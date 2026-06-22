# Embed sidecar (#712) — BGE-M3, 4-bit MLX, on a dedicated worker subset (off
# planners). Tag the matching kri LLMEndpoint with model_capabilities="embed"
# and point LLM_EMBED_BASE_URL at it.
ml:
  mlx_serve:
    tier: embed
    model: mlx-community/bge-m3-4bit
    port: 8081
    max_concurrent: 4
    context_cap: 512
