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
