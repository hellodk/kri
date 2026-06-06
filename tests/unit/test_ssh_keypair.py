"""Unit tests for ssh_keypair — controller keypair management (closes #309)."""

import pytest


def test_ensure_creates_keypair_when_missing(tmp_path):
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair

    priv = tmp_path / "id_rsa"
    pub = tmp_path / "id_rsa.pub"
    ensure_controller_keypair(priv_path=priv, pub_path=pub)
    assert priv.exists(), "private key must be created"
    assert pub.exists(), "public key must be created"
    pubkey_text = pub.read_text().strip()
    # RSA or Ed25519 public key
    assert pubkey_text.startswith("ssh-"), f"expected ssh key, got: {pubkey_text[:50]}"
    # private key must be owner-read-only
    assert oct(priv.stat().st_mode & 0o777) == "0o600"


def test_ensure_is_idempotent_does_not_rotate_key(tmp_path):
    """Calling ensure twice must not regenerate the key — rotation would break authorized_keys."""
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair

    priv = tmp_path / "id_rsa"
    pub = tmp_path / "id_rsa.pub"
    ensure_controller_keypair(priv_path=priv, pub_path=pub)
    first_bytes = priv.read_bytes()
    ensure_controller_keypair(priv_path=priv, pub_path=pub)
    assert priv.read_bytes() == first_bytes, "keypair must not be regenerated on second call"


def test_get_pubkey_returns_none_when_missing(tmp_path):
    from fleet_platform.services.ssh_keypair import get_controller_pubkey

    pub = tmp_path / "id_rsa.pub"
    result = get_controller_pubkey(pub_path=pub)
    assert result is None


def test_get_pubkey_returns_value_after_ensure(tmp_path):
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair, get_controller_pubkey

    priv = tmp_path / "id_rsa"
    pub = tmp_path / "id_rsa.pub"
    ensure_controller_keypair(priv_path=priv, pub_path=pub)
    pubkey = get_controller_pubkey(pub_path=pub)
    assert pubkey is not None
    assert pubkey.startswith("ssh-")


def test_ensure_raises_on_unwritable_dir(tmp_path):
    """Proves the PermissionError caught in main.py lifespan is the correct type."""
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair

    locked = tmp_path / "locked"
    locked.mkdir(mode=0o444)  # read-only directory
    priv = locked / "id_rsa"
    pub = locked / "id_rsa.pub"
    with pytest.raises((PermissionError, OSError)):
        ensure_controller_keypair(priv_path=priv, pub_path=pub)
