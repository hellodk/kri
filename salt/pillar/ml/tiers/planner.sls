# Planner tier (#712) — Qwen2.5-14B-Instruct, 4-bit MLX. 16 GB is tight: single
# concurrent request, 8K session cap. Tag the matching kri LLMEndpoint with
# model_capabilities="planner" so the tier-router selects it.
ml:
  mlx_serve:
    tier: planner
    model: mlx-community/Qwen2.5-14B-Instruct-4bit
    port: 8080
    max_concurrent: 1
    context_cap: 8192
