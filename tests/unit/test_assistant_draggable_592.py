"""
Tests for issue #592: Make AI Assistant widget draggable, translucent, fade in/out.

Source-contract style: parses LLMAssistant.tsx directly and asserts on its content.
"""

from pathlib import Path

COMPONENT = Path(__file__).parent.parent.parent / "frontend" / "src" / "components" / "LLMAssistant.tsx"
_SOURCE = COMPONENT.read_text()


# ---------------------------------------------------------------------------
# 1. Drag event handlers present on both the icon and the panel header
# ---------------------------------------------------------------------------


def test_pointer_down_handler_present():
    """onPointerDown handler must be present (drag start)."""
    assert "onPointerDown" in _SOURCE, "onPointerDown not found in LLMAssistant.tsx — drag start handler missing"


def test_pointer_move_handler_present():
    """onPointerMove handler must be present (drag move)."""
    assert "onPointerMove" in _SOURCE, "onPointerMove not found in LLMAssistant.tsx — drag move handler missing"


def test_pointer_up_handler_present():
    """onPointerUp handler must be present (drag end)."""
    assert "onPointerUp" in _SOURCE, "onPointerUp not found in LLMAssistant.tsx — drag end handler missing"


# ---------------------------------------------------------------------------
# 2. localStorage used with the correct key
# ---------------------------------------------------------------------------


def test_localstorage_key_present():
    """localStorage must be used with key 'llm-assistant-pos'."""
    assert "'llm-assistant-pos'" in _SOURCE or '"llm-assistant-pos"' in _SOURCE, (
        "localStorage key 'llm-assistant-pos' not found in LLMAssistant.tsx"
    )


def test_localstorage_getitem_present():
    """localStorage.getItem must be called (position restore on mount)."""
    assert "localStorage.getItem" in _SOURCE, "localStorage.getItem not found — persisted position not being restored"


def test_localstorage_setitem_present():
    """localStorage.setItem must be called (position persist on drag end)."""
    assert "localStorage.setItem" in _SOURCE, "localStorage.setItem not found — drag position not being persisted"


# ---------------------------------------------------------------------------
# 3. Viewport clamping: window.innerWidth / window.innerHeight with Math.min/max
# ---------------------------------------------------------------------------


def test_viewport_clamp_inner_width():
    """window.innerWidth must be referenced (horizontal clamp)."""
    assert "window.innerWidth" in _SOURCE, "window.innerWidth not found — horizontal viewport clamping missing"


def test_viewport_clamp_inner_height():
    """window.innerHeight must be referenced (vertical clamp)."""
    assert "window.innerHeight" in _SOURCE, "window.innerHeight not found — vertical viewport clamping missing"


def test_viewport_clamp_math_min():
    """Math.min must be used for clamping."""
    assert "Math.min" in _SOURCE, "Math.min not found — clamping to viewport max not implemented"


def test_viewport_clamp_math_max():
    """Math.max must be used for clamping."""
    assert "Math.max" in _SOURCE, "Math.max not found — clamping to viewport min (0) not implemented"


# ---------------------------------------------------------------------------
# 4. Click-vs-drag movement threshold of 5px
# ---------------------------------------------------------------------------


def test_click_drag_threshold_present():
    """A numeric threshold of 5 must be used to distinguish click from drag."""
    # Accept: < 5 or <= 5 comparisons involving a distance/movement variable
    import re

    # Look for "< 5" or "<= 5" or "5 >" etc. near movement/distance context
    pattern = re.compile(r"[<>]=?\s*5\b|5\s*[<>]=?")
    assert pattern.search(_SOURCE), (
        "No movement threshold of 5px found in LLMAssistant.tsx — click-vs-drag disambiguation missing"
    )


# ---------------------------------------------------------------------------
# 5. Translucent panel: bg-white/90 + backdrop-blur
# ---------------------------------------------------------------------------


def test_panel_translucent_bg():
    """Panel must use bg-white/90 (translucent white background)."""
    assert "bg-white/90" in _SOURCE, "bg-white/90 not found — translucent panel background missing"


def test_panel_backdrop_blur():
    """Panel must use backdrop-blur for frosted glass effect."""
    assert "backdrop-blur" in _SOURCE, "backdrop-blur not found — panel frosted-glass effect missing"


# ---------------------------------------------------------------------------
# 6. Fade transition: transition-all/opacity, opacity-100, opacity-0, scale-95
# ---------------------------------------------------------------------------


def test_fade_transition_class():
    """Fade must use transition-all or transition-opacity."""
    assert "transition-all" in _SOURCE or "transition-opacity" in _SOURCE, (
        "No transition-all or transition-opacity found — fade animation missing"
    )


def test_fade_opacity_visible():
    """opacity-100 must be present (visible state)."""
    assert "opacity-100" in _SOURCE, "opacity-100 not found — panel visible state class missing"


def test_fade_opacity_hidden():
    """opacity-0 must be present (hidden/faded-out state)."""
    assert "opacity-0" in _SOURCE, "opacity-0 not found — panel hidden state class missing"


def test_fade_scale_hidden():
    """scale-95 must be present (slight scale-down when closed)."""
    assert "scale-95" in _SOURCE, "scale-95 not found — closed panel scale class missing"


# ---------------------------------------------------------------------------
# 7. Resize listener for re-clamping pos into viewport
# ---------------------------------------------------------------------------


def test_resize_listener_present():
    """addEventListener('resize', ...) must be present to re-clamp on window resize."""
    assert "addEventListener('resize'" in _SOURCE or 'addEventListener("resize"' in _SOURCE, (
        "resize event listener not found — pos is not re-clamped on window resize"
    )


# ---------------------------------------------------------------------------
# 8. Pointer capture for smooth drag (setPointerCapture)
# ---------------------------------------------------------------------------


def test_pointer_capture_present():
    """setPointerCapture must be called on drag start for reliable pointer tracking."""
    assert "setPointerCapture" in _SOURCE, (
        "setPointerCapture not found — pointer capture not set, drag will be unreliable"
    )


# ---------------------------------------------------------------------------
# 9. Keyboard accessibility: Enter/Space must still open the assistant
# ---------------------------------------------------------------------------


def test_keyboard_open_preserved():
    """Keyboard activation (click with detail === 0) must still open the panel.

    Removing the plain onClick in favour of pointer events breaks Enter/Space on
    the focused icon — keyboard clicks fire `click` with detail === 0, never
    pointer events. The component must handle that path explicitly.
    """
    assert "e.detail === 0" in _SOURCE, (
        "No keyboard-click handler (e.detail === 0) found — Enter/Space on the "
        "focused icon can no longer open the assistant (regression)"
    )


# ---------------------------------------------------------------------------
# 10. Hidden panel must leave the tab order (visibility, not just opacity)
# ---------------------------------------------------------------------------


def test_hidden_panel_invisible_class():
    """Closed panel must use `invisible` (visibility: hidden) so its textarea and
    buttons are removed from the tab order — opacity-0 alone keeps them focusable."""
    assert "invisible" in _SOURCE, "`invisible` class not found — hidden panel children remain Tab-reachable"


def test_hidden_panel_aria_hidden():
    """Closed panel must set aria-hidden so screen readers skip the hidden chat."""
    assert "aria-hidden={!open}" in _SOURCE, "aria-hidden={!open} not found on the always-mounted panel"
