#!/usr/bin/env bash
# Sets up llama.cpp and runs the nomic-embed-text-v1.5 embedding server.
#
# What this does:
#   1. Downloads the llama.cpp CPU binary for Ubuntu x64 (no sudo, no build)
#   2. Downloads nomic-embed-text-v1.5.Q8_0.gguf (~144 MB, 768-dim)
#   3. Starts llama-server on port 8080 with --embeddings --pooling mean
#
# After it starts, set in kri Platform Settings:
#   LLM_EMBED_BASE_URL = http://<this-host>:8080
#
# Port override:   LLAMA_PORT=9090 ./setup-embed-server.sh
# Re-run to restart (model + binary are cached; no re-download).

set -euo pipefail

INSTALL_DIR="${HOME}/.local/llama.cpp"
BIN_DIR="${INSTALL_DIR}/bin"
MODEL_DIR="${INSTALL_DIR}/models"
MODEL_FILE="nomic-embed-text-v1.5.Q8_0.gguf"
MODEL_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/${MODEL_FILE}"
PORT="${LLAMA_PORT:-8080}"

mkdir -p "${BIN_DIR}" "${MODEL_DIR}"

# ── 1. Locate or download llama-server ────────────────────────────────────────

LLAMA_SERVER="${BIN_DIR}/llama-server"

if command -v llama-server &>/dev/null && [[ ! -x "${LLAMA_SERVER}" ]]; then
  LLAMA_SERVER="$(command -v llama-server)"
  echo "[ok] using system llama-server: ${LLAMA_SERVER}"
elif [[ -x "${LLAMA_SERVER}" ]]; then
  echo "[ok] using cached llama-server: ${LLAMA_SERVER}"
else
  echo "[+] fetching latest llama.cpp release metadata..."

  RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest")

  # CPU-only Ubuntu x64 tarball — exclude vulkan / rocm / openvino variants
  ASSET_URL=$(python3 - <<'PY' "${RELEASE_JSON}"
import sys, json
data = json.loads(sys.argv[1])
for a in data["assets"]:
    n = a["name"]
    if (n.endswith("ubuntu-x64.tar.gz")
            and "vulkan" not in n
            and "rocm" not in n
            and "openvino" not in n):
        print(a["browser_download_url"])
        break
PY
  )

  if [[ -z "${ASSET_URL}" ]]; then
    echo "error: could not find ubuntu-x64 CPU tarball in latest release" >&2
    echo "       check https://github.com/ggml-org/llama.cpp/releases for asset names" >&2
    exit 1
  fi

  ASSET_NAME=$(basename "${ASSET_URL}")
  echo "[+] downloading ${ASSET_NAME}..."
  TMP_TAR=$(mktemp /tmp/llama-cpp-XXXXXX.tar.gz)
  curl -fSL --progress-bar -o "${TMP_TAR}" "${ASSET_URL}"

  echo "[+] extracting llama-server..."
  TMP_DIR=$(mktemp -d /tmp/llama-cpp-XXXXXX)
  tar -xf "${TMP_TAR}" -C "${TMP_DIR}"

  EXTRACTED=$(find "${TMP_DIR}" -name "llama-server" -type f 2>/dev/null | head -1)
  if [[ -z "${EXTRACTED}" ]]; then
    # Older builds used plain "server"
    EXTRACTED=$(find "${TMP_DIR}" -name "server" -type f 2>/dev/null | head -1)
  fi
  if [[ -z "${EXTRACTED}" ]]; then
    echo "error: llama-server binary not found in tarball" >&2
    ls -R "${TMP_DIR}" >&2
    rm -rf "${TMP_TAR}" "${TMP_DIR}"
    exit 1
  fi

  cp "${EXTRACTED}" "${LLAMA_SERVER}"
  chmod +x "${LLAMA_SERVER}"
  rm -rf "${TMP_TAR}" "${TMP_DIR}"
  echo "[ok] installed to ${LLAMA_SERVER}"
fi

# ── 2. Download model ─────────────────────────────────────────────────────────

MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"

if [[ -f "${MODEL_PATH}" ]]; then
  echo "[ok] model already present: ${MODEL_PATH}"
else
  echo "[+] downloading ${MODEL_FILE} (~144 MB)..."
  curl -fSL --progress-bar -o "${MODEL_PATH}.tmp" "${MODEL_URL}"
  mv "${MODEL_PATH}.tmp" "${MODEL_PATH}"
  echo "[ok] saved to ${MODEL_PATH}"
fi

# ── 3. Start server ───────────────────────────────────────────────────────────

echo ""
echo "  embedding server  →  http://0.0.0.0:${PORT}/v1/embeddings"
echo "  model             →  ${MODEL_FILE}"
echo "  pooling           →  mean  (required for nomic-embed-text)"
echo ""
echo "  kri Platform Settings → LLM_EMBED_BASE_URL = http://<this-host>:${PORT}"
echo ""

exec "${LLAMA_SERVER}" \
  --model "${MODEL_PATH}" \
  --embeddings \
  --pooling mean \
  --ctx-size 2048 \
  --batch-size 512 \
  --host 0.0.0.0 \
  --port "${PORT}"
