"""
Unit tests for the kri process telemetry collector — GitHub issue #610.

Tests two concerns:
  1. is_llm_process() pure classifier — no psutil / network required.
  2. Source-contract checks on process_report.sls (text grep assertions).

collect() and post() are NOT called here; they require psutil and network.
"""

import importlib.util
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the collector module without triggering psutil at module level
# ---------------------------------------------------------------------------

_COLLECTOR_PATH = Path(__file__).parent.parent.parent / "salt" / "states" / "base" / "files" / "process_collector.py"

_SLS_PATH = Path(__file__).parent.parent.parent / "salt" / "states" / "base" / "process_report.sls"


def _load_collector():
    """Load process_collector.py by file path without importing psutil."""
    spec = importlib.util.spec_from_file_location("process_collector", _COLLECTOR_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def collector():
    return _load_collector()


@pytest.fixture(scope="module")
def sls_text():
    return _SLS_PATH.read_text()


# ---------------------------------------------------------------------------
# is_llm_process — LLM runtime patterns must return True
# ---------------------------------------------------------------------------


class TestIsLlmProcessPositive:
    """Known LLM/AI runtime names and cmdlines must classify as True."""

    @pytest.mark.parametrize(
        "name,cmdline",
        [
            # exo
            ("exo", ""),
            ("", "python3 /usr/local/bin/exo --some-flag"),
            ("Exo", ""),  # case-insensitive on name
            # mlx
            ("mlx_lm.server", ""),
            ("", "python3 -m mlx_lm.server --model mlx-community/Phi-4"),
            # llama (llama.cpp, llama-server, etc.)
            ("llama-server", ""),
            ("", "/usr/local/bin/llama-server -m models/llama-3.gguf"),
            ("llama_cpp", ""),
            # vllm
            ("vllm", ""),
            ("", "python3 -m vllm.entrypoints.openai.api_server"),
            # ollama
            ("ollama", ""),
            ("", "/usr/local/bin/ollama serve"),
            ("Ollama", ""),  # case-insensitive
            # llm (generic)
            ("llm", ""),
            ("", "python3 llm_server.py"),
            # tinygrad
            ("tinygrad", ""),
            ("", "python3 -m tinygrad.runtime"),
            # model-server patterns
            ("model-server", ""),
            ("model_server", ""),
            ("modelserver", ""),
            # LLM in cmdline only
            ("python3", "python3 /opt/ml/text-generation/server.py"),
            ("python3", "python3 text_generation_server/main.py"),
        ],
    )
    def test_llm_name_or_cmdline_returns_true(self, collector, name, cmdline):
        assert collector.is_llm_process(name, cmdline) is True, f"Expected True for name={name!r} cmdline={cmdline!r}"


class TestIsLlmProcessNegative:
    """Known system process names must always classify as False."""

    @pytest.mark.parametrize(
        "name,cmdline",
        [
            ("sshd", ""),
            ("sshd", "/usr/sbin/sshd -D"),
            ("salt-minion", ""),
            ("salt-minion", "/opt/salt/bin/python3 /opt/salt/bin/salt-minion"),
            ("kernel_task", ""),
            ("launchd", ""),
            ("WindowServer", ""),
            ("systemd", ""),
            ("init", ""),
            ("kthreadd", ""),
            # regular user procs — no LLM pattern
            ("bash", "/bin/bash"),
            ("python3", "python3 /home/user/scripts/migrate.py"),
            ("nginx", "nginx: worker process"),
            ("postgres", "postgres: checkpointer"),
        ],
    )
    def test_system_or_neutral_proc_returns_false(self, collector, name, cmdline):
        assert collector.is_llm_process(name, cmdline) is False, f"Expected False for name={name!r} cmdline={cmdline!r}"


class TestIsLlmProcessEdgeCases:
    """Edge cases: empty strings, None-like inputs."""

    def test_empty_name_and_cmdline(self, collector):
        assert collector.is_llm_process("", "") is False

    def test_whitespace_only(self, collector):
        assert collector.is_llm_process("   ", "   ") is False

    def test_case_insensitive_ollama_upper(self, collector):
        assert collector.is_llm_process("OLLAMA", "") is True

    def test_case_insensitive_vllm_mixed(self, collector):
        assert collector.is_llm_process("VLLM", "") is True

    def test_partial_match_in_long_cmdline(self, collector):
        assert (
            collector.is_llm_process(
                "python3",
                "python3 /opt/my-service/src/exo_runner.py --workers 4",
            )
            is True
        )


# ---------------------------------------------------------------------------
# Source-contract: process_report.sls
# ---------------------------------------------------------------------------


class TestProcessReportSlsContract:
    """Smoke-check that process_report.sls contains the required strings."""

    def test_references_process_stats_endpoint(self, sls_text):
        """The SLS must mention the /process_stats endpoint path."""
        assert "process_stats" in sls_text

    def test_references_ingest_url_pillar(self, sls_text):
        """Must read ingest_url from the fleet_platform pillar."""
        assert "ingest_url" in sls_text

    def test_references_node_token_pillar(self, sls_text):
        """Must read node_token from the fleet_platform pillar."""
        assert "node_token" in sls_text

    def test_psutil_install_guard(self, sls_text):
        """Must guard psutil install with an unless: import check."""
        assert "import psutil" in sls_text

    def test_psutil_pip_install(self, sls_text):
        """Must contain a pip install for psutil."""
        assert "pip install" in sls_text
        assert "psutil" in sls_text

    def test_collector_file_path_deployed(self, sls_text):
        """Collector must be deployed to /opt/kri/process_collector.py."""
        assert "/opt/kri/process_collector.py" in sls_text

    def test_salt_source_reference(self, sls_text):
        """Must reference the Salt file-server source path."""
        assert "salt://base/files/process_collector.py" in sls_text

    def test_minion_id_from_grains(self, sls_text):
        """Must pass the minion ID from grains['id']."""
        assert "grains['id']" in sls_text

    def test_node_token_env_var(self, sls_text):
        """Must pass NODE_TOKEN as an env var to the collector."""
        assert "NODE_TOKEN" in sls_text

    def test_ingest_url_env_var(self, sls_text):
        """Must pass INGEST_URL as an env var to the collector."""
        assert "INGEST_URL" in sls_text

    def test_conditional_guard_on_ingest_url(self, sls_text):
        """Must be guarded by {% if ingest_url %} so empty pillar is safe."""
        assert "{% if ingest_url %}" in sls_text
