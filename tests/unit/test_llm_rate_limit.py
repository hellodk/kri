"""Test that LLM endpoints have SlowAPI rate limit decorators applied."""

import inspect


def test_llm_submit_query_has_rate_limit():
    """Verify that submit_query has @limiter.limit decorator."""
    from fleet_platform.api.routes import llm

    # Check that the route imports limiter
    assert hasattr(llm, "limiter"), "llm module must import limiter from fleet_platform.api.limiter"

    # Check that submit_query function exists
    assert hasattr(llm, "submit_query"), "submit_query function must exist"

    # Get the function
    func = llm.submit_query
    # Check signature includes request: Request as first param
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    assert params[0] == "request", f"First param must be 'request', got {params[0]}"

    # Check that request has Request type annotation
    request_param = sig.parameters["request"]
    from fastapi import Request

    assert request_param.annotation == Request, "request param must be annotated as Request"


def test_node_actions_ask_ai_has_rate_limit():
    """Verify that ask_ai_about_node has @limiter.limit decorator."""
    from fleet_platform.api.routes import node_actions

    # Check that limiter is imported
    assert hasattr(node_actions, "limiter"), "node_actions must import limiter"

    # Check that ask_ai_about_node exists
    assert hasattr(node_actions, "ask_ai_about_node"), "ask_ai_about_node function must exist"

    # Get the function
    func = node_actions.ask_ai_about_node
    # Check signature includes request: Request as first param
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    assert params[0] == "request", f"First param must be 'request', got {params[0]}"

    # Check that request has Request type annotation
    request_param = sig.parameters["request"]
    from fastapi import Request

    assert request_param.annotation == Request, "request param must be annotated as Request"


def test_imports_work():
    """Sanity check: both modules import successfully."""
    from fleet_platform.api.routes import llm, node_actions

    assert llm is not None
    assert node_actions is not None
