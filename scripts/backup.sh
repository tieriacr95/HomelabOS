#!/usr/bin/env bash
# Consistent, encrypted backup using restic. Requires a configured restic repository.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
: "${HOMELAB_RESTIC_REPOSITORY:?Set HOMELAB_RESTIC_REPOSITORY}"
: "${HOMELAB_RESTIC_PASSWORD_FILE:?Set HOMELAB_RESTIC_PASSWORD_FILE}"
command -v restic >/dev/null || { echo "Install restic first." >&2; exit 1; }
[[ -f data/homelabos.db ]] || { echo "No database yet." >&2; exit 1; }
TEMP="$(mktemp -d)"
chmod 700 "$TEMP"
trap 'rm -rf "$TEMP"' EXIT
python3 - "$TEMP/homelabos.db" <<'PY'
import sqlite3
import sys
from pathlib import Path
src = sqlite3.connect('data/homelabos.db')
dst = sqlite3.connect(sys.argv[1])
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
PY
RESTIC_REPOSITORY="$HOMELAB_RESTIC_REPOSITORY" \
RESTIC_PASSWORD_FILE="$HOMELAB_RESTIC_PASSWORD_FILE" \
  restic backup "$TEMP/homelabos.db" "$ROOT/config"
echo "Encrypted backup completed. Verify restores regularly with restic restore."
