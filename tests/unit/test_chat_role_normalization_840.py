"""
Tests for #840 Issue C2 — LLMAssistant chat role normalization.

Source-contract style: parses LLMAssistant.tsx directly and asserts on its
content to guarantee the normalization algorithm is present and structurally
correct.
"""

from pathlib import Path

COMPONENT = Path("frontend/src/components/LLMAssistant.tsx")
_SOURCE = COMPONENT.read_text()

# Locate handleSubmit for scoped assertions
_SUBMIT_START = _SOURCE.index("const handleSubmit = ()")
_SUBMIT_END = _SOURCE.find("const handleStop", _SUBMIT_START)
_SUBMIT_FN = _SOURCE[_SUBMIT_START:_SUBMIT_END]


# ---------------------------------------------------------------------------
# 1. History construction filters empty-content and error messages
# ---------------------------------------------------------------------------


def test_history_filters_error_messages():
    """History must exclude error-flagged messages."""
    assert "m.error" in _SUBMIT_FN, "handleSubmit history must filter out error messages via m.error"


def test_history_filters_empty_content():
    """History must exclude messages with empty/whitespace content."""
    assert "content.trim" in _SUBMIT_FN or "content !== ''" in _SUBMIT_FN, (
        "handleSubmit history must filter out empty-content messages"
    )


# ---------------------------------------------------------------------------
# 2. Consecutive same-role collapsing
# ---------------------------------------------------------------------------


def test_consecutive_role_collapsing_present():
    """History normalisation must collapse consecutive same-role messages."""
    assert "prev.role === msg.role" in _SUBMIT_FN, (
        "consecutive same-role check (prev.role === msg.role) not found in handleSubmit"
    )


def test_consecutive_role_collapsing_joins_content():
    """Collapsing must join content so nothing is silently dropped."""
    assert "prev.content" in _SUBMIT_FN and "msg.content" in _SUBMIT_FN, (
        "collapsed messages must have their content merged into prev.content"
    )


# ---------------------------------------------------------------------------
# 3. Leading assistant turns are stripped
# ---------------------------------------------------------------------------


def test_leading_assistant_turns_stripped():
    """History must strip any leading assistant turns (LLM expects user first)."""
    assert "role === 'assistant'" in _SUBMIT_FN and ".shift()" in _SUBMIT_FN, (
        "leading assistant turn stripping (.shift()) not found in handleSubmit"
    )


# ---------------------------------------------------------------------------
# 4. Final slice still limits history to 10 turns
# ---------------------------------------------------------------------------


def test_final_history_slice_present():
    """History must be sliced to at most 10 turns before sending."""
    assert ".slice(-10)" in _SUBMIT_FN, ".slice(-10) not found — final history window limit missing"


# ---------------------------------------------------------------------------
# 5. Normalized history is passed to streamQuery
# ---------------------------------------------------------------------------


def test_normalized_history_passed_to_stream():
    """The normalizedHistory (or history) variable must be passed to streamQuery."""
    assert "history" in _SUBMIT_FN and "streamQuery(" in _SUBMIT_FN, (
        "normalized history is not passed to streamQuery in handleSubmit"
    )


# ---------------------------------------------------------------------------
# 6. Empty-stream turns are marked as errors
# ---------------------------------------------------------------------------


def test_empty_stream_marked_as_error():
    """A zero-token done event must produce a visible error on the assistant bubble."""
    # The check should be in the onDone callback inside handleSubmit
    assert "output_tokens" in _SUBMIT_FN and ("empty stream" in _SUBMIT_FN.lower() or "isEmpty" in _SUBMIT_FN), (
        "empty-stream detection (output_tokens === 0 → error) not found in handleSubmit onDone"
    )


def test_empty_stream_error_message_meaningful():
    """Empty-stream error message must be human-readable, not a raw boolean."""
    assert "No response received" in _SOURCE or "empty stream" in _SOURCE.lower(), (
        "empty-stream error message must be informative, not just 'undefined' or 'true'"
    )


# ---------------------------------------------------------------------------
# 7. Regression: history capture still happens BEFORE addMessage (#303)
# ---------------------------------------------------------------------------


def test_history_capture_before_add_message():
    """History capture must still come before addMessage (regression guard for #303)."""
    history_pos = _SUBMIT_FN.find("const history = normalizedHistory")
    add_msg_pos = _SUBMIT_FN.find("addMessage({ role: 'user'")
    assert history_pos != -1, "normalized history assignment not found in handleSubmit"
    assert add_msg_pos != -1, "addMessage({ role: 'user' not found in handleSubmit"
    assert history_pos < add_msg_pos, (
        "history must be captured BEFORE addMessage to avoid including the current "
        "user message in the history sent to the LLM"
    )
