# fleet_platform/services/llm_caller.py
import json as _json
import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# Per-chunk read timeout: as long as tokens keep flowing, the request won't
# abort — only a silent/stalled stream triggers this. Connect timeout is
# separate so fast failures (wrong URL) still surface quickly (#274).
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0  # max silence between consecutive SSE chunks
_STREAM_TIMEOUT = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=5.0)

# Anthropic's SDK defaults to a 600s timeout, which would pin a DB connection
# and event-loop slot on a stalled call. Bound it to the same budget as the
# OpenAI-compatible path (#667).
_ANTHROPIC_TIMEOUT = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=5.0)

# Claude context window when the caller doesn't supply one. Used only to size
# the truncation budget so a runaway prompt can't blow the window (#667).
_ANTHROPIC_DEFAULT_CTX = 200_000

# Rough bytes-per-token estimate shared by all prompt-budgeting math.
_CHARS_PER_TOKEN = 4


def _budget_inputs(
    *,
    system_prompt: str,
    history: list[dict] | None,
    user_prompt: str,
    ctx: int,
    max_tokens: int,
) -> tuple[str, list[dict]]:
    """Fit system prompt + history + user prompt under ONE input ceiling (#667).

    Previously the system-prompt truncation budget and the ``history[-10:]``
    slice were independent and additive, so their sum could exceed the model
    window (~47% over on the default 8k). Here a single ceiling — the context
    window minus the reserved output (``max_tokens``) — is shared across all
    inputs, prioritising the user prompt, then the grounding tail of the system
    prompt, then the most recent history. Returns the (possibly truncated)
    system prompt and the history messages that fit.
    """
    history = list(history or [])
    input_chars = max(1000, (ctx - max_tokens) * _CHARS_PER_TOKEN - 200)
    user_chars = len(user_prompt or "")
    remaining = max(1000, input_chars - user_chars)
    # History gets at most half the remaining budget, most-recent-first, so a
    # long back-and-forth can never starve the system prompt's grounding rules.
    history_budget = remaining // 2
    kept: list[dict] = []
    used = 0
    for msg in reversed(history[-10:]):
        c = len(str(msg.get("content", "")))
        if used + c > history_budget:
            break
        kept.insert(0, msg)
        used += c
    system_budget = max(1000, remaining - used)
    return _truncate_system_prompt(system_prompt, system_budget), kept


class LLMCallError(Exception):
    """Raised when an LLM provider call fails — wraps transport and parse errors."""


def _describe_http_error(exc: "httpx.HTTPStatusError", base_url: str) -> str:
    status = exc.response.status_code
    body = ""
    try:
        body = exc.response.text or ""
    except Exception:  # noqa: BLE001
        body = ""
    body = body.strip().replace("\n", " ")[:300]
    msg = f"HTTP {status} from {base_url}"
    if body:
        msg += f": {body}"
    if status == 404:
        msg += " (the configured model is not loaded on this endpoint — pick an available model in Settings → LLM)"
    elif status in (401, 403):
        msg += " (authentication failed — check the endpoint API key in Settings → LLM)"
    return msg


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


# Anchor marking the start of the pinned tail (Rules + grounding rules). The
# context builder always emits these as the final block, and they must survive
# truncation on small-context endpoints (#575).
_GROUNDING_ANCHOR = "## Rules"
_TRUNCATION_MARKER = "\n[context truncated for model capacity]\n"


