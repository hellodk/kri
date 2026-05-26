# fleet_platform/services/llm_caller.py
import httpx

OPENAI_COMPAT_TIMEOUT = 90.0  # local Ollama models can be slow


class LLMCallError(Exception):
    """Raised when an LLM provider call fails — wraps transport and parse errors."""


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

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=OPENAI_COMPAT_TIMEOUT) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
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
    return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


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
    content: str = message.content[0].text
    return content, message.usage.input_tokens, message.usage.output_tokens
