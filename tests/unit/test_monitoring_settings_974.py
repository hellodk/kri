"""Monitoring settings — Prometheus base URL + OTLP endpoint/protocol/headers (#974)."""


def test_monitoring_keys_in_settings_update_schema():
    """PlatformSettingsUpdate must include prometheus_url, otlp_endpoint, otlp_protocol, otlp_headers (#974)."""
    from fleet_platform.schemas.ansible import PlatformSettingsUpdate

    fields = PlatformSettingsUpdate.model_fields
    for name in ("prometheus_url", "otlp_endpoint", "otlp_protocol", "otlp_headers"):
        assert name in fields, f"{name} missing from PlatformSettingsUpdate"


def test_monitoring_keys_in_settings_response_schema():
    """PlatformSettingsResponse must include prometheus_url, otlp_endpoint, otlp_protocol, otlp_headers (#974)."""
    from fleet_platform.schemas.ansible import PlatformSettingsResponse

    fields = PlatformSettingsResponse.model_fields
    for name in ("prometheus_url", "otlp_endpoint", "otlp_protocol", "otlp_headers"):
        assert name in fields, f"{name} missing from PlatformSettingsResponse"


def test_monitoring_setting_key_literals_match_ansible_tasks():
    """Setting key literals must match what ansible_tasks.py reads via get_setting_sync (#974)."""
    from fleet_platform.services.platform_settings_svc import (
        OTLP_ENDPOINT,
        OTLP_HEADERS,
        OTLP_PROTOCOL,
        PROMETHEUS_URL,
    )

    assert PROMETHEUS_URL == "prometheus_url"
    assert OTLP_ENDPOINT == "otlp_endpoint"
    assert OTLP_PROTOCOL == "otlp_protocol"
    assert OTLP_HEADERS == "otlp_headers"


def test_monitoring_settings_route_get_fetches_keys():
    """GET /api/v1/settings handler must include the 4 monitoring keys in the bulk fetch (#974)."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from fleet_platform.api.routes.platform_settings import get_settings
    from fleet_platform.services.platform_settings_svc import (
        OTLP_ENDPOINT,
        OTLP_HEADERS,
        OTLP_PROTOCOL,
        PROMETHEUS_URL,
    )

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

    assert PROMETHEUS_URL in queried_keys, "GET handler must request PROMETHEUS_URL from DB"
    assert OTLP_ENDPOINT in queried_keys, "GET handler must request OTLP_ENDPOINT from DB"
    assert OTLP_PROTOCOL in queried_keys, "GET handler must request OTLP_PROTOCOL from DB"
    assert OTLP_HEADERS in queried_keys, "GET handler must request OTLP_HEADERS from DB"


def test_monitoring_settings_route_get_returns_values():
    """GET /api/v1/settings response must surface the stored monitoring values (#974)."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from fleet_platform.api.routes.platform_settings import get_settings
    from fleet_platform.services.platform_settings_svc import (
        OTLP_ENDPOINT,
        OTLP_HEADERS,
        OTLP_PROTOCOL,
        PROMETHEUS_URL,
    )

    stored = {
        PROMETHEUS_URL: "http://prometheus-operated.monitoring.svc:9090",
        OTLP_ENDPOINT: "http://gateway.monitoring.svc:30318",
        OTLP_PROTOCOL: "grpc",
        OTLP_HEADERS: "authorization=Bearer xyz",
    }

    async def fake_bulk(db, keys):
        return {k: stored.get(k) for k in keys}

    fake_db = AsyncMock()

    with (
        patch("fleet_platform.api.routes.platform_settings.get_settings_bulk", side_effect=fake_bulk),
        patch("fleet_platform.api.routes.platform_settings.get_controller_pubkey", return_value=None),
    ):
        result = asyncio.run(get_settings(db=fake_db, _={}))

    assert result.prometheus_url == stored[PROMETHEUS_URL]
    assert result.otlp_endpoint == stored[OTLP_ENDPOINT]
    assert result.otlp_protocol == stored[OTLP_PROTOCOL]
    assert result.otlp_headers == stored[OTLP_HEADERS]


def test_monitoring_settings_route_put_persists_keys():
    """PUT /api/v1/settings handler must call set_setting for all 4 monitoring keys (#974)."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from fleet_platform.api.routes.platform_settings import update_settings
    from fleet_platform.schemas.ansible import PlatformSettingsUpdate
    from fleet_platform.services.platform_settings_svc import (
        OTLP_ENDPOINT,
        OTLP_HEADERS,
        OTLP_PROTOCOL,
        PROMETHEUS_URL,
    )

    set_calls: dict[str, str] = {}

    async def fake_set(db, key, value, **kwargs):
        set_calls[key] = value

    async def fake_get(db, key):
        return None

    fake_db = AsyncMock()
    payload = PlatformSettingsUpdate(
        prometheus_url="http://prometheus-operated.monitoring.svc:9090",
        otlp_endpoint="http://gateway.monitoring.svc:30318",
        otlp_protocol="http",
        otlp_headers="authorization=Bearer xyz",
    )

    with (
        patch("fleet_platform.api.routes.platform_settings.set_setting", side_effect=fake_set),
        patch("fleet_platform.api.routes.platform_settings.get_setting", side_effect=fake_get),
        patch("fleet_platform.api.routes.platform_settings.get_controller_pubkey", return_value=None),
        patch("fleet_platform.api.routes.platform_settings.audit", new_callable=AsyncMock),
    ):
        asyncio.run(update_settings(payload=payload, db=fake_db, claims={"email": "admin@test"}))

    assert set_calls[PROMETHEUS_URL] == "http://prometheus-operated.monitoring.svc:9090"
    assert set_calls[OTLP_ENDPOINT] == "http://gateway.monitoring.svc:30318"
    assert set_calls[OTLP_PROTOCOL] == "http"
    assert set_calls[OTLP_HEADERS] == "authorization=Bearer xyz"
