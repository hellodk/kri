"""Tests for #58: Salt ML state library."""
from pathlib import Path


def test_artifactory_state_exists():
    assert Path("salt/states/common/artifactory.sls").exists()


def test_artifactory_state_uses_pillar():
    src = Path("salt/states/common/artifactory.sls").read_text()
    assert "pillar" in src and "pypi_proxy" in src


def test_vllm_state_uses_artifactory_include():
    src = Path("salt/states/ml/vllm/init.sls").read_text()
    assert "include" in src and "common.artifactory" in src


def test_vllm_state_pip_install():
    src = Path("salt/states/ml/vllm/init.sls").read_text()
    assert "pip" in src and "vllm" in src


def test_vllm_remove_exists():
    assert Path("salt/states/ml/vllm/remove.sls").exists()


def test_llamacpp_state_uses_artifactory():
    src = Path("salt/states/ml/llamacpp/init.sls").read_text()
    assert "artifactory" in src or "binary_repo" in src or "binary_url" in src


def test_llamacpp_remove_exists():
    assert Path("salt/states/ml/llamacpp/remove.sls").exists()


def test_ollama_state_downloads_from_artifactory():
    src = Path("salt/states/ml/ollama/init.sls").read_text()
    assert "artifactory" in src or "binary_repo" in src or "binary_url" in src


def test_ollama_remove_exists():
    assert Path("salt/states/ml/ollama/remove.sls").exists()


def test_mlx_cluster_coordinator_vs_worker():
    src = Path("salt/states/ml/mlx_cluster/init.sls").read_text()
    assert "coordinator" in src and "worker" in src


def test_mlx_cluster_remove_exists():
    assert Path("salt/states/ml/mlx_cluster/remove.sls").exists()


def test_mlx_updated_to_use_artifactory():
    src = Path("salt/states/mlx/init.sls").read_text()
    assert "common.artifactory" in src or "artifactory" in src


def test_mlx_no_huggingface_direct_download():
    src = Path("salt/states/mlx/init.sls").read_text()
    assert "huggingface_hub.commands" not in src


def test_artifactory_pillar_example_exists():
    assert Path("salt/pillar/artifactory.sls").exists()


def test_pillar_examples_exist():
    assert Path("salt/pillar/ml/vllm.sls.example").exists()
    assert Path("salt/pillar/ml/ollama.sls.example").exists()
    assert Path("salt/pillar/ml/mlx_cluster.sls.example").exists()
