"""Tests for IST timestamp utility (#367)."""


def test_ist_utils_file_exists():
    from pathlib import Path

    assert Path("frontend/src/utils/time.ts").exists()


def test_formatist_is_exported():
    content = open("frontend/src/utils/time.ts").read()
    assert "export function formatIST" in content
    # #796/#877: timestamps now render in the viewer's local timezone via
    # getTimezone() (with timeZoneName for the suffix) rather than a hardcoded
    # Asia/Kolkata zone.
    assert "getTimezone()" in content
    assert "timeZoneName" in content


def test_node_detail_uses_formatist():
    # #787: date formatting moved into the pages/nodeDetail/ tab components.
    from pathlib import Path

    _pages = Path("frontend/src/pages")
    content = "\n".join(
        [
            (_pages / "NodeDetail.tsx").read_text(),
            *(p.read_text() for p in sorted((_pages / "nodeDetail").glob("*.tsx"))),
        ]
    )
    assert "formatIST" in content or "formatISTDate" in content
    # Should NOT have bare format(new Date()) for absolute dates anymore
    import re

    bare_format_calls = re.findall(r"format\(new Date\([^)]+\),\s*['\"]PP", content)
    assert len(bare_format_calls) == 0, f"NodeDetail still has non-IST absolute date formats: {bare_format_calls}"


def test_ist_suffix_in_utility():
    content = open("frontend/src/utils/time.ts").read()
    # The timezone suffix is now derived dynamically from the viewer's locale
    # (timeZoneName: 'short') instead of a hardcoded ' IST' string (#796/#877).
    assert "timeZoneName" in content
