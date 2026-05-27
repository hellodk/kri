"""Unit tests for #118 (webssh blocklist), #141 (skeleton), #147 (salt JSON)."""
from pathlib import Path


def test_webssh_blocklist_removed():
    src = Path("fleet_platform/api/routes/webssh.py").read_text()
    assert "rm\\s+" not in src, "WebSSH regex blocklist must be removed (issue #118)"
    assert "security note" in src.lower() or "Security note" in src, (
        "webssh.py must have a comment explaining the real security model"
    )


def test_security_page_no_loading_text():
    src = Path("frontend/src/pages/SecurityPage.tsx").read_text()
    # "Loading..." as a bare string return is the bad pattern
    assert 'return "Loading..."' not in src and ">Loading...</" not in src, (
        "SecurityPage must not use 'Loading...' text — use skeleton UI"
    )
    assert "animate-pulse" in src, "SecurityPage must use skeleton animation"


def test_salt_ops_structured_results():
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    assert "JSON.stringify" in src, "SaltOpsPage must format results with JSON.stringify"
    assert "animate-pulse" in src or "skeleton" in src.lower() or "font-mono" in src, (
        "SaltOpsPage must display results in a structured code-style format"
    )
