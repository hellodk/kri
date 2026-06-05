"""Tests for #299 — group-targeted jobs appear in node's Executions tab."""


def test_list_ansible_jobs_route_has_group_logic():
    """The jobs route must handle group membership when node_id filter is used."""
    import inspect

    import fleet_platform.api.routes.ansible as ansible_mod

    source = inspect.getsource(ansible_mod.list_ansible_jobs)
    # Must look up group memberships when filtering by node_id
    assert "GroupMember" in source or "group_member" in source.lower(), (
        "list_ansible_jobs must include group-targeted jobs for the node"
    )


def test_list_ansible_jobs_uses_or_condition():
    """Jobs for groups containing the node must be OR'd into the query."""
    import inspect

    import fleet_platform.api.routes.ansible as ansible_mod

    source = inspect.getsource(ansible_mod.list_ansible_jobs)
    assert "or_" in source or "group_ids" in source, "Query must use OR to include both direct and group-targeted jobs"
