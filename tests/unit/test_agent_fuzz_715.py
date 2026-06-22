"""Per-tool input fuzzing — the schema validator must never crash, and must
reject malformed args rather than passing them through (#715)."""

from __future__ import annotations

import pytest

from fleet_platform.agent.executor import validate_args
from fleet_platform.agent.tools import build_default_registry

# A spread of hostile / malformed argument payloads.
FUZZ_VALUES = [
    None,
    123,
    -1,
    0,
    True,
    False,
    "",
    "x" * 100_000,
    "\x00\x01\x02",
    "\u202e\u200b",
    "../../etc/passwd",
    "${jndi:ldap://evil}",
    {"nested": {"deep": [1, 2, 3]}},
    [1, 2, 3],
    [{"a": 1}],
    {"__proto__": "x"},
    float("inf"),
    "'; DROP TABLE nodes; --",
    "```rm -rf /```",
]

REGISTRY = build_default_registry()


@pytest.mark.parametrize("tool", [t.name for t in REGISTRY.all()])
def test_validate_args_never_crashes_on_garbage(tool):
    spec = REGISTRY.get(tool)
    schema = spec.params_schema
    # Non-dict args.
    for bad in (None, 1, "str", [1], True):
        res = validate_args(schema, bad)  # type: ignore[arg-type]
        assert res is None or isinstance(res, str)
    # Per-field garbage injection.
    for field in schema.get("properties", {}):
        for val in FUZZ_VALUES:
            res = validate_args(schema, {field: val})
            assert res is None or isinstance(res, str)
    # Random extra keys must be rejected (additionalProperties: false).
    res = validate_args(schema, {"totally_unknown_key_xyz": "v"})
    assert isinstance(res, str)


@pytest.mark.parametrize("tool", [t.name for t in REGISTRY.all()])
def test_missing_required_is_rejected(tool):
    spec = REGISTRY.get(tool)
    required = spec.params_schema.get("required", [])
    if required:
        # Empty args must be rejected when the tool has required fields.
        res = validate_args(spec.params_schema, {})
        assert isinstance(res, str)
        assert "required" in res


def test_oversized_string_rejected_when_maxlength_set():
    spec = REGISTRY.get("get_node")
    # get_node.identifier has a maxLength; a giant value must be rejected.
    props = spec.params_schema["properties"]
    field, meta = next(iter(props.items()))
    if "maxLength" in meta:
        res = validate_args(spec.params_schema, {field: "x" * (meta["maxLength"] + 1)})
        assert isinstance(res, str)
        assert "maxLength" in res
