import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_extract_role_from_claims_admin():
    from fleet_platform.services.oidc_svc import _extract_role

    claims = {"realm_access": {"roles": ["kri-admin", "offline_access"]}}
    assert _extract_role(claims, prefix="kri-") == "admin"


def test_extract_role_from_claims_operator():
    from fleet_platform.services.oidc_svc import _extract_role

    claims = {"realm_access": {"roles": ["kri-operator"]}}
    assert _extract_role(claims, prefix="kri-") == "operator"


def test_extract_role_from_claims_auditor():
    from fleet_platform.services.oidc_svc import _extract_role

    claims = {"realm_access": {"roles": ["kri-auditor"]}}
    assert _extract_role(claims, prefix="kri-") == "auditor"


def test_extract_role_defaults_to_viewer_when_no_kri_role():
    from fleet_platform.services.oidc_svc import _extract_role

    claims = {"realm_access": {"roles": ["some-other-role"]}}
    assert _extract_role(claims, prefix="kri-") == "viewer"


def test_extract_role_returns_highest_when_multiple():
    from fleet_platform.services.oidc_svc import _extract_role

    # admin beats operator
    claims = {"realm_access": {"roles": ["kri-admin", "kri-operator"]}}
    assert _extract_role(claims, prefix="kri-") == "admin"


def test_build_authorization_url_contains_required_params():
    from fleet_platform.services.oidc_svc import build_authorization_url

    url, state = build_authorization_url(
        authorization_endpoint="https://kc.example.com/realms/kri/protocol/openid-connect/auth",
        client_id="kri-app",
        redirect_uri="https://kri.example.com/api/v1/auth/oidc/callback",
    )
    assert "client_id=kri-app" in url
    assert "response_type=code" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url
    assert len(state) == 32


@pytest.mark.asyncio
async def test_verify_id_token_raises_on_bad_signature():
    """verify_id_token must reject a tampered token even if JWKS key is valid."""
    import jwt as pyjwt
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Generate a real RSA key pair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()

    # Build a valid token signed with the private key
    valid_token = pyjwt.encode(
        {"sub": "user1", "aud": "kri-app", "iss": "https://kc.example.com", "exp": 9999999999},
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-id"},
    )

    # Tamper with the payload (replace middle segment)
    parts = valid_token.split(".")
    tampered_payload = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": "hacker", "aud": "kri-app", "iss": "https://kc.example.com", "exp": 9999999999}).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

    # Build a JWKS response with the public key
    pub_jwk = pyjwt.algorithms.RSAAlgorithm.to_jwk(public_key)
    import json as _json

    jwks_dict = {"keys": [{**_json.loads(pub_jwk), "kid": "test-key-id"}]}

    # Mock httpx to return our JWKS
    mock_response = MagicMock()
    mock_response.json.return_value = jwks_dict
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    from fleet_platform.services.oidc_svc import verify_id_token

    with patch("fleet_platform.services.oidc_svc.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):  # pyjwt.InvalidSignatureError or similar
            await verify_id_token(
                id_token=tampered_token,
                discovery={"jwks_uri": "https://kc.example.com/jwks"},
                client_id="kri-app",
            )


@pytest.mark.asyncio
async def test_verify_id_token_succeeds_with_valid_token():
    """verify_id_token returns claims for a properly-signed token."""
    import json as _json

    import jwt as pyjwt
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()

    valid_token = pyjwt.encode(
        {"sub": "user1", "aud": "kri-app", "iss": "https://kc.example.com", "exp": 9999999999},
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-id"},
    )

    pub_jwk = pyjwt.algorithms.RSAAlgorithm.to_jwk(public_key)
    jwks_dict = {"keys": [{**_json.loads(pub_jwk), "kid": "test-key-id"}]}

    mock_response = MagicMock()
    mock_response.json.return_value = jwks_dict
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    from fleet_platform.services.oidc_svc import verify_id_token

    with patch("fleet_platform.services.oidc_svc.httpx.AsyncClient", return_value=mock_client):
        claims = await verify_id_token(
            id_token=valid_token,
            discovery={"jwks_uri": "https://kc.example.com/jwks"},
            client_id="kri-app",
        )

    assert claims["sub"] == "user1"
