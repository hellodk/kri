# tests/unit/test_llm_data_minimization_b25.py
"""Unit tests for LLM data minimization — issue #169.

Verifies that _redact_sensitive_data correctly redacts IPv4 addresses when
include_ips=False and leaves them intact when include_ips=True.
"""


from fleet_platform.services.llm_svc import _redact_sensitive_data


def test_redact_ips_when_disabled():
    result = _redact_sensitive_data("Node IP: 192.168.1.5, host: macmini-01", include_ips=False)
    assert "192.168.1.5" not in result
    assert "[REDACTED_IP]" in result
    assert "macmini-01" in result  # hostnames not affected


def test_keep_ips_when_enabled():
    result = _redact_sensitive_data("Node IP: 192.168.1.5", include_ips=True)
    assert "192.168.1.5" in result


def test_multiple_ips_redacted():
    result = _redact_sensitive_data("IPs: 10.0.0.1 and 172.16.0.5", include_ips=False)
    assert "10.0.0.1" not in result
    assert "172.16.0.5" not in result
    assert result.count("[REDACTED_IP]") == 2


def test_no_ips_returns_context_unchanged():
    text = "Salt master: not configured\nGroups: build, ci"
    result = _redact_sensitive_data(text, include_ips=False)
    assert result == text


def test_redact_does_not_affect_non_ip_numbers():
    text = "Port: 8080, version: 3.10.4"
    result = _redact_sensitive_data(text, include_ips=False)
    # 3.10.4 is not a valid IPv4 (only 3 octets) — should not be replaced
    assert "3.10.4" in result
    # 8080 is not an IPv4 — should not be replaced
    assert "8080" in result


def test_redact_ip_at_end_of_string():
    result = _redact_sensitive_data("Master: 10.0.0.254", include_ips=False)
    assert "10.0.0.254" not in result
    assert "[REDACTED_IP]" in result


def test_redact_preserves_surrounding_text():
    result = _redact_sensitive_data("Connect to 192.168.0.1 for access", include_ips=False)
    assert result == "Connect to [REDACTED_IP] for access"


def test_empty_context():
    assert _redact_sensitive_data("", include_ips=False) == ""
    assert _redact_sensitive_data("", include_ips=True) == ""


def test_redact_constant_exported_from_platform_settings():
    """Verify the LLM_INCLUDE_NODE_IPS constant is accessible from platform_settings_svc."""
    from fleet_platform.services.platform_settings_svc import LLM_INCLUDE_NODE_IPS

    assert LLM_INCLUDE_NODE_IPS == "llm_include_node_ips"
