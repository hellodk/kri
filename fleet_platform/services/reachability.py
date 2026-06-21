"""Reachability helpers — node-vantage minion→master connectivity.

Encapsulates parsing of per-master nc(1) reachability results that are
registered during Ansible bootstrap (playbooks/bootstrap_node.yml).

Each element in ``results`` must be a dict with at least:
  - ``master``: str  — the master address that was probed
  - ``rc``: int      — the nc(1) return code (0 = reachable, non-zero = not)

Issue #536, epic #537.
"""

from __future__ import annotations


def parse_nc_reachability(results: list[dict]) -> dict[str, bool]:
    """Map a list of per-master nc check results to ``{address: reachable}``.

    ``rc == 0`` means nc connected successfully → reachable (True).
    Any non-zero rc means nc timed out or was refused → not reachable (False).

    Args:
        results: List of dicts, each with ``"master"`` (str) and ``"rc"`` (int).

    Returns:
        Dict mapping each master address to its reachability boolean.

    Example::

        >>> parse_nc_reachability([
        ...     {"master": "10.0.0.1", "rc": 0},
        ...     {"master": "10.0.0.2", "rc": 1},
        ... ])
        {'10.0.0.1': True, '10.0.0.2': False}
    """
    return {entry["master"]: entry["rc"] == 0 for entry in results}
