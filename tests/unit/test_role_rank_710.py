"""#710 Phase A — centralized role-rank helper.

Single source of truth for viewer < operator < admin comparisons, used by the
agent tool executor (#711) and the co-sign threshold (#714).
"""

import pytest

from fleet_platform.core.auth import role_rank, role_satisfies


@pytest.mark.parametrize(
    "role,rank",
    [("viewer", 0), ("operator", 1), ("admin", 2)],
)
def test_known_roles_rank_in_order(role, rank):
    assert role_rank(role) == rank


def test_hierarchy_is_strictly_increasing():
    assert role_rank("viewer") < role_rank("operator") < role_rank("admin")


@pytest.mark.parametrize("bad", [None, "", "root", "superadmin", "Admin", 123])
def test_unknown_roles_rank_negative(bad):
    assert role_rank(bad) == -1


@pytest.mark.parametrize(
    "actual,required,ok",
    [
        ("admin", "viewer", True),
        ("admin", "operator", True),
        ("admin", "admin", True),
        ("operator", "viewer", True),
        ("operator", "operator", True),
        ("operator", "admin", False),
        ("viewer", "viewer", True),
        ("viewer", "operator", False),
        ("viewer", "admin", False),
    ],
)
def test_role_satisfies_matrix(actual, required, ok):
    assert role_satisfies(actual, required) is ok


@pytest.mark.parametrize("bad", [None, "", "root", 123])
def test_unknown_actor_never_satisfies(bad):
    assert role_satisfies(bad, "viewer") is False


@pytest.mark.parametrize("bad", [None, "", "nonsense"])
def test_unknown_requirement_is_never_satisfiable(bad):
    # An unknown requirement must fail closed even for admins.
    assert role_satisfies("admin", bad) is False
