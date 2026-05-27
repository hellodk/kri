import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
