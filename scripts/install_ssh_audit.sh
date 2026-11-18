#!/usr/bin/env bash
# Explicit opt-in to a minimal SSH audit helper. Run as the desktop user.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "$(id -u)" == 0 ]]; then echo "Use your non-root Fedora account." >&2; exit 1; fi
ACCOUNT="$(id -un)"
if [[ ! "$ACCOUNT" =~ ^[a-z_][a-z0-9_-]*$ ]]; then echo "Invalid account for sudoers." >&2; exit 1; fi
DEST=/usr/local/libexec/homelabos/ssh-audit-helper
TEMP="$(mktemp)"
trap 'rm -f "$TEMP"' EXIT
printf '%s ALL=(root) NOPASSWD: %s\n' "$ACCOUNT" "$DEST" >"$TEMP"
sudo visudo -cf "$TEMP"
sudo install -d -o root -g root -m 0755 /usr/local/libexec/homelabos
sudo install -o root -g root -m 0755 helpers/ssh-audit-helper "$DEST"
sudo install -o root -g root -m 0440 "$TEMP" /etc/sudoers.d/homelabos-ssh-audit
sudo visudo -cf /etc/sudoers.d/homelabos-ssh-audit
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
echo "Restricted SSH audit enabled. No host keys or raw SSH configuration are exported."
