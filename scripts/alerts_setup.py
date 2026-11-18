#!/usr/bin/env python3
"""Explicit setup for private HomeLab Telegram credentials and monitoring timer."""
import argparse
import getpass
import json
import os
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
CONFIG=Path.home()/".config/homelabos"
USER_UNITS=Path.home()/".config/systemd/user"


def write_private(path,data):
    CONFIG.mkdir(parents=True,exist_ok=True)
    CONFIG.chmod(0o700)
    if path.exists():
        raise SystemExit("Already configured; use --replace explicitly to change credentials")
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(data,f)


def systemctl(*args):
    r=subprocess.run(["systemctl","--user",*args],check=False)
    if r.returncode:
        raise SystemExit("systemctl --user failed")


def main():
    p=argparse.ArgumentParser(description="HomeLab OS proactive monitoring setup")
    option=p.add_mutually_exclusive_group(required=True)
    option.add_argument("--telegram",action="store_true")
    option.add_argument("--enable",action="store_true",help="Enable monitoring every two minutes")
    option.add_argument("--disable",action="store_true",help="Disable timer; preserve incidents")
    option.add_argument("--status",action="store_true")
    p.add_argument("--replace",action="store_true",help="Replace existing Telegram credentials")
    args=p.parse_args()
    if os.geteuid()==0:
        p.error("Run as Fedora desktop user, not root")
    if args.telegram:
        token=getpass.getpass("Telegram bot token (hidden): ").strip()
        chat=input("Telegram chat ID: ").strip()
        if not re.fullmatch(r"[0-9]{5,15}:[A-Za-z0-9_-]{30,128}",token):
            p.error("Invalid bot token format")
        if not re.fullmatch(r"-?[0-9]{4,20}",chat):
            p.error("Invalid Telegram chat ID")
        target=CONFIG/"telegram.json"
        if args.replace and target.exists():
            if target.stat().st_uid != os.getuid() or target.stat().st_mode&0o077:
                p.error("Existing Telegram file permissions are unsafe")
            target.unlink()
        write_private(target,{"bot_token":token,"chat_id":chat})
        print("Telegram credentials stored privately at:",target)
        print("Test from HomeLab OS > Alertas > Enviar prueba")
        return
    if args.status:
        systemctl("list-timers","--all","homelabos-alerts.timer")
        return
    if args.disable:
        systemctl("disable","--now","homelabos-alerts.timer")
        print("Monitoring timer disabled; existing incident history preserved.")
        return
    USER_UNITS.mkdir(parents=True,exist_ok=True)
    USER_UNITS.chmod(0o700)
    python=Path.home()/".local/share/homelabos/venv/bin/python"
    if not python.is_file():
        p.error("HomeLab OS agent not installed")
    service=USER_UNITS/"homelabos-alerts.service"
    timer=USER_UNITS/"homelabos-alerts.timer"
    script=ROOT/"agent/alerts_manager.py"
    # Shares agent's private user state; no shell or environment secrets.
    service.write_text(
        "[Unit]\nDescription=HomeLab OS monitoring and Telegram alerts\n"
        "After=network-online.target docker.service\n\n"
        "[Service]\nType=oneshot\n"
        "ExecStart="+str(python)+" "+str(script)+"\n"
        "UMask=0077\nNoNewPrivileges=true\n"
        "ProtectSystem=full\nPrivateTmp=true\nTimeoutStartSec=90\n\n",
        encoding="utf-8")
    timer.write_text(
        "[Unit]\nDescription=HomeLab OS proactive alert polling\n\n"
        "[Timer]\nOnBootSec=2min\nOnUnitInactiveSec=2min\n"
        "RandomizedDelaySec=15s\nPersistent=false\n"
        "Unit=homelabos-alerts.service\n\n"
        "[Install]\nWantedBy=timers.target\n",encoding="utf-8")
    systemctl("daemon-reload")
    systemctl("enable","--now","homelabos-alerts.timer")
    print("Timer enabled. ALSO enable rule processing from HomeLab OS > Alertas.")
    print("No Telegram message is sent unless notify_telegram is enabled.")


if __name__=="__main__":
    main()
