#!/usr/bin/env python3
"""Opt-in weekly HomeLab restic verification, no arbitrary maintenance commands."""
import argparse
import os
import subprocess
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from agent import backup_manager

UNITS=Path.home()/".config/systemd/user"

def systemctl(*parts):
    proc=subprocess.run(["systemctl","--user",*parts],check=False)
    if proc.returncode:
        raise SystemExit("systemctl --user failed")


def main():
    parser=argparse.ArgumentParser(description="Scheduled restic integrity checks")
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--enable",action="store_true")
    actions.add_argument("--disable",action="store_true")
    actions.add_argument("--status",action="store_true")
    args=parser.parse_args()
    if os.geteuid()==0:
        parser.error("Do not run as root")
    if args.status:
        systemctl("list-timers","--all","homelabos-maintenance.timer")
        return
    if args.disable:
        systemctl("disable","--now","homelabos-maintenance.timer")
        print("Weekly maintenance verification disabled")
        return
    conf,err=backup_manager.settings()
    if err:
        parser.error(err)
    python=Path.home()/".local/share/homelabos/venv/bin/python"
    if not python.exists():
        parser.error("Install HomeLab OS first")
    UNITS.mkdir(parents=True,exist_ok=True)
    UNITS.chmod(0o700)
    (UNITS/"homelabos-maintenance.service").write_text(
        "[Unit]\nDescription=HomeLab OS weekly encrypted backup integrity verification\n"
        "After=network-online.target\n\n"
        "[Service]\nType=oneshot\n"
        "ExecStart="+str(python)+" "+str(ROOT/"agent/maintenance_runner.py")+"\n"
        "UMask=0077\nNoNewPrivileges=true\nProtectSystem=full\nPrivateTmp=true\n"
        "TimeoutStartSec=6h\n\n",encoding="utf-8")
    (UNITS/"homelabos-maintenance.timer").write_text(
        "[Unit]\nDescription=HomeLab OS weekly maintenance verification\n\n"
        "[Timer]\nOnCalendar=Sun *-*-* 04:00:00\n"
        "RandomizedDelaySec=15min\nPersistent=false\n"
        "Unit=homelabos-maintenance.service\n\n"
        "[Install]\nWantedBy=timers.target\n",encoding="utf-8")
    systemctl("daemon-reload")
    systemctl("enable","--now","homelabos-maintenance.timer")
    print("Weekly restic verification scheduled Sunday 04:00 (+ up to 15 min)")
    print("Task only verifies encrypted backup integrity; it does not restart or modify apps")


if __name__=="__main__":
    main()
