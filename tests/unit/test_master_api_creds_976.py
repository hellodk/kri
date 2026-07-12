"""Issue #976 — provision must ensure salt-api creds exist, else 401.

provision_master previously passed an empty api_password to api_user.yml when the
master record had none (e.g. promoted from a node), creating the krisalt PAM user
with no usable password → every salt-api call 401s → the Minion Keys page and the
pending-count notification badge show empty.

_ensure_master_api_creds(master) must generate + persist a password (and default
api_user='krisalt') when absent, and preserve existing creds otherwise.
"""

from fleet_platform.workers import ansible_tasks


class _FakeMaster:
    def __init__(self, api_password_enc=None, api_user=None):
        self.api_password_enc = api_password_enc
        self.api_user = api_user


def _patch_crypto(monkeypatch):
    # encrypt/decrypt are imported inside the helper from platform_settings_svc.
    import fleet_platform.services.platform_settings_svc as svc

    monkeypatch.setattr(svc, "encrypt_secret", lambda p: f"enc:{p}")
    monkeypatch.setattr(svc, "decrypt_secret", lambda c: c[4:] if c.startswith("enc:") else c)


def test_generates_and_persists_when_absent(monkeypatch):
    _patch_crypto(monkeypatch)
    m = _FakeMaster(api_password_enc=None, api_user=None)
    pw = ansible_tasks._ensure_master_api_creds(m)
    assert pw, "a password must be generated"
    assert m.api_password_enc == f"enc:{pw}", "generated password must be persisted (encrypted)"
    assert m.api_user == "krisalt", "api_user must default to krisalt"


def test_preserves_existing_creds(monkeypatch):
    _patch_crypto(monkeypatch)
    m = _FakeMaster(api_password_enc="enc:existingpw", api_user="customuser")
    pw = ansible_tasks._ensure_master_api_creds(m)
    assert pw == "existingpw", "existing password must be returned, not regenerated"
    assert m.api_password_enc == "enc:existingpw", "existing ciphertext must be untouched"
    assert m.api_user == "customuser", "existing api_user must be preserved"


def test_defaults_user_but_keeps_existing_password(monkeypatch):
    _patch_crypto(monkeypatch)
    m = _FakeMaster(api_password_enc="enc:pw2", api_user=None)
    ansible_tasks._ensure_master_api_creds(m)
    assert m.api_user == "krisalt"
