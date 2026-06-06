"""Unit tests for the RAG embedding service.

All tests run without a real embedding endpoint — embed_texts is mocked.
"""

import hashlib

# --- Task 1: DB model ---------------------------------------------------------


def test_fleet_embedding_model_importable():
    from fleet_platform.models.fleet_embedding import FleetEmbedding

    assert FleetEmbedding.__tablename__ == "fleet_embeddings"


# --- Task 2: Chunking + RRF + hash --------------------------------------------


def test_chunk_node_returns_one_chunk():
    from fleet_platform.services.embedding_svc import chunk_node

    chunks = chunk_node(
        node_id="uuid-123",
        hostname="mm1",
        ip="192.168.1.10",
        status="online",
        group="build",
        os_info="macOS 14.4",
        last_seen="2m ago",
    )
    assert len(chunks) == 1
    assert "mm1" in chunks[0]["chunk_text"]
    assert chunks[0]["source_type"] == "node"
    assert chunks[0]["source_id"] == "uuid-123"


def test_chunk_playbook_splits_per_play():
    from fleet_platform.services.embedding_svc import chunk_playbook

    yaml_content = """
- name: Bootstrap Mac Mini
  hosts: all
  tasks:
    - name: Install Homebrew
      command: /bin/bash -c "$(curl ...)"
- name: Configure Salt
  hosts: salt_masters
  tasks:
    - name: Enable salt-master
      service: name=salt-master state=started
"""
    chunks = chunk_playbook("playbooks/bootstrap_mac_mini.yml", yaml_content)
    assert len(chunks) == 2
    for c in chunks:
        assert c["source_type"] == "playbook"
        assert "playbooks/bootstrap_mac_mini.yml" in c["source_id"]


def test_chunk_salt_state_splits_per_state_key():
    from fleet_platform.services.embedding_svc import chunk_salt_state

    sls_content = """
install_homebrew:
  cmd.run:
    - name: /bin/bash -c install

enable_salt_minion:
  service.running:
    - name: salt-minion
    - enable: True
"""
    chunks = chunk_salt_state("salt/states/bootstrap.sls", sls_content)
    assert len(chunks) == 2
    assert all(c["source_type"] == "salt_state" for c in chunks)
    assert any("install_homebrew" in c["source_id"] for c in chunks)
    assert any("enable_salt_minion" in c["source_id"] for c in chunks)


def test_rrf_fusion_deduplicates_and_ranks():
    from fleet_platform.services.embedding_svc import reciprocal_rank_fusion

    bm25_ids = ["a", "b", "c", "d"]
    vector_ids = ["b", "a", "e", "f"]
    fused = reciprocal_rank_fusion(bm25_ids, vector_ids, k=60)
    # 'a' and 'b' appear in both lists — must rank highest
    assert fused[0] in ("a", "b")
    assert fused[1] in ("a", "b")
    assert len(set(fused)) == len(fused)  # no duplicates


def test_rrf_fusion_returns_all_unique_ids():
    from fleet_platform.services.embedding_svc import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion(["a", "b"], ["c", "d"])
    assert set(fused) == {"a", "b", "c", "d"}
    assert len(fused) == 4


def test_content_hash_skips_unchanged_chunk():
    from fleet_platform.services.embedding_svc import compute_content_hash

    text = "mm1 online 2m ago build group"
    h = compute_content_hash(text)
    assert len(h) == 64  # sha256 hex
    assert h == hashlib.sha256(text.encode()).hexdigest()


def test_chunk_node_source_id_is_node_id():
    from fleet_platform.services.embedding_svc import chunk_node

    chunks = chunk_node(
        node_id="node-abc",
        hostname="mm2",
        ip="192.168.1.11",
        status="offline",
        group="test",
        os_info="Linux 22.04",
        last_seen="5m ago",
    )
    assert chunks[0]["source_id"] == "node-abc"
    assert chunks[0]["source_type"] == "node"


def test_chunk_playbook_invalid_yaml_returns_empty():
    from fleet_platform.services.embedding_svc import chunk_playbook

    chunks = chunk_playbook("path/to/bad.yml", "{{{{ invalid yaml ::::")
    assert chunks == []


