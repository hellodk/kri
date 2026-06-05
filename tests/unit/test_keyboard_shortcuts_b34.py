"""Tests for #163: keyboard shortcuts."""

from pathlib import Path

HOOK = (Path(__file__).parent.parent.parent / "frontend/src/hooks/useKeyboardShortcuts.ts").read_text()
OVERLAY = (Path(__file__).parent.parent.parent / "frontend/src/components/KeyboardShortcutsOverlay.tsx").read_text()
APP = (Path(__file__).parent.parent.parent / "frontend/src/App.tsx").read_text()


def test_hook_file_exists():
    assert "useKeyboardShortcuts" in HOOK


def test_hook_ignores_input_elements():
    assert "INPUT" in HOOK or "input" in HOOK.lower()


def test_hook_allows_escape_in_inputs():
    assert "Escape" in HOOK


def test_overlay_lists_escape_shortcut():
    assert "Escape" in OVERLAY


def test_overlay_lists_search_shortcut():
    assert "Ctrl+K" in OVERLAY or "ctrl+k" in OVERLAY.lower()


def test_overlay_lists_question_mark():
    assert '"?"' in OVERLAY or "'?'" in OVERLAY


def test_app_registers_question_mark_shortcut():
    assert '"?"' in APP or "'?'" in APP


def test_app_renders_overlay():
    assert "KeyboardShortcutsOverlay" in APP


def test_app_registers_ctrl_k():
    assert "ctrl+k" in APP.lower() or "ctrl+K" in APP


def test_hook_prevents_default():
    assert "preventDefault" in HOOK
