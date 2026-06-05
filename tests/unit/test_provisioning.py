"""Unit tests for provisioning route helpers."""


def test_safe_filename_strips_crlf():
    from fleet_platform.api.routes.provisioning import _safe_filename

    assert "\r" not in _safe_filename("evil\r\nHeader: injected")
    assert "\n" not in _safe_filename("evil\r\nHeader: injected")
    assert _safe_filename("normal_file.mobileprovision") == "normal_file.mobileprovision"


def test_safe_filename_strips_quotes():
    from fleet_platform.api.routes.provisioning import _safe_filename

    assert '"' not in _safe_filename('file"name.mp')
    assert "\\" not in _safe_filename("file\\name.mp")


def test_safe_filename_strips_null():
    from fleet_platform.api.routes.provisioning import _safe_filename

    assert "\x00" not in _safe_filename("file\x00.mp")


def test_safe_filename_strips_path_traversal():
    from fleet_platform.api.routes.provisioning import _safe_filename

    assert "/" not in _safe_filename("../../etc/passwd")
    assert "/" not in _safe_filename("a/b/c.mp")
    assert _safe_filename("../../etc/passwd") == ".._.._etc_passwd"
