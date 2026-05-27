import pytest
from fleet_platform.models.user import User


def test_user_model_has_auth_provider_field():
    u = User(email="x@x.com", password_hash="h", role="admin", auth_provider="local")
    assert u.auth_provider == "local"


def test_user_model_auth_provider_defaults_local():
    u = User(email="x@x.com", password_hash="h", role="admin")
    # default is "local"
    assert u.auth_provider == "local"