def _truncate_system_prompt(system_prompt: str, max_system_chars: int) -> str:
    """Truncate the MIDDLE of the system prompt, never the grounding-rules tail (#575).

    The anti-hallucination grounding rules are emitted as the final block of the
    prompt. The previous implementation truncated from the tail, so on a
    small-context endpoint the grounding rules were cut first. This preserves the
    head (role + fleet snapshot) and the entire pinned tail (Rules + grounding),
    dropping only the middle (retrieved chunks / node records) when over budget.
    """
    if len(system_prompt) <= max_system_chars:
        return system_prompt

    anchor = system_prompt.rfind(_GROUNDING_ANCHOR)
    tail = system_prompt[anchor:] if anchor != -1 else ""

    head_budget = max_system_chars - len(tail) - len(_TRUNCATION_MARKER)
    if head_budget <= 0:
        # The pinned tail alone exceeds the budget — keep the grounding rules
        # (the most important part) by retaining the final max_system_chars.
        if tail:
            return (_TRUNCATION_MARKER + tail)[-max_system_chars:]
        return system_prompt[:max_system_chars] + _TRUNCATION_MARKER

    return system_prompt[:head_budget] + _TRUNCATION_MARKER + tail


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

    # Unified input budget: system + history + user share one ceiling (#667).
    system_prompt, budgeted_history = _budget_inputs(
        system_prompt=system_prompt,
        history=history,
        user_prompt=user_prompt,
        ctx=ctx,
        max_tokens=max_tokens,
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(budgeted_history)
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
                    data_str = line[len("data:") :].strip()
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
        raise LLMCallError(_describe_http_error(exc, base_url)) from exc
    except httpx.ReadTimeout as exc:
        raise LLMCallError(
            f"Stream stalled — no chunk received within {_READ_TIMEOUT}s. Model may be overloaded or still loading."
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMCallError(f"Connection timed out after {_CONNECT_TIMEOUT}s") from exc
    except httpx.RequestError as exc:
        raise LLMCallError(f"Network error: {exc}") from exc

    content: str = "".join(content_parts)

    # A genuinely empty response with zero completion tokens indicates a
    # server-side crash (e.g. vllm-mlx position_embeddings error) that returns
    # HTTP 200 but delivers nothing. Treat as a hard failure so the endpoint
    # gets marked unhealthy (#840).
    if not content and completion_tokens == 0:
        raise LLMCallError("Model returned no content (0 tokens) — the endpoint or model may be broken")

    # Strip <think>...</think> reasoning blocks from thinking models
    if is_thinking:
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
        if not content:
            raise LLMCallError("Model returned only a thinking block with no final answer")
    else:
        # Echo-detection only makes sense for small non-thinking models
        content = _validate_response(content, system_prompt)

    return content, prompt_tokens, completion_tokens


async def call_openai_compat_tools(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
    history: list[dict] | None = None,
    model_context_length: int | None = None,
    model_capabilities: list[str] | None = None,
) -> tuple[dict, int, int]:
    """Native-tool-calling sibling of :func:`call_openai_compat` (#651).

    Sends a top-level ``tools=[...]`` array so the endpoint can emit native
    OpenAI ``tool_calls`` rather than prompt-embedded JSON. Returns the assistant
    ``message`` dict — ``{"role", "content", "tool_calls"}`` — alongside the same
    ``(input_tokens, output_tokens)`` counts as the plain caller, so the planner
    can feed it straight into :func:`extract_tool_calls`.

    Kept separate from :func:`call_openai_compat` on purpose: the existing 3-tuple
    ``(content, in, out)`` contract has many callers and must not change shape.
    """
    import re as _re

    from fleet_platform.services.tool_calling import ToolCallAccumulator

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    is_thinking = bool(model_capabilities and "thinking" in model_capabilities)

    ctx = model_context_length or 8192
    if max_tokens > ctx:
        max_tokens = ctx

    system_prompt, budgeted_history = _budget_inputs(
        system_prompt=system_prompt,
        history=history,
        user_prompt=user_prompt,
        ctx=ctx,
        max_tokens=max_tokens,
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(budgeted_history)
    messages.append({"role": "user", "content": user_prompt})

    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "top_p": 0.9,
        "messages": messages,
        "tools": tools,
        "stream": True,
    }
    # Stop tokens can truncate a native tool-call argument stream mid-JSON, so we
    # omit them here regardless of model size — the accumulator needs the full
    # arguments fragment sequence to parse.

    content_parts: list[str] = []
    accumulator = ToolCallAccumulator()
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
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                    except _json.JSONDecodeError:
                        continue
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                        if delta.get("tool_calls"):
                            accumulator.add_delta(delta)
                    if "usage" in chunk and chunk["usage"]:
                        prompt_tokens = chunk["usage"].get("prompt_tokens", 0) or 0
                        completion_tokens = chunk["usage"].get("completion_tokens", 0) or 0
    except httpx.HTTPStatusError as exc:
        raise LLMCallError(_describe_http_error(exc, base_url)) from exc
    except httpx.ReadTimeout as exc:
        raise LLMCallError(
            f"Stream stalled — no chunk received within {_READ_TIMEOUT}s. Model may be overloaded or still loading."
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMCallError(f"Connection timed out after {_CONNECT_TIMEOUT}s") from exc
    except httpx.RequestError as exc:
        raise LLMCallError(f"Network error: {exc}") from exc

    content: str = "".join(content_parts)
    finalized = accumulator.finalize()
    # Re-emit as raw OpenAI-shaped tool_calls so extract_tool_calls() can
    # normalize them through the same path as a non-streaming response.
    tool_calls: list[dict] = [
        {"id": tc.id, "function": {"name": tc.name, "arguments": _json.dumps(tc.arguments)}} for tc in finalized
    ]

    # Empty AND no tool calls AND zero tokens means a server-side crash returning
    # HTTP 200 with nothing (#840). A tool-call-only reply (no content) is valid.
    if not content and not tool_calls and completion_tokens == 0:
        raise LLMCallError("Model returned no content (0 tokens) — the endpoint or model may be broken")

    if is_thinking:
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
    elif not tool_calls and content:
        # Only validate plain-text final answers; a tool-call reply legitimately
        # carries little or no prose and must not be flagged as an echo.
        content = _validate_response(content, system_prompt)

    message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    return message, prompt_tokens, completion_tokens


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
    model_context_length: int | None = None,
) -> tuple[str, int, int]:
    """
    Call Anthropic Claude via the native anthropic SDK.
    Returns (content, input_tokens, output_tokens).

    Applies the same unified prompt budget as the OpenAI-compatible path and a
    bounded request timeout so a stalled call can't pin a DB connection for the
    SDK's 600s default (#667).
    """
    import anthropic

    ctx = model_context_length or _ANTHROPIC_DEFAULT_CTX
    system_prompt, budgeted_history = _budget_inputs(
        system_prompt=system_prompt,
        history=history,
        user_prompt=user_prompt,
        ctx=ctx,
        max_tokens=min(max_tokens, ctx),
    )

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_ANTHROPIC_TIMEOUT)
    messages: list[dict] = list(budgeted_history)
    messages.append({"role": "user", "content": user_prompt})
    try:
        message = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]  # dict is runtime-compatible with MessageParam
        )
    except anthropic.APIError as exc:
        raise LLMCallError(f"Anthropic API error: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise LLMCallError(f"Anthropic call timed out after {_READ_TIMEOUT}s") from exc
    block = message.content[0]
    content: str = block.text if hasattr(block, "text") else ""
    if not content and message.usage.output_tokens == 0:
        raise LLMCallError("Model returned no content (0 tokens) — the endpoint or model may be broken")
    return content, message.usage.input_tokens, message.usage.output_tokens


async def call_anthropic_tools(
    *,
    api_key: str,
    model: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
    history: list[dict] | None = None,
    model_context_length: int | None = None,
) -> tuple[dict, int, int]:
    """Native-tool-calling sibling of :func:`call_anthropic` (#651).

    Sends Anthropic ``tools=[...]`` and flattens the response content blocks into
    an assistant ``message`` dict — text blocks joined into ``content`` and any
    ``tool_use`` blocks re-emitted under ``tool_calls`` — so the planner can pass
    it straight to :func:`extract_tool_calls` (which understands the ``tool_use``
    shape). Returns ``(message, input_tokens, output_tokens)``.
    """
    import anthropic

    ctx = model_context_length or _ANTHROPIC_DEFAULT_CTX
    system_prompt, budgeted_history = _budget_inputs(
        system_prompt=system_prompt,
        history=history,
        user_prompt=user_prompt,
        ctx=ctx,
        max_tokens=min(max_tokens, ctx),
    )

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_ANTHROPIC_TIMEOUT)
    messages: list[dict] = list(budgeted_history)
    messages.append({"role": "user", "content": user_prompt})
    try:
        message = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
        )
    except anthropic.APIError as exc:
        raise LLMCallError(f"Anthropic API error: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise LLMCallError(f"Anthropic call timed out after {_READ_TIMEOUT}s") from exc

    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in message.content or []:
        btype = getattr(block, "type", None)
        if btype == "tool_use":
            tool_calls.append(
                {
                    "type": "tool_use",
                    "id": getattr(block, "id", None),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                }
            )
        else:
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)

    content = "".join(text_parts)
    if not content and not tool_calls and message.usage.output_tokens == 0:
        raise LLMCallError("Model returned no content (0 tokens) — the endpoint or model may be broken")

    result_message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    return result_message, message.usage.input_tokens, message.usage.output_tokens


