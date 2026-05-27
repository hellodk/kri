import os
import tempfile


def test_fernet_encrypt_decrypt_roundtrip():
    from fleet_platform.services.platform_settings_svc import _fernet

    plaintext = "super-secret-password"
    encrypted = _fernet().encrypt(plaintext.encode()).decode()
    decrypted = _fernet().decrypt(encrypted.encode()).decode()
    assert decrypted == plaintext


def test_fernet_key_is_deterministic():
    from fleet_platform.services.platform_settings_svc import _fernet_key

    assert _fernet_key() == _fernet_key()


def test_fernet_key_uses_explicit_key_when_set():
    """_fernet_key returns the FERNET_SECRET_KEY directly when it is configured."""
    from cryptography.fernet import Fernet

    from fleet_platform.services.platform_settings_svc import _fernet_key

    explicit_key = Fernet.generate_key().decode()

    import fleet_platform.services.platform_settings_svc as svc_module

    original = svc_module.settings.fernet_secret_key

    try:
        # Monkeypatch the settings object
        svc_module.settings.__dict__["fernet_secret_key"] = explicit_key
        result = _fernet_key()
        assert result == explicit_key.encode()
    finally:
        svc_module.settings.__dict__["fernet_secret_key"] = original


def test_fernet_key_falls_back_to_jwt_secret():
    """_fernet_key falls back to deriving from jwt_secret when FERNET_SECRET_KEY is unset."""
    import base64
    import hashlib

    import fleet_platform.services.platform_settings_svc as svc_module
    from fleet_platform.services.platform_settings_svc import _fernet_key

    original = svc_module.settings.fernet_secret_key

    try:
        svc_module.settings.__dict__["fernet_secret_key"] = None
        result = _fernet_key()

        # Should be sha256 of jwt_secret, urlsafe base64 encoded
        expected = base64.urlsafe_b64encode(hashlib.sha256(svc_module.settings.jwt_secret.encode()).digest())
        assert result == expected
    finally:
        svc_module.settings.__dict__["fernet_secret_key"] = original


def test_ssh_keypair_creates_files():
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair

    with tempfile.TemporaryDirectory() as tmpdir:
        priv = os.path.join(tmpdir, "id_rsa")
        pub = os.path.join(tmpdir, "id_rsa.pub")
        ensure_controller_keypair(priv_path=priv, pub_path=pub)
        assert os.path.exists(priv)
        assert os.path.exists(pub)
        assert open(pub).read().startswith("ssh-rsa ")


def test_ssh_keypair_idempotent():
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair

    with tempfile.TemporaryDirectory() as tmpdir:
        priv = os.path.join(tmpdir, "id_rsa")
        pub = os.path.join(tmpdir, "id_rsa.pub")
        ensure_controller_keypair(priv_path=priv, pub_path=pub)
        mtime = os.path.getmtime(priv)
        ensure_controller_keypair(priv_path=priv, pub_path=pub)
        assert os.path.getmtime(priv) == mtime
