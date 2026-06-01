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

    history_capture_pos = submit_fn.find("const history = messages")
    # Look for the specific addMessage call that adds the user message
    add_msg_pos = submit_fn.find("addMessage({ role: 'user'")

    assert history_capture_pos != -1, "history capture not found in handleSubmit"
    assert add_msg_pos != -1, "addMessage({ role: 'user' not found in handleSubmit"
    assert history_capture_pos < add_msg_pos, (
        "history must be captured BEFORE addMessage to avoid including "
        "the current user message in the history sent to the LLM"
    )


def test_filter_before_slice_in_history():
    """filter(error) must come before slice(-10) so we keep last 10 valid messages."""
    with open("frontend/src/components/LLMAssistant.tsx") as f:
        content = f.read()

    # find the filter and slice positions relative to the history capture
    history_start = content.find("const history = messages")
    history_end = content.find("mutation.mutate", history_start)
    capture_block = content[history_start:history_end]

    filter_pos = capture_block.find(".filter(m => !m.error)")
    slice_pos = capture_block.find(".slice(-10)")

    assert filter_pos != -1, "filter(!m.error) not found in history capture"
    assert slice_pos != -1, "slice(-10) not found in history capture"
    assert filter_pos < slice_pos, "filter(!m.error) must come before slice(-10)"


def test_mutation_receives_text_and_history():
    """mutation.mutate() must pass both text and pre-captured history, not just text."""
    with open("frontend/src/components/LLMAssistant.tsx") as f:
        content = f.read()

    # Check that mutationFn accepts { text, history }
    mutation_sig = content[content.find("mutationFn:"):content.find("onSuccess")]
    assert "{ text, history }" in mutation_sig, (
        "mutationFn must accept { text, history } destructured object"
    )

    # Check that mutation.mutate is called with { text, history }
    submit_fn_start = content.index("const handleSubmit = ()")
    next_func = content.find("const handleKeyDown", submit_fn_start)
    submit_fn = content[submit_fn_start:next_func]

    assert "mutation.mutate" in submit_fn and "text, history" in submit_fn, (
        "mutation.mutate() must be called with { text, history }, not just text"
    )
