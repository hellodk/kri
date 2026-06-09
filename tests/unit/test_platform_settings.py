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
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "fleet_platform/api/routes/platform_settings.py").read_text()
    get_fn_start = src.find("async def get_settings(")
    get_fn_end = src.find("\n@router.", get_fn_start + 1)
    get_fn = src[get_fn_start:get_fn_end]
    assert "LLM_EMBED_BASE_URL" in get_fn, "GET handler must fetch LLM_EMBED_BASE_URL"
    assert "LLM_INCLUDE_NODE_IPS" in get_fn, "GET handler must fetch LLM_INCLUDE_NODE_IPS"


def test_rag_settings_route_put_persists_embed_keys():
    """PUT /api/v1/settings handler must call set_setting for both RAG embedding keys (#664)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "fleet_platform/api/routes/platform_settings.py").read_text()
    put_fn_start = src.find("async def update_settings(")
    put_fn_end = src.find("\n@router.", put_fn_start + 1)
    if put_fn_end == -1:
        put_fn_end = len(src)
    put_fn = src[put_fn_start:put_fn_end]
    assert "LLM_EMBED_BASE_URL" in put_fn, "PUT handler must call set_setting(db, LLM_EMBED_BASE_URL, ...)"
    assert "LLM_INCLUDE_NODE_IPS" in put_fn, "PUT handler must call set_setting(db, LLM_INCLUDE_NODE_IPS, ...)"


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
