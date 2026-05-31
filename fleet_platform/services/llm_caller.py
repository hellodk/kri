# fleet_platform/services/llm_caller.py
import httpx

OPENAI_COMPAT_TIMEOUT = 90.0  # local Ollama models can be slow


class LLMCallError(Exception):
    """Raised when an LLM provider call fails — wraps transport and parse errors."""


def normalize_openai_base_url(base_url: str) -> str:
    """Return *base_url* with any trailing ``/v1`` and trailing slashes removed.

    OpenAI-compatible endpoints are conventionally written either with the
    ``/v1`` suffix (OpenAI, Groq) or without it (some local servers). Callers
    append the version segment themselves (``/v1/chat/completions``,
    ``/v1/models``), so stripping a trailing ``/v1`` here makes both forms
    resolve identically and avoids a doubled ``/v1/v1`` path (#272). Provider
    path prefixes such as Groq's ``/openai`` are preserved.
    """
    cleaned = base_url.strip().rstrip("/")
    if cleaned.endswith("/v1"):
        cleaned = cleaned[: -len("/v1")]
    return cleaned.rstrip("/")


async def call_openai_compat(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    """
    Call an OpenAI-compatible /chat/completions endpoint.
    Returns (content, input_tokens, output_tokens).
    Compatible with: OpenAI, Ollama, LM Studio, vLLM, Groq, Mistral, Together.
    Raises: LLMCallError on HTTP errors, timeouts, or unexpected response shape.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Truncate system prompt for small local models (< 8k context)
    MAX_SYSTEM_CHARS = 2000
    if len(system_prompt) > MAX_SYSTEM_CHARS:
        system_prompt = system_prompt[:MAX_SYSTEM_CHARS] + "\n[context truncated for model capacity]"

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.3,       # reduce echo/repetition vs pure greedy decoding
        "top_p": 0.9,
        "stop": ["</s>", "<|im_end|>", "<|endoftext|>", "Human:", "User:"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=OPENAI_COMPAT_TIMEOUT) as client:
            response = await client.post(
                f"{normalize_openai_base_url(base_url)}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMCallError(f"HTTP {exc.response.status_code} from {base_url}") from exc
    except httpx.TimeoutException as exc:
        raise LLMCallError(f"Request timed out after {OPENAI_COMPAT_TIMEOUT}s") from exc
    except httpx.RequestError as exc:
        raise LLMCallError(f"Network error: {exc}") from exc

    try:
        data = response.json()
        content: str = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMCallError(f"Unexpected response shape from {base_url}: {exc}") from exc

    usage = data.get("usage", {})
    # Detect garbled output — small local models sometimes echo the system prompt
    content = _validate_response(content, system_prompt)
    return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def _validate_response(content: str, system_prompt: str) -> str:
    """Detect common small-model failure modes and return a clean error message."""
    stripped = content.strip()
    # Too short to be useful
    if len(stripped) < 5:
        return "[Model returned an empty response. Try a larger model or simplify your question.]"
    # Echoing the system prompt (first 40 chars match)
    if len(stripped) > 20 and system_prompt[:40].lower().replace("\n", " ") in stripped[:200].lower():
        return "[Model echoed its system prompt — it may be too small for this task. Try a 7B+ model.]"
    # Contains common chat-template artifacts
    artifacts = ["<|im_start|>", "<|im_end|>", "<|system|>", "<|user|>", "<|assistant|>"]
    if any(a in content for a in artifacts):
        # Strip them and return if something useful remains
        for a in artifacts:
            content = content.replace(a, "")
        content = content.strip()
        if len(content) < 5:
            return "[Model response contained only template tokens. Configure chat_template in llama.cpp.]"
    return content


async def call_anthropic(
    *,
    api_key: str,
    model: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    """
    Call Anthropic Claude via the native anthropic SDK.
    Returns (content, input_tokens, output_tokens).
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    block = message.content[0]
    content: str = block.text if hasattr(block, "text") else ""
    return content, message.usage.input_tokens, message.usage.output_tokens
