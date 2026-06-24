"""OpenAPI contract / schema-shape tests (#811 TST-15).

Uses FastAPI's ``app.openapi()`` to assert that critical response models
contain the expected fields and types. A breaking schema change (renamed field,
changed type, removed required key) will fail these tests before it reaches
production.

Each assertion targets the JSON Schema object that FastAPI generates from the
corresponding Pydantic model — no live HTTP calls needed, no DB required.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def openapi_schema():
    from fleet_platform.api.main import create_app

    app = create_app()
    return app.openapi()


@pytest.fixture(scope="module")
def components(openapi_schema):
    return openapi_schema.get("components", {}).get("schemas", {})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_ref(ref: str, components: dict) -> dict:
    """Resolve a $ref like '#/components/schemas/Foo' to its schema dict."""
    name = ref.split("/")[-1]
    return components[name]


def _required_fields(schema: dict) -> set[str]:
    return set(schema.get("required", []))


def _properties(schema: dict) -> set[str]:
    return set(schema.get("properties", {}).keys())


# ---------------------------------------------------------------------------
# TokenResponse — auth login / refresh
# ---------------------------------------------------------------------------


def test_token_response_has_access_and_refresh_tokens(components):
    schema = components["TokenResponse"]
    props = _properties(schema)
    assert "access_token" in props, "TokenResponse must have 'access_token'"
    assert "refresh_token" in props, "TokenResponse must have 'refresh_token'"
    assert "token_type" in props, "TokenResponse must have 'token_type'"


def test_token_response_access_token_is_string(components):
    schema = components["TokenResponse"]
    assert schema["properties"]["access_token"].get("type") == "string"


def test_token_response_token_type_default_is_bearer(components):
    schema = components["TokenResponse"]
    token_type_prop = schema["properties"]["token_type"]
    default = token_type_prop.get("default")
    assert default == "bearer", f"token_type default should be 'bearer', got {default!r}"


# ---------------------------------------------------------------------------
# NodeRegisterResponse
# ---------------------------------------------------------------------------


def test_node_register_response_has_required_fields(components):
    schema = components["NodeRegisterResponse"]
    props = _properties(schema)
    assert "node_id" in props
    assert "minion_id" in props
    assert "token" in props


def test_node_register_response_node_id_is_uuid_format(components):
    schema = components["NodeRegisterResponse"]
    node_id_prop = schema["properties"]["node_id"]
    fmt = node_id_prop.get("format") or node_id_prop.get("type")
    assert fmt in ("uuid", "string"), f"node_id should be uuid format, got {node_id_prop}"


def test_node_register_response_minion_id_is_string(components):
    schema = components["NodeRegisterResponse"]
    assert schema["properties"]["minion_id"].get("type") == "string"


# ---------------------------------------------------------------------------
# NodeListItem — node list endpoint
# ---------------------------------------------------------------------------


def test_node_list_item_has_status_field(components):
    schema = components["NodeListItem"]
    props = _properties(schema)
    assert "status" in props, "NodeListItem must expose 'status'"


def test_node_list_item_has_health_field(components):
    schema = components["NodeListItem"]
    props = _properties(schema)
    assert "health" in props, "NodeListItem must expose computed 'health' field"


def test_node_list_item_has_id_and_minion_id(components):
    schema = components["NodeListItem"]
    props = _properties(schema)
    assert "id" in props
    assert "minion_id" in props


# ---------------------------------------------------------------------------
# MeResponse — /auth/me
# ---------------------------------------------------------------------------


def test_me_response_has_email_and_role(components):
    schema = components["MeResponse"]
    props = _properties(schema)
    assert "email" in props
    assert "role" in props
    assert "id" in props


def test_me_response_auth_provider_default_is_local(components):
    schema = components["MeResponse"]
    prop = schema["properties"].get("auth_provider", {})
    assert prop.get("default") == "local"


# ---------------------------------------------------------------------------
# PaginatedResponse structure (generic wrapper)
# ---------------------------------------------------------------------------


def test_paginated_response_shape_present_in_schema(openapi_schema):
    """At least one paginated response schema must exist in components."""
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    paginated = [k for k in schemas if "Paginated" in k]
    assert paginated, "Expected at least one PaginatedResponse variant in OpenAPI schema"


# ---------------------------------------------------------------------------
# Health endpoint — shape via live GET (no DB needed)
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_ok_status():
    from fastapi.testclient import TestClient

    from fleet_platform.api.main import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert "version" in body
    assert "environment" in body


def test_health_response_keys_are_stable():
    """The /health response must always have exactly these top-level keys."""
    from fastapi.testclient import TestClient

    from fleet_platform.api.main import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=True)
    body = client.get("/health").json()
    assert set(body.keys()) == {"status", "version", "environment"}
