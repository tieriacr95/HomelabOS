#!/usr/bin/env python3
"""Interactive/local opt-in restic repository initializer. Never run under sudo."""
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import backup_manager as backup

def write_private(path, content):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as writer:
        writer.write(content)


def main():
    parser = argparse.ArgumentParser(description="Initialize encrypted HomeLab backups")
    parser.add_argument("--repository", default=str(Path.home() / "Backups/HomeLabOS"),
                        help="New local restic repository directory; must not already exist")
    parser.add_argument("--include-discovered-postgres", action="store_true",
                        help="Explicitly add discovered PostgreSQL containers as backup targets")
    parser.add_argument("--include-volume", action="append", default=[],
                        help="Explicit Docker volume name to include (repeatable)")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Do not run with sudo")
    if not shutil.which("restic"):
        parser.error("restic is not installed. On Fedora run: sudo dnf install restic")
    path = Path(args.repository).expanduser().resolve()
    if path.exists() or path == Path.home() or not path.is_absolute():
        parser.error("Choose a NEW, dedicated local repository directory")
    if not Path.home().resolve() in path.parents:
        parser.error("Local repository must be inside your Fedora home directory")
    if backup.TARGETS.exists() or backup.CREDENTIALS.exists():
        parser.error("Backup configuration already exists. No credentials overwritten.")
    path.parent.mkdir(parents=True, exist_ok=True)
    backup._secure_dir(backup.CONFIG_DIR)
    pwd = backup.CONFIG_DIR / "restic-password"
    if pwd.exists():
        parser.error("Existing password file found; refusing overwrite")
    discovery = backup.inventory()
    names = {x["name"] for x in discovery["postgres"]}
    volumes = set(discovery["volumes"])
    sources = [{"name": "homelab", "type": "homelab"}]
    if args.include_discovered_postgres:
        sources += [{"type": "postgres", "name": n} for n in sorted(names)]
    for name in args.include_volume:
        if name not in volumes:
            parser.error("Docker volume not found: " + name)
        if not backup.NAME_RE.fullmatch(name):
            parser.error("Invalid volume name")
        sources.append({"type": "volume", "name": name})
    if len(sources) > backup.MAX_ITEMS:
        parser.error("Too many sources")
    created=[]
    try:
        write_private(pwd, secrets.token_urlsafe(64) + "\n")
        created.append(pwd)
        env_content = "RESTIC_REPOSITORY=" + str(path) + "\n" + \
                      "RESTIC_PASSWORD_FILE=" + str(pwd) + "\n"
        write_private(backup.CREDENTIALS, env_content)
        created.append(backup.CREDENTIALS)
        write_private(backup.TARGETS, json.dumps({
            "sources": sources,
            "retention": {"daily": 7, "weekly": 4, "monthly": 6}
        }, indent=2) + "\n")
        created.append(backup.TARGETS)
        backup._secure_dir(backup.STATE_DIR)
        env = backup._restic_env()
        result = subprocess.run(["restic", "init"], env=env, check=False, timeout=90)
        if result.returncode:
            raise RuntimeError("restic init failed")
    except Exception:
        for file in created:
            file.unlink(missing_ok=True)
        raise
    print("Restic repository initialized:", path)
    print("Private config:", backup.TARGETS)
    print("Password stored only on the local host:", pwd)
    print("IMPORTANT: make a secure independent copy of the restic password.")
    print("A repository on the same disk is NOT disaster recovery: replicate it off-host.")
    print("Edit the 0600 backup.json to include selected PostgreSQL containers and volumes.")
    print("Backup jobs remain disabled until you explicitly start or schedule them.")
    print("Regenerate the agent sandbox to allow the new local restic repository:")
    print("  python3 scripts/install_agent.py && systemctl --user daemon-reload && systemctl --user restart homelabos-agent")


if __name__ == "__main__":
    main()
