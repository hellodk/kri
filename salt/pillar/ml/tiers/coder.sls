# Coder tier (#712) — Qwen2.5-Coder-14B, 4-bit MLX. Tag the matching kri
# LLMEndpoint with model_capabilities="coder_yaml,coder".
ml:
  mlx_serve:
    tier: coder
    model: mlx-community/Qwen2.5-Coder-14B-Instruct-4bit
    port: 8080
    max_concurrent: 1
    context_cap: 8192
