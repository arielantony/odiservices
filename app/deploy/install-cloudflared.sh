#!/usr/bin/env bash
# Install cloudflared on the Lightsail host and run it as a service (OPS-04).
# Run once as the deploy user, with the tunnel token on standard input:
#   tofu output -raw tunnel_token | ssh deploy@<public_ip> /opt/odiservices/app/deploy/install-cloudflared.sh
# The token is never an argument, never in the shell history and never printed.
set -euo pipefail

ENV_FILE=/etc/odiservices/cloudflared.env
UNIT=/etc/systemd/system/cloudflared.service

if [ -t 0 ]; then
  echo "refusing to run: the tunnel token must come on standard input" >&2
  exit 1
fi
IFS= read -r TUNNEL_TOKEN || true
if [ -z "$TUNNEL_TOKEN" ]; then
  echo "refusing to run: standard input is empty" >&2
  exit 1
fi

if ! command -v cloudflared > /dev/null; then
  sudo install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq cloudflared
fi

# The env file is root-only (0600). It is created empty first, so the token is
# never in a file that other users can read.
sudo install -d -m 0700 -o root -g root /etc/odiservices
sudo install -m 0600 -o root -g root /dev/null "$ENV_FILE"
printf 'TUNNEL_TOKEN=%s\n' "$TUNNEL_TOKEN" | sudo tee "$ENV_FILE" > /dev/null
unset TUNNEL_TOKEN

sudo tee "$UNIT" > /dev/null <<'UNIT_FILE'
[Unit]
Description=cloudflared tunnel for the OdiServices portal
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/etc/odiservices/cloudflared.env
ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT_FILE

sudo systemctl daemon-reload
sudo systemctl enable cloudflared
sudo systemctl restart cloudflared

# Wait for a registered connection (60 s). The journal never holds the token.
for _ in $(seq 1 30); do
  if sudo journalctl -u cloudflared --no-pager --since "-2min" 2> /dev/null \
    | grep -q "Registered tunnel connection"; then
    echo "cloudflared: active, tunnel connection registered"
    exit 0
  fi
  sleep 2
done
echo "cloudflared did not register a connection in 60 s; see: journalctl -u cloudflared" >&2
exit 1
