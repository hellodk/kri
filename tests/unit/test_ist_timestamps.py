"""Tests for IST timestamp utility (#367)."""


def test_ist_utils_file_exists():
    from pathlib import Path

    assert Path("frontend/src/utils/time.ts").exists()


def test_formatist_is_exported():
    content = open("frontend/src/utils/time.ts").read()
    assert "export function formatIST" in content
    assert "Asia/Kolkata" in content
    assert "IST" in content


def test_node_detail_uses_formatist():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "formatIST" in content or "formatISTDate" in content
    # Should NOT have bare format(new Date()) for absolute dates anymore
    import re

    bare_format_calls = re.findall(r"format\(new Date\([^)]+\),\s*['\"]PP", content)
    assert len(bare_format_calls) == 0, f"NodeDetail still has non-IST absolute date formats: {bare_format_calls}"


def test_ist_suffix_in_utility():
    content = open("frontend/src/utils/time.ts").read()
    assert "+ ' IST'" in content or "IST'" in content
