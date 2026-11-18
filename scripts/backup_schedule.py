#!/usr/bin/env python3
"""Opt-in local Fedora systemd user timer for HomeLab backups."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import backup_manager as backup

UNIT_DIR = Path.home() / ".config/systemd/user"
SERVICE = UNIT_DIR / "homelabos-backup.service"
TIMER = UNIT_DIR / "homelabos-backup.timer"


def systemctl(*args):
    completed = subprocess.run(["systemctl", "--user", *args], check=False)
    if completed.returncode:
        raise SystemExit("systemctl --user operation failed")


def main():
    parser = argparse.ArgumentParser(description="Manage HomeLab OS backup schedule")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", metavar="HH:MM",
                       help="Daily local time (e.g. 03:00)")
    group.add_argument("--disable", action="store_true")
    group.add_argument("--status", action="store_true")
    args=parser.parse_args()

    if args.status:
        systemctl("list-timers", "--all", "homelabos-backup.timer")
        return
    if args.disable:
        systemctl("disable", "--now", "homelabos-backup.timer")
        print("Automated backups disabled. Existing encrypted snapshots remain.")
        return
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", args.enable):
        parser.error("Time must be 24-hour HH:MM")
    config, error = backup.settings()
    if error:
        parser.error(error)
    if not config["sources"]:
        parser.error("No backup resources selected")
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    UNIT_DIR.chmod(0o700)
    python = Path.home() / ".local/share/homelabos/venv/bin/python"
    if not python.exists():
        parser.error("Install HomeLab OS first with bash scripts/install.sh")
    script = ROOT / "agent/backup_manager.py"
    SERVICE.write_text(
        "[Unit]\nDescription=HomeLab OS encrypted restic backup\n"
        "After=docker.service\n\n"
        "[Service]\nType=oneshot\n"
        "ExecStart=" + str(python) + " " + str(script) + "\n"
        "UMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\n"
        "ProtectSystem=full\nRestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n"
        "TimeoutStartSec=2h\n\n", encoding="utf-8")
    TIMER.write_text(
        "[Unit]\nDescription=HomeLab OS daily backup schedule\n\n"
        "[Timer]\nOnCalendar=*-*-* " + args.enable +
        ":00\nRandomizedDelaySec=10m\nPersistent=false\n"
        "Unit=homelabos-backup.service\n\n"
        "[Install]\nWantedBy=timers.target\n", encoding="utf-8")
    systemctl("daemon-reload")
    systemctl("enable", "--now", "homelabos-backup.timer")
    print("Scheduled daily backup at",args.enable,"local time (+ up to 10 min random delay)")
    print("View status: systemctl --user list-timers homelabos-backup.timer")
    print("View logs: journalctl --user -u homelabos-backup.service")


if __name__ == "__main__":
    main()
