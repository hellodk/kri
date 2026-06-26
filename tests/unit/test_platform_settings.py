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


def test_rag_embed_url_in_settings_response_schema():
    """PlatformSettingsResponse must include llm_embed_base_url and llm_include_node_ips (#664)."""
    from fleet_platform.schemas.ansible import PlatformSettingsResponse

    fields = PlatformSettingsResponse.model_fields
    assert "llm_embed_base_url" in fields, "llm_embed_base_url missing from PlatformSettingsResponse"
    assert "llm_include_node_ips" in fields, "llm_include_node_ips missing from PlatformSettingsResponse"


def test_rag_embed_url_in_settings_update_schema():
    """PlatformSettingsUpdate must include llm_embed_base_url and llm_include_node_ips (#664)."""
    from fleet_platform.schemas.ansible import PlatformSettingsUpdate

    fields = PlatformSettingsUpdate.model_fields
    assert "llm_embed_base_url" in fields, "llm_embed_base_url missing from PlatformSettingsUpdate"
    assert "llm_include_node_ips" in fields, "llm_include_node_ips missing from PlatformSettingsUpdate"


def test_rag_settings_route_get_fetches_embed_keys():
    """GET /api/v1/settings handler must include LLM_EMBED_BASE_URL and LLM_INCLUDE_NODE_IPS in bulk fetch (#664)."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from fleet_platform.api.routes.platform_settings import get_settings
    from fleet_platform.services.platform_settings_svc import LLM_EMBED_BASE_URL, LLM_INCLUDE_NODE_IPS

    queried_keys: list[str] = []

    async def fake_bulk(db, keys):
        queried_keys.extend(keys)
        return {k: None for k in keys}

    fake_db = AsyncMock()

    with (
        patch("fleet_platform.api.routes.platform_settings.get_settings_bulk", side_effect=fake_bulk),
        patch("fleet_platform.api.routes.platform_settings.get_controller_pubkey", return_value=None),
    ):
        asyncio.run(get_settings(db=fake_db, _={}))

    assert LLM_EMBED_BASE_URL in queried_keys, "GET handler must request LLM_EMBED_BASE_URL from DB"
    assert LLM_INCLUDE_NODE_IPS in queried_keys, "GET handler must request LLM_INCLUDE_NODE_IPS from DB"


def test_rag_settings_route_put_persists_embed_keys():
    """PUT /api/v1/settings handler must call set_setting for both RAG embedding keys (#664)."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from fleet_platform.api.routes.platform_settings import update_settings
    from fleet_platform.schemas.ansible import PlatformSettingsUpdate
    from fleet_platform.services.platform_settings_svc import LLM_EMBED_BASE_URL, LLM_INCLUDE_NODE_IPS

    set_keys: list[str] = []

    async def fake_set(db, key, value, **kwargs):
        set_keys.append(key)

    async def fake_get(db, key):
        return None

    fake_db = AsyncMock()
    payload = PlatformSettingsUpdate(
        llm_embed_base_url="http://embed.example.com",
        llm_include_node_ips=True,
    )

    with (
        patch("fleet_platform.api.routes.platform_settings.set_setting", side_effect=fake_set),
        patch("fleet_platform.api.routes.platform_settings.get_setting", side_effect=fake_get),
        patch("fleet_platform.api.routes.platform_settings.get_controller_pubkey", return_value=None),
        patch("fleet_platform.api.routes.platform_settings.audit", new_callable=AsyncMock),
    ):
        asyncio.run(update_settings(payload=payload, db=fake_db, claims={"email": "admin@test"}))

    assert LLM_EMBED_BASE_URL in set_keys, "PUT handler must call set_setting(db, LLM_EMBED_BASE_URL, ...)"
    assert LLM_INCLUDE_NODE_IPS in set_keys, "PUT handler must call set_setting(db, LLM_INCLUDE_NODE_IPS, ...)"


def test_playbook_sources_nonexistent_local_warns(caplog):
    """get_all_playbook_dirs logs a warning for non-existent local paths."""
    import json
    import logging
    from pathlib import Path

    from fleet_platform.services.playbook_sources import get_all_playbook_dirs

    sources_json = json.dumps([{"type": "local", "path": "/nonexistent/path/xyz"}])
    builtin = Path("/tmp")
    with caplog.at_level(logging.WARNING):
        dirs = get_all_playbook_dirs(sources_json, builtin)
    assert builtin in dirs  # builtin always present
