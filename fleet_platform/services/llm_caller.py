# fleet_platform/services/llm_caller.py
import json as _json

import httpx

# Per-chunk read timeout: as long as tokens keep flowing, the request won't
# abort — only a silent/stalled stream triggers this. Connect timeout is
# separate so fast failures (wrong URL) still surface quickly (#274).
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0   # max silence between consecutive SSE chunks
_STREAM_TIMEOUT = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=5.0)


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
    history: list[dict] | None = None,
    model_context_length: int | None = None,
    model_capabilities: list[str] | None = None,
) -> tuple[str, int, int]:
    """
    Call an OpenAI-compatible /chat/completions endpoint.
    Returns (content, input_tokens, output_tokens).
    Compatible with: OpenAI, Ollama, LM Studio, vLLM, Groq, Mistral, Together, exo.

    model_context_length: if known, used to size the system-prompt budget and
        clamp max_tokens; falls back to an 8k conservative default.
    model_capabilities: list of strings from /v1/models (e.g. ["text","thinking"]).
        Thinking models skip echo-detection, strip <think> blocks, and omit
        small-model stop tokens (#273).
    """
    import re as _re

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    is_thinking = bool(model_capabilities and "thinking" in model_capabilities)

    # Clamp max_tokens to the model's context window when known
    ctx = model_context_length or 8192
    if max_tokens > ctx:
        max_tokens = ctx

    # Budget the system prompt so it fits in the context window.
    # Reserve max_tokens chars for output; allow the rest (≈ 4 chars/token).
    max_system_chars = max(1000, (ctx - max_tokens) * 4 - 200)
    if len(system_prompt) > max_system_chars:
        system_prompt = system_prompt[:max_system_chars] + "\n[context truncated for model capacity]"

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-10:])
    messages.append({"role": "user", "content": user_prompt})

    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "top_p": 0.9,
        "messages": messages,
    }
    # Small-model stop tokens are counter-productive on thinking/frontier models
    if not is_thinking:
        payload["stop"] = ["</s>", "<|im_end|>", "<|endoftext|>", "Human:", "User:"]
    payload["stream"] = True

    content_parts: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0

    try:
        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{normalize_openai_base_url(base_url)}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                    except _json.JSONDecodeError:
                        continue
                    # Aggregate delta content
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                    # Some providers send usage in the final chunk
                    if "usage" in chunk and chunk["usage"]:
                        prompt_tokens = chunk["usage"].get("prompt_tokens", 0) or 0
                        completion_tokens = chunk["usage"].get("completion_tokens", 0) or 0
    except httpx.HTTPStatusError as exc:
        raise LLMCallError(f"HTTP {exc.response.status_code} from {base_url}") from exc
    except httpx.ReadTimeout as exc:
        raise LLMCallError(
            f"Stream stalled — no chunk received within {_READ_TIMEOUT}s. "
            "Model may be overloaded or still loading."
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMCallError(f"Connection timed out after {_CONNECT_TIMEOUT}s") from exc
    except httpx.RequestError as exc:
        raise LLMCallError(f"Network error: {exc}") from exc

    content: str = "".join(content_parts)

    if not content:
        content = "[Model returned an empty stream response. Try a larger model or simplify your question.]"

    # Strip <think>...</think> reasoning blocks from thinking models
    if is_thinking:
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
        if not content:
            content = "[Model returned only a thinking block with no final answer.]"
    else:
        # Echo-detection only makes sense for small non-thinking models
        content = _validate_response(content, system_prompt)

    return content, prompt_tokens, completion_tokens


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
    history: list[dict] | None = None,
) -> tuple[str, int, int]:
    """
    Call Anthropic Claude via the native anthropic SDK.
    Returns (content, input_tokens, output_tokens).
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)
    messages: list[dict] = []
    if history:
        messages.extend(history[-10:])
    messages.append({"role": "user", "content": user_prompt})
    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,  # type: ignore[arg-type]  # dict is runtime-compatible with MessageParam
    )
    block = message.content[0]
    content: str = block.text if hasattr(block, "text") else ""
    return content, message.usage.input_tokens, message.usage.output_tokens
