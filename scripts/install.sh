#!/usr/bin/env bash
# Install HomeLab OS on Fedora. Run as your normal desktop user, never with sudo.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this script as your normal Fedora user (without sudo)." >&2
  exit 1
fi
for cmd in python3 docker systemctl; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd" >&2; exit 1; }
done
docker compose version >/dev/null || { echo "Install Docker Compose v2 first." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not accessible to this user. Fix Docker permissions first." >&2; exit 1; }

python3 - <<'PY'
import os
import secrets
from pathlib import Path
p = Path('.env')
if not p.exists():
    p.write_text(
        'HOMELAB_AGENT_TOKEN=' + secrets.token_urlsafe(48) + '\n'
        'HOMELAB_SETUP_TOKEN=' + secrets.token_urlsafe(32) + '\n'
        'HOMELAB_COOKIE_SECURE=false\n'
        'HOMELAB_ALLOWED_CONTAINERS=\n'
        'LOCAL_UID=' + str(os.getuid()) + '\n'
        'LOCAL_GID=' + str(os.getgid()) + '\n'
    )
    p.chmod(0o600)
    print('Generated .env with new random credentials.')
else:
    print('Using existing .env; credentials were not overwritten.')
Path('data').mkdir(exist_ok=True)
Path('data').chmod(0o700)
PY

VENV="$HOME/.local/share/homelabos/venv"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check -r agent/requirements.txt

python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user enable --now homelabos-agent.service
systemctl --user restart homelabos-agent.service

docker compose up -d --build
echo
echo "HomeLab OS installed: http://localhost:8090"
echo "First login: create an admin account with the token from:"
echo "  grep '^HOMELAB_SETUP_TOKEN=' .env"
echo "Agent status: systemctl --user status homelabos-agent"