# ── Streaming variants (SSE-friendly) ────────────────────────────────────────
# These yield one event per delta so the API route can re-emit them as SSE
# straight to the browser. Each call emits at least one ``done`` event with
# token usage and the joined content; callers are expected to forward that
# to the query log writer.
#
# Event shapes:
#   {"type": "delta", "text": "<chunk>"}
#   {"type": "done",  "content": "<full>", "input_tokens": int, "output_tokens": int}
#   {"type": "error", "error": "<message>"}


async def stream_openai_compat(
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
) -> AsyncIterator[dict]:
    """Stream an OpenAI-compatible /chat/completions response chunk-by-chunk.

    Performs the same prompt budgeting, thinking-block stripping, and
    echo-detection as :func:`call_openai_compat` so the streamed text is
    consistent with the buffered call. Cancelling the consumer (closing the
    HTTP response) causes httpx to abort the upstream request.
    """
    import re as _re

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    is_thinking = bool(model_capabilities and "thinking" in model_capabilities)

    ctx = model_context_length or 8192
    if max_tokens > ctx:
        max_tokens = ctx

    # Unified input budget: system + history + user share one ceiling (#667).
    system_prompt, budgeted_history = _budget_inputs(
        system_prompt=system_prompt,
        history=history,
        user_prompt=user_prompt,
        ctx=ctx,
        max_tokens=max_tokens,
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(budgeted_history)
    messages.append({"role": "user", "content": user_prompt})

    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "top_p": 0.9,
        "messages": messages,
        "stream": True,
    }
    if not is_thinking:
        payload["stop"] = ["</s>", "<|im_end|>", "<|endoftext|>", "Human:", "User:"]

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
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                    except _json.JSONDecodeError:
                        continue
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        text = delta.get("content")
                        if text:
                            content_parts.append(text)
                            yield {"type": "delta", "text": text}
                    if "usage" in chunk and chunk["usage"]:
                        prompt_tokens = chunk["usage"].get("prompt_tokens", 0) or 0
                        completion_tokens = chunk["usage"].get("completion_tokens", 0) or 0
    except httpx.HTTPStatusError as exc:
        yield {"type": "error", "error": _describe_http_error(exc, base_url)}
        return
    except httpx.ReadTimeout:
        yield {
            "type": "error",
            "error": f"Stream stalled — no chunk received within {_READ_TIMEOUT}s.",
        }
        return
    except httpx.TimeoutException:
        yield {"type": "error", "error": f"Connection timed out after {_CONNECT_TIMEOUT}s"}
        return
    except httpx.RequestError as exc:
        yield {"type": "error", "error": f"Network error: {exc}"}
        return

    content = "".join(content_parts)

    # A genuinely empty response with zero completion tokens indicates a
    # server-side crash that returns HTTP 200 but delivers nothing (#840).
    if not content and completion_tokens == 0:
        yield {
            "type": "error",
            "error": "Model returned no content (0 tokens) — the endpoint or model may be broken",
        }
        return

    if is_thinking:
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
        if not content:
            yield {"type": "error", "error": "Model returned only a thinking block with no final answer"}
            return
    else:
        content = _validate_response(content, system_prompt)

    yield {
        "type": "done",
        "content": content,
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
    }


