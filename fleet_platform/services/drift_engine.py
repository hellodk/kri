# fleet_platform/services/drift_engine.py
"""Pure stateless drift computation. No DB, no Celery — fully unit-testable."""
import re
from dataclasses import dataclass, field

# Scoring weights per violation type
_WEIGHTS = {
    "missing_required_package": 20,
    "extra_forbidden_package": 10,
    "version_mismatch_major": 15,
    "version_mismatch_minor": 5,
    "service_drift": 15,
}


@dataclass
class DriftResult:
    drift_score: int = 0
    missing_packages: list[dict] = field(default_factory=list)
    extra_packages: list[dict] = field(default_factory=list)
    version_mismatches: list[dict] = field(default_factory=list)
    service_drift: list[dict] = field(default_factory=list)
    config_drift: list[dict] = field(default_factory=list)


def compute_drift(grains: dict, baseline: dict) -> DriftResult:
    """Compute drift between actual grains and desired baseline spec.

    Args:
        grains: Salt grain dict from the node (e.g. NodeFact.grains).
        baseline: Desired state dict (e.g. DesiredStateBaseline.state_json).

    Returns:
        DriftResult with score 0–100 and per-category diff lists.
    """
    missing = _check_missing(grains, baseline)
    extra = _check_extra(grains, baseline)
    version_mismatches = _check_versions(grains, baseline)
    services = _check_services(grains, baseline)

    score = (
        len(missing) * _WEIGHTS["missing_required_package"]
        + len(extra) * _WEIGHTS["extra_forbidden_package"]
        + sum(
            _WEIGHTS[f"version_mismatch_{v['severity']}"]
            for v in version_mismatches
        )
        + len(services) * _WEIGHTS["service_drift"]
    )

    return DriftResult(
        drift_score=min(100, score),
        missing_packages=missing,
        extra_packages=extra,
        version_mismatches=version_mismatches,
        service_drift=services,
        config_drift=[],  # requires config file facts — deferred
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _installed(grains: dict) -> dict[str, str]:
    """Return {lowercase_name: version} from grains."""
    pkgs = grains.get("pkgs") or grains.get("brew_pkgs") or {}
    if not isinstance(pkgs, dict):
        return {}
    return {k.lower(): str(v) for k, v in pkgs.items()}


def _check_missing(grains: dict, baseline: dict) -> list[dict]:
    installed = _installed(grains)
    required = baseline.get("packages", {}).get("required", [])
    return [
        {"name": pkg["name"], "required_version": pkg.get("version")}
        for pkg in required
        if pkg["name"].lower() not in installed
    ]


def _check_extra(grains: dict, baseline: dict) -> list[dict]:
    installed = _installed(grains)
    forbidden = baseline.get("packages", {}).get("forbidden", [])
    return [
        {"name": pkg["name"], "installed_version": installed[pkg["name"].lower()]}
        for pkg in forbidden
        if pkg["name"].lower() in installed
    ]


def _parse_version(v: str) -> tuple[int, ...]:
    """Return a comparable version tuple from a version string."""
    digits = re.findall(r"\d+", re.sub(r"^[>=<~^]+", "", v))
    return tuple(int(d) for d in digits[:3]) if digits else (0,)


def _check_versions(grains: dict, baseline: dict) -> list[dict]:
    installed = _installed(grains)
    required = baseline.get("packages", {}).get("required", [])
    mismatches = []
    for pkg in required:
        name = pkg["name"].lower()
        constraint = pkg.get("version")
        if not constraint or name not in installed:
            continue
        actual_v = _parse_version(installed[name])
        required_v = _parse_version(constraint)
        if ">=" in constraint and actual_v < required_v:
            severity = "major" if (actual_v[0] if actual_v else 0) < (required_v[0] if required_v else 0) else "minor"
            mismatches.append({
                "name": pkg["name"],
                "actual": installed[name],
                "required": constraint,
                "severity": severity,
            })
    return mismatches


def _check_services(grains: dict, baseline: dict) -> list[dict]:
    running = set(grains.get("services") or [])
    spec = baseline.get("services", {})
    drift = []
    for svc in spec.get("required_stopped", []):
        if svc in running:
            drift.append({"service": svc, "expected": "stopped", "actual": "running"})
    for svc in spec.get("required_running", []):
        if svc not in running:
            drift.append({"service": svc, "expected": "running", "actual": "stopped"})
    return drift
