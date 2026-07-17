"""Tests for playbook chunk splitting (Closes #1028).

Verifies long plays with many tasks are split into size-bounded sub-chunks.
"""

from __future__ import annotations

from fleet_platform.services.embedding_svc import chunk_playbook


class TestPlaybookChunkSplitting:
    """Verify chunk_playbook splits large plays."""

    def test_short_play_single_chunk(self):
        """A play with few tasks stays as one chunk."""
        yaml_content = """
- name: Deploy nginx
  hosts: webservers
  tasks:
    - name: Install nginx
      apt:
        name: nginx
    - name: Start nginx
      service:
        name: nginx
        state: started
"""
        chunks = chunk_playbook("playbooks/deploy.yml", yaml_content)
        assert len(chunks) == 1
        assert "Deploy nginx" in chunks[0]["chunk_text"]

    def test_long_play_produces_multiple_chunks(self):
        """A play with many tasks (>400 tokens) produces multiple chunks."""
        # Create a play with many tasks to exceed 400 tokens
        tasks = []
        for i in range(30):
            name = f"Task {i} with a somewhat longer description to add tokens"
            msg = f"Step {i} of the deployment process"
            tasks.append(f"    - name: {name}\n      debug:\n          msg: '{msg}'")

        yaml_content = "- name: Long deployment\n  hosts: all\n  tasks:\n" + "\n".join(tasks)

        chunks = chunk_playbook("playbooks/long.yml", yaml_content)

        # Should produce multiple chunks for a long play
        assert len(chunks) > 1, f"Expected multiple chunks for long play, got {len(chunks)}"

        # All chunks should have the same source base
        for chunk in chunks:
            assert chunk["source_type"] == "playbook"
            assert chunk["source_id"].startswith("playbooks/long.yml:")

    def test_play_header_preserved_in_sub_chunks(self):
        """Each sub-chunk retains the play header for context."""
        tasks = []
        for i in range(30):
            tasks.append(f"    - name: Task {i}\n      debug:\n          msg: test")

        yaml_content = "- name: Deploy app\n  hosts: webservers\n  tasks:\n" + "\n".join(tasks)

        chunks = chunk_playbook("playbooks/app.yml", yaml_content)

        # All chunks should contain the play name
        for chunk in chunks:
            assert "Deploy app" in chunk["chunk_text"], f"Play header missing in chunk: {chunk['chunk_text'][:100]}"

    def test_empty_tasks_list(self):
        """A play with no tasks produces one chunk."""
        yaml_content = """
- name: Empty play
  hosts: all
  tasks: []
"""
        chunks = chunk_playbook("playbooks/empty.yml", yaml_content)
        assert len(chunks) == 1
        assert "Empty play" in chunks[0]["chunk_text"]

    def test_invalid_yaml_returns_empty(self):
        """Invalid YAML returns empty list."""
        chunks = chunk_playbook("playbooks/bad.yml", "not: valid: yaml: [")
        assert chunks == []
