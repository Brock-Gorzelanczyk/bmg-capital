# BMG Capital — Claude CLI Relay Server

Routes Railway LLM calls through Brock's Mac `claude` CLI via Cloudflare Tunnel.
This avoids direct Anthropic API billing from Railway for most calls.

## One-time setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Set env var:
   ```
   export RELAY_AUTH_TOKEN=<generate a strong random token, 32+ chars>
   ```

3. Set up Cloudflare Tunnel (run once):
   ```
   CF_HOSTNAME=bmg-relay.<your-zone> bash setup_tunnel.sh
   ```

4. Copy plist to LaunchAgents and replace token placeholder:
   ```
   cp com.bmg.relay.plist ~/Library/LaunchAgents/
   # Edit ~/Library/LaunchAgents/com.bmg.relay.plist — replace REPLACE_WITH_TOKEN
   launchctl load ~/Library/LaunchAgents/com.bmg.relay.plist
   ```

5. Set Railway env vars:
   - `RELAY_URL=https://bmg-relay.<your-zone>`
   - `RELAY_AUTH_TOKEN=<same token>`
   - `FALLBACK_TO_API=false`

## Verify

```bash
curl https://bmg-relay.<your-zone>/health
# {"ok":true,"claude_cli":"found","version":"..."}

curl -X POST https://bmg-relay.<your-zone>/infer \
  -H "Authorization: Bearer $RELAY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","prompt":"reply with OK","max_tokens":20}'
# {"response_text":"OK","model":"...","duration_ms":...,"source":"claude_cli"}
```

## Local run (development)

```
uvicorn claude_relay_server:app --host 127.0.0.1 --port 8787
```

## Logs

Per-request JSONL at `relay/logs/requests.jsonl`.