async def stream_anthropic(
    *,
    api_key: str,
    model: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
    history: list[dict] | None = None,
    model_context_length: int | None = None,
) -> AsyncIterator[dict]:
    """Stream Claude messages using the native anthropic SDK's messages.stream.

    Yields one ``delta`` event per text chunk plus a final ``done`` event with
    token counts. Errors surface as a single ``error`` event. Applies the same
    unified prompt budget and bounded timeout as :func:`call_anthropic` (#667).
    """
    import anthropic

    ctx = model_context_length or _ANTHROPIC_DEFAULT_CTX
    system_prompt, budgeted_history = _budget_inputs(
        system_prompt=system_prompt,
        history=history,
        user_prompt=user_prompt,
        ctx=ctx,
        max_tokens=min(max_tokens, ctx),
    )

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_ANTHROPIC_TIMEOUT)
    messages: list[dict] = list(budgeted_history)
    messages.append({"role": "user", "content": user_prompt})

    content_parts: list[str] = []
    input_tokens = 0
    output_tokens = 0

    try:
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    content_parts.append(text)
                    yield {"type": "delta", "text": text}
            final_message = await stream.get_final_message()
            input_tokens = final_message.usage.input_tokens
            output_tokens = final_message.usage.output_tokens
    except anthropic.APIError as exc:
        yield {"type": "error", "error": f"Anthropic API error: {exc}"}
        return
    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "error": f"Anthropic stream failed: {exc}"}
        return

    content = "".join(content_parts)
    if not content and output_tokens == 0:
        yield {
            "type": "error",
            "error": "Model returned no content (0 tokens) — the endpoint or model may be broken",
        }
        return
    yield {
        "type": "done",
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
