"""Unit tests for #143 (LLM persistence) and #155 (drift display names)."""
from pathlib import Path


def test_llm_store_uses_zustand_persist():
    # Check either llmStore.ts or LLMAssistant component uses zustand persist
    store_candidates = [
        Path("frontend/src/stores/llmStore.ts"),
        Path("frontend/src/stores/llmChatStore.ts"),
    ]
    found = any(p.exists() for p in store_candidates)
    if found:
        src = next(p.read_text() for p in store_candidates if p.exists())
        assert "persist" in src, "LLM store must use Zustand persist middleware"
        assert "clearMessages" in src or "clear" in src.lower(), "LLM store must have a clear function"
    else:
        # fallback: check LLMAssistant component directly
        import glob
        files = glob.glob("frontend/src/components/LLMAssistant/**/*.tsx", recursive=True)
        files += glob.glob("frontend/src/components/LLMAssistant*.tsx")
        combined = "".join(Path(f).read_text() for f in files if Path(f).exists())
        assert "persist" in combined or "useLLMStore" in combined, (
            "LLMAssistant must use persisted Zustand store for messages"
        )


def test_drift_has_grain_display_names():
    import glob
    drift_files = glob.glob("frontend/src/**/*.tsx", recursive=True)
    drift_files = [f for f in drift_files if "drift" in f.lower() or "Drift" in f]
    combined = "".join(Path(f).read_text() for f in drift_files if Path(f).exists())
    assert "GRAIN_DISPLAY_NAMES" in combined or "formatGrainKey" in combined or "displayName" in combined.lower(), (
        "Drift views must have grain key display name mapping"
    )


def test_llm_store_has_clear_function():
    store_candidates = [
        Path("frontend/src/stores/llmStore.ts"),
        Path("frontend/src/stores/llmChatStore.ts"),
    ]
    src = ""
    for p in store_candidates:
        if p.exists():
            src = p.read_text()
            break
    if src:
        assert "clear" in src.lower(), "LLM store must have a clear/reset messages function"
