# fleet_platform/services/model_catalog.py
"""Shared model catalog for all LLM providers.

Used by:
- LLM endpoint form (model selector dropdown, filtered by provider)
- MLX salt state pillar generator
- Future: auto-complete in the AI assistant panel
"""

from typing import TypedDict


class ModelEntry(TypedDict):
    id: str
    name: str
    provider: str
    context_length: int
    notes: str


CATALOG: list[ModelEntry] = [
    # ── Apple MLX (runs locally on each Mac Mini via mlx-lm serve) ───────────
    {
        "id": "mlx-community/Llama-3.2-1B-Instruct-4bit",
        "name": "Llama 3.2 1B (4-bit, ~700 MB)",
        "provider": "mlx",
        "context_length": 8192,
        "notes": "Fastest; good for quick fleet commands",
    },
    {
        "id": "mlx-community/Llama-3.2-3B-Instruct-4bit",
        "name": "Llama 3.2 3B (4-bit, ~2 GB)",
        "provider": "mlx",
        "context_length": 8192,
        "notes": "Recommended default for most Mac Minis",
    },
    {
        "id": "mlx-community/Llama-3.1-8B-Instruct-4bit",
        "name": "Llama 3.1 8B (4-bit, ~5 GB)",
        "provider": "mlx",
        "context_length": 32768,
        "notes": "Better reasoning; needs ≥8 GB unified memory",
    },
    {
        "id": "mlx-community/Mistral-7B-Instruct-v0.3-4bit",
        "name": "Mistral 7B Instruct v0.3 (4-bit, ~4.5 GB)",
        "provider": "mlx",
        "context_length": 32768,
        "notes": "Strong instruction following; good for SaltStack generation",
    },
    {
        "id": "mlx-community/Phi-3.5-mini-instruct-4bit",
        "name": "Phi-3.5 Mini (4-bit, ~2.3 GB)",
        "provider": "mlx",
        "context_length": 128000,
        "notes": "Long context; compact footprint",
    },
    {
        "id": "mlx-community/Qwen2.5-7B-Instruct-4bit",
        "name": "Qwen 2.5 7B (4-bit, ~4.5 GB)",
        "provider": "mlx",
        "context_length": 32768,
        "notes": "Strong coder; good for Ansible playbook generation",
    },
    {
        "id": "mlx-community/Qwen2.5-14B-Instruct-4bit",
        "name": "Qwen 2.5 14B (4-bit, ~9 GB)",
        "provider": "mlx",
        "context_length": 32768,
        "notes": "Best MLX quality; needs Mac Mini with 16+ GB unified memory",
    },
    # ── Ollama / openai_compat (local via http://localhost:11434) ─────────────
    {
        "id": "llama3.2",
        "name": "Llama 3.2 3B (Ollama)",
        "provider": "openai_compat",
        "context_length": 8192,
        "notes": "Pull with: ollama pull llama3.2",
    },
    {
        "id": "llama3.1:8b",
        "name": "Llama 3.1 8B (Ollama)",
        "provider": "openai_compat",
        "context_length": 32768,
        "notes": "Pull with: ollama pull llama3.1:8b",
    },
    {
        "id": "mistral",
        "name": "Mistral 7B (Ollama)",
        "provider": "openai_compat",
        "context_length": 32768,
        "notes": "Pull with: ollama pull mistral",
    },
    {
        "id": "qwen2.5-coder:7b",
        "name": "Qwen 2.5 Coder 7B (Ollama)",
        "provider": "openai_compat",
        "context_length": 32768,
        "notes": "Optimised for code/YAML/SaltStack; ollama pull qwen2.5-coder:7b",
    },
    {
        "id": "phi3.5",
        "name": "Phi-3.5 Mini (Ollama)",
        "provider": "openai_compat",
        "context_length": 128000,
        "notes": "Pull with: ollama pull phi3.5",
    },
    # ── Anthropic (Claude via native SDK) ────────────────────────────────────
    {
        "id": "claude-haiku-4-5-20251001",
        "name": "Claude Haiku 4.5",
        "provider": "anthropic",
        "context_length": 200000,
        "notes": "Fastest and cheapest; good for routine fleet queries",
    },
    {
        "id": "claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "context_length": 200000,
        "notes": "Best quality/speed balance; recommended for playbook generation",
    },
    {
        "id": "claude-opus-4-7",
        "name": "Claude Opus 4.7",
        "provider": "anthropic",
        "context_length": 200000,
        "notes": "Most capable; use for complex multi-step automation",
    },
    # ── OpenAI (via openai_compat with api.openai.com) ────────────────────────
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "openai_compat",
        "context_length": 128000,
        "notes": "Fast and affordable; base_url: https://api.openai.com/v1",
    },
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai_compat",
        "context_length": 128000,
        "notes": "Best OpenAI model; base_url: https://api.openai.com/v1",
    },
    # ── Groq (via openai_compat, ultra-fast inference) ────────────────────────
    {
        "id": "llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B (Groq)",
        "provider": "openai_compat",
        "context_length": 32768,
        "notes": "Very fast; base_url: https://api.groq.com/openai/v1",
    },
    {
        "id": "mixtral-8x7b-32768",
        "name": "Mixtral 8x7B (Groq)",
        "provider": "openai_compat",
        "context_length": 32768,
        "notes": "Fast MoE model; base_url: https://api.groq.com/openai/v1",
    },
]


def get_models(provider: str | None = None) -> list[ModelEntry]:
    """Return catalog entries, optionally filtered by provider."""
    if provider is None:
        return CATALOG
    return [m for m in CATALOG if m["provider"] == provider]


def get_model(model_id: str) -> ModelEntry | None:
    """Look up a model by its ID."""
    return next((m for m in CATALOG if m["id"] == model_id), None)
