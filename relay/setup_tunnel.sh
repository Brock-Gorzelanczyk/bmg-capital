#!/usr/bin/env bash
set -euo pipefail

if ! command -v cloudflared >/dev/null; then
  brew install cloudflared
fi

if [ ! -f ~/.cloudflared/cert.pem ]; then
  cloudflared tunnel login
fi

TUNNEL_NAME="bmg-relay"
if ! cloudflared tunnel list | grep -q "$TUNNEL_NAME"; then
  cloudflared tunnel create "$TUNNEL_NAME"
fi

: "${CF_HOSTNAME:?set CF_HOSTNAME=bmg-relay.<your-zone> before running}"
cloudflared tunnel route dns "$TUNNEL_NAME" "$CF_HOSTNAME"

mkdir -p ~/.cloudflared
TUNNEL_ID=$(cloudflared tunnel list | awk -v n="$TUNNEL_NAME" '$2==n {print $1}')
cat > ~/.cloudflared/config.yml <<YAML
tunnel: $TUNNEL_NAME
credentials-file: $HOME/.cloudflared/$TUNNEL_ID.json
ingress:
  - hostname: $CF_HOSTNAME
    service: http://127.0.0.1:8787
  - service: http_status:404
YAML

sudo cloudflared service install
echo "Tunnel up: https://$CF_HOSTNAME -> http://127.0.0.1:8787"
