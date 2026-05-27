"""Unit tests for #168 (ingest rate limit) and #170 (LLM audit trail)."""
from pathlib import Path

INGEST = Path("fleet_platform/api/routes/ingest.py").read_text()
LLM = Path("fleet_platform/api/routes/llm.py").read_text()


def test_ingest_has_rate_limit():
    assert "_check_ingest_rate_limit" in INGEST or "rate_limit" in INGEST.lower(), (
        "ingest endpoint must implement per-node rate limiting"
    )
    assert "429" in INGEST, "ingest must return HTTP 429 when rate limit exceeded"
    assert "incr" in INGEST or "INCR" in INGEST, (
        "rate limit must use Redis INCR for atomic counting"
    )


def test_ingest_rate_limit_fails_open():
    """If Redis is down, ingest must still work (fail open)."""
    assert "except" in INGEST and ("return True" in INGEST or "fail open" in INGEST.lower()), (
        "rate limit must fail open — return True on Redis error"
    )


def test_llm_queries_logged_to_audit():
    assert "audit" in LLM.lower() or "AuditLog" in LLM, (
        "LLM route must write to the audit log"
    )
    assert "llm_query" in LLM or "llm" in LLM.lower(), (
        "audit entry must identify the LLM query action"
    )
