"""Unit tests for macOS configuration profile service functions."""
from __future__ import annotations


def test_extract_profile_uuid_valid_xml():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    xml = """<?xml version="1.0"?>
<plist version="1.0"><dict>
<key>PayloadUUID</key><string>12345678-ABCD-1234-ABCD-123456789012</string>
</dict></plist>"""
    assert extract_profile_uuid(xml) == "12345678-ABCD-1234-ABCD-123456789012"


def test_extract_profile_uuid_missing_returns_none():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    assert extract_profile_uuid("<plist><dict></dict></plist>") is None


def test_extract_profile_uuid_invalid_xml_returns_none():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    assert extract_profile_uuid("not xml at all") is None


def test_extract_profile_uuid_nested_dict():
    """PayloadUUID nested inside an array/dict should still be found."""
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    xml = """<?xml version="1.0"?>
<plist version="1.0">
  <dict>
    <key>PayloadContent</key>
    <array>
      <dict>
        <key>PayloadUUID</key>
        <string>NESTED-1234-ABCD-1234-NESTED123456</string>
      </dict>
    </array>
    <key>PayloadUUID</key>
    <string>TOP-LEVEL-ABCD-1234-ABCD-TOPLEVEL0001</string>
  </dict>
</plist>"""
    # Should return the first match (top-level dict)
    result = extract_profile_uuid(xml)
    assert result is not None
    assert len(result) > 0


def test_extract_profile_uuid_empty_string_returns_none():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    assert extract_profile_uuid("") is None


def test_extract_profile_uuid_only_key_no_string():
    """PayloadUUID key exists but no following <string> sibling."""
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    xml = """<plist><dict>
<key>PayloadUUID</key>
<integer>12345</integer>
</dict></plist>"""
    assert extract_profile_uuid(xml) is None
