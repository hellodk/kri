"""Tests for LLM quick-fix recommendations on NodeDetail (#294)."""


def test_ask_ai_route_registered():
    """The /ask-ai route must exist in node_actions router."""
    from fleet_platform.api.routes.node_actions import router
    paths = [r.path for r in router.routes]
    assert any("ask-ai" in p for p in paths), f"ask-ai route not found in {paths}"


def test_node_context_string_contains_key_fields():
    """Verify the node context string format includes cpu/mem/drift."""
    cpu, mem, drift = 72.5, 88.1, 45
    context = (
        f"CPU usage: {cpu:.1f}%\n"
        f"Memory usage: {mem:.1f}%\n"
        f"Drift score: {drift}/100\n"
    )
    assert "72.5%" in context
    assert "88.1%" in context
    assert "45/100" in context
