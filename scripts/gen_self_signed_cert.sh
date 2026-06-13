#!/usr/bin/env bash
# Generate a self-signed TLS certificate for kri (dev/home-lab use)
# For production, use a cert from your CA or Tailscale HTTPS

set -euo pipefail

CERT_DIR="${1:-$(dirname "$0")/../deploy/certs}"
mkdir -p "$CERT_DIR"

HOSTNAME="${KRI_HOSTNAME:-kri.local}"

openssl req -x509 -newkey rsa:4096 -keyout "$CERT_DIR/kri.key" -out "$CERT_DIR/kri.crt" \
    -days 3650 -nodes \
    -subj "/CN=$HOSTNAME/O=kri Fleet Platform/C=US" \
    -addext "subjectAltName=DNS:$HOSTNAME,DNS:localhost,IP:127.0.0.1"

chmod 600 "$CERT_DIR/kri.key"
chmod 644 "$CERT_DIR/kri.crt"

echo "Certificate generated:"
echo "  $CERT_DIR/kri.crt"
echo "  $CERT_DIR/kri.key"
echo ""
echo "To enable TLS:"
echo "  1. Update deploy/Dockerfile.frontend to copy deploy/nginx-tls.conf.template"
echo "     instead of deploy/nginx.conf.template into /etc/nginx/templates/"
echo "  2. Mount certs in docker-compose.yml:"
echo "     volumes:"
echo "       - ./certs:/etc/nginx/certs:ro"
echo "  3. Expose port 443: '443:443'"
echo "  4. Restart: ./scripts/kri rolling-deploy"
