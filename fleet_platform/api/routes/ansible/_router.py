# fleet_platform/api/routes/ansible/_router.py
"""Shared router + module-level constants for the ansible route package."""

from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/ansible")

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent.parent.parent / "playbooks"

# Playbooks that must only run via the dedicated bootstrap endpoint — not the generic run API
_BOOTSTRAP_ONLY_PLAYBOOKS: frozenset[str] = frozenset({"bootstrap_node.yml"})