def test_chunk_salt_state_non_dict_returns_empty():
    from fleet_platform.services.embedding_svc import chunk_salt_state

    # A list is valid YAML but not a valid SLS state dict
    chunks = chunk_salt_state("path/to/bad.sls", "- item1\n- item2\n")
    assert chunks == []


# --- Task 7: Golden eval gate — regression prevention -------------------------


def test_grounding_rules_never_truncated():
    """Grounding rules must appear in final context regardless of chunk size."""
    from fleet_platform.services.llm_context import build_static_context

    huge_chunks = "x" * 10000
    ctx = build_static_context(
        node_count=2,
        online_count=1,
        groups=["fleet"],
        salt_master="",
        playbooks_dir="",
        retrieved_chunks=huge_chunks,
    )
    # Grounding rules must be present regardless of context size
    assert "Answer ONLY from" in ctx or "ONLY" in ctx
    assert "never claim" in ctx.lower()


def test_estimate_tokens_never_zero():
    from fleet_platform.services.llm_context import estimate_tokens

    assert estimate_tokens("") >= 1
    assert estimate_tokens("hello world") == max(1, len("hello world") // 4)


def test_intent_classifier_defaults_to_fleet_query():
    from fleet_platform.services.llm_intent import classify_intent

    assert classify_intent("what is mm1 doing") == "fleet_query"
    assert classify_intent("Hi there") == "fleet_query"


def test_intent_classifier_generates_salt_state():
    from fleet_platform.services.llm_intent import classify_intent

    assert classify_intent("write a salt state to install nginx") == "salt_state"
    assert classify_intent("generate an sls file for redis") == "salt_state"


# --- Task 5: Celery task imports -----------------------------------------------


def test_embedding_tasks_importable():
    from fleet_platform.workers import embedding_tasks

    assert hasattr(embedding_tasks, "reindex_nodes")
    assert hasattr(embedding_tasks, "reindex_playbooks")
    assert hasattr(embedding_tasks, "reindex_drift_history")


# --- Chunker coverage additions ------------------------------------------------


def test_chunk_playbook_parses_plays():
    from fleet_platform.services.embedding_svc import chunk_playbook

    yaml_content = "- name: Deploy app\n  hosts: all\n  tasks:\n    - name: Install\n    - name: Start\n"
    chunks = chunk_playbook("deploy.yml", yaml_content)
    assert len(chunks) == 1
    assert chunks[0]["source_type"] == "playbook"
    assert "Deploy app" in chunks[0]["chunk_text"]


def test_chunk_playbook_invalid_yaml_returns_empty_v2():
    from fleet_platform.services.embedding_svc import chunk_playbook

    assert chunk_playbook("bad.yml", ": {invalid:") == []


def test_chunk_playbook_non_list_returns_empty():
    from fleet_platform.services.embedding_svc import chunk_playbook

    assert chunk_playbook("vars.yml", "key: value") == []


def test_chunk_salt_state_parses_state_ids():
    from fleet_platform.services.embedding_svc import chunk_salt_state

    chunks = chunk_salt_state("nginx.sls", "nginx:\n  service.running:\n    - enable: true\n")
    assert len(chunks) == 1
    assert chunks[0]["source_type"] == "salt_state"
    assert "nginx" in chunks[0]["chunk_text"]


def test_chunk_salt_state_invalid_yaml_returns_empty():
    from fleet_platform.services.embedding_svc import chunk_salt_state

    assert chunk_salt_state("bad.sls", ": {broken:") == []


def test_chunk_drift_record_produces_single_chunk():
    from fleet_platform.services.embedding_svc import chunk_drift_record

    chunks = chunk_drift_record(
        drift_id="abc",
        node_hostname="mm1",
        computed_at="2026-06-01",
        drift_score=42,
        missing_packages=["nginx"],
        extra_packages=[],
        version_mismatches=[],
    )
    assert len(chunks) == 1
    assert chunks[0]["source_type"] == "drift"
    assert "mm1" in chunks[0]["chunk_text"]
    assert "missing: nginx" in chunks[0]["chunk_text"]
