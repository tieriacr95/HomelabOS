#!/usr/bin/env bash
# Explicit opt-in privilege delegation: execute as your normal user.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "$(id -u)" == 0 ]]; then
  echo "Run as your regular Fedora user, not root." >&2
  exit 1
fi
USER_NAME="$(id -un)"
if [[ ! "$USER_NAME" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo "Unsupported username for sudoers." >&2
  exit 1
fi
DEST="/usr/local/libexec/homelabos/package-helper"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cat >"$TMP" <<EOF
# HomeLab OS: opt-in, exact command/argument allowlist.
$USER_NAME ALL=(root) NOPASSWD: $DEST dnf-upgrade, $DEST flatpak-system-upgrade
EOF
sudo visudo -cf "$TMP"
sudo install -d -o root -g root -m 0755 /usr/local/libexec/homelabos
sudo install -o root -g root -m 0755 helpers/package-helper "$DEST"
sudo install -o root -g root -m 0440 "$TMP" /etc/sudoers.d/homelabos-packages
sudo visudo -cf /etc/sudoers.d/homelabos-packages
echo "Approved package helper installed. Updating agent unit sandbox settings."
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
echo "Done. DNF and system Flatpak upgrades are now available in HomeLab OS."
