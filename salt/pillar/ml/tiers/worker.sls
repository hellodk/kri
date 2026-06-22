# Worker tier (#712) — Qwen2.5-7B-Instruct, 4-bit MLX. Tag the matching kri
# LLMEndpoint with model_capabilities="fast_summarize,worker".
ml:
  mlx_serve:
    tier: worker
    model: mlx-community/Qwen2.5-7B-Instruct-4bit
    port: 8080
    max_concurrent: 2
    context_cap: 8192
