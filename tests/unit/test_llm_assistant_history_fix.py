"""Tests for #303 — duplicate user turn bug in LLMAssistant."""


def test_llm_assistant_captures_history_before_addmessage():
    """LLMAssistant must capture history BEFORE addMessage to avoid duplicate user turn."""
    with open("frontend/src/components/LLMAssistant.tsx") as f:
        content = f.read()

    # The history capture must come before addMessage({ role: 'user' in handleSubmit
    submit_fn_start = content.index("const handleSubmit = ()")
    # Find the next function definition to bound the search
    next_func = content.find("const handleKeyDown", submit_fn_start)
    submit_fn = content[submit_fn_start:next_func]

    history_capture_pos = submit_fn.find("const rawHistory = messages")
    # Look for the specific addMessage call that adds the user message
    add_msg_pos = submit_fn.find("addMessage({ role: 'user'")

    assert history_capture_pos != -1, "history capture not found in handleSubmit"
    assert add_msg_pos != -1, "addMessage({ role: 'user' not found in handleSubmit"
    assert history_capture_pos < add_msg_pos, (
        "history must be captured BEFORE addMessage to avoid including "
        "the current user message in the history sent to the LLM"
    )


def test_filter_before_slice_in_history():
    """filter(error) must come before slice() so we keep last N valid messages."""
    with open("frontend/src/components/LLMAssistant.tsx") as f:
        content = f.read()

    # find the filter and slice positions relative to the history capture
    history_start = content.find("const rawHistory = messages")
    history_end = content.find("streamQuery(", history_start)
    capture_block = content[history_start:history_end]

    filter_pos = capture_block.find(".filter(m => !m.error")
    slice_pos = capture_block.find(".slice(-20)")

    assert filter_pos != -1, "filter(!m.error) not found in history capture"
    assert slice_pos != -1, "slice(-20) not found in history capture"
    assert filter_pos < slice_pos, "filter(!m.error) must come before slice(-20)"


def test_stream_call_receives_text_and_history():
    """The stream call must pass both the prompt text and pre-captured history.

    LLMAssistant was refactored from a react-query mutation to streamQuery();
    the #303 guarantee still holds — history is captured before addMessage and
    handed to the stream alongside the prompt text.
    """
    with open("frontend/src/components/LLMAssistant.tsx") as f:
        content = f.read()

    submit_fn_start = content.index("const handleSubmit = ()")
    next_func = content.find("const handleStop", submit_fn_start)
    submit_fn = content[submit_fn_start:next_func]

    assert "streamQuery(" in submit_fn, "handleSubmit must dispatch the prompt via streamQuery()"
    assert "prompt: text" in submit_fn and "history" in submit_fn, (
        "stream call must pass the prompt text and pre-captured history, not just text"
    )
