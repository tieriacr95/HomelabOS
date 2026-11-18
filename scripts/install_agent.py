#!/usr/bin/env python3
"""Create a least-privilege systemd --user unit for the Fedora collector."""
import os
import shlex
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if not env_file.is_file():
    raise SystemExit("Missing .env. Run bash scripts/install.sh first.")
values = {}
for line in env_file.read_text().splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k in ("HOMELAB_AGENT_TOKEN", "HOMELAB_ALLOWED_CONTAINERS", "HOMELAB_ALLOWED_SYSTEMD_UNITS"):
        values[k] = v
token = values.get("HOMELAB_AGENT_TOKEN", "")
if len(token) < 32:
    raise SystemExit("HOMELAB_AGENT_TOKEN must contain at least 32 characters.")

config = Path.home() / ".config/homelabos"
config.mkdir(parents=True, exist_ok=True)
config.chmod(0o700)
agent_env = config / "agent.env"
# Refuse newline injection into systemd EnvironmentFile.
for value in values.values():
    if "\n" in value or "\r" in value or '"' in value:
        raise SystemExit("Invalid characters in agent configuration")
agent_env.write_text(
    'HOMELAB_AGENT_TOKEN=' + token + '\n'
    'HOMELAB_ALLOWED_CONTAINERS=' + values.get("HOMELAB_ALLOWED_CONTAINERS", "") + '\n' +
    'HOMELAB_ALLOWED_SYSTEMD_UNITS=' + values.get("HOMELAB_ALLOWED_SYSTEMD_UNITS", "") + '\n'
)
agent_env.chmod(0o600)

# Relax sandbox only after optional root-owned helper + sudoers installation.
helper = Path("/usr/local/libexec/homelabos/package-helper")
sudoers = Path("/etc/sudoers.d/homelabos-packages")
def root_owned_safe(path):
    try:
        st = path.stat()
        return st.st_uid == 0 and not (st.st_mode & 0o022)
    except OSError:
        return False

privileged_mode = root_owned_safe(helper) and root_owned_safe(sudoers)
ssh_audit_mode = root_owned_safe(Path("/usr/local/libexec/homelabos/ssh-audit-helper")) and root_owned_safe(Path("/etc/sudoers.d/homelabos-ssh-audit"))
print("Package helper: " + ("enabled (reduced agent sandbox)" if privileged_mode
                            else "disabled (read-only DNF)"))

# Backups use a private writable staging folder. Preserve the existing
# read-only agent sandbox elsewhere; permit only the configured local repo.
backup_state = Path.home() / ".local/state/homelabos/backup"
backup_state.mkdir(parents=True, exist_ok=True)
backup_state.chmod(0o700)
alerts_state = Path.home() / ".local/state/homelabos/alerts"
alerts_state.mkdir(parents=True, exist_ok=True)
alerts_state.chmod(0o700)
backup_writes = [backup_state, alerts_state, config]
backup_env = Path.home() / ".config/homelabos/backup.env"
if backup_env.is_file() and backup_env.stat().st_uid == os.getuid() and (
        backup_env.stat().st_mode & 0o077) == 0:
    for line in backup_env.read_text(encoding="utf-8").splitlines():
        if line.startswith("RESTIC_REPOSITORY="):
            candidate = Path(line.partition("=")[2])
            if candidate.is_absolute():
                resolved = candidate.resolve()
                if Path.home() in resolved.parents and resolved.is_dir():
                    backup_writes.append(resolved)
                else:
                    print("Restic repository outside home is not writable inside the default agent sandbox")
backup_write_paths = "".join("ReadWritePaths=" + shlex.quote(str(path)) + "\n"
                            for path in backup_writes)

python = Path.home() / ".local/share/homelabos/venv/bin/python"
agent = root / "agent/agent.py"
unit_dir = Path.home() / ".config/systemd/user"
unit_dir.mkdir(parents=True, exist_ok=True)
unit = unit_dir / "homelabos-agent.service"
unit.write_text(
    "[Unit]\nDescription=HomeLab OS Fedora collector\nAfter=default.target\n\n"
    "[Service]\nType=simple\n"
    "EnvironmentFile=" + shlex.quote(str(agent_env)) + "\n"
    "ExecStart=" + shlex.quote(str(python)) + " " + shlex.quote(str(agent)) + "\n"
    "Restart=on-failure\nRestartSec=5\n"
    + ("NoNewPrivileges=false\n" if (privileged_mode or ssh_audit_mode) else "NoNewPrivileges=true\n")
    + ("" if privileged_mode else "ProtectSystem=strict\nProtectHome=read-only\n"
       "ReadWritePaths=-%h/.local/share/flatpak -%h/.cache\n"
     + backup_write_paths)
    + "PrivateTmp=true\nRestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX\n"
    "UMask=0077\n\n"
    "[Install]\nWantedBy=default.target\n"
)
print("Agent unit installed at:", unit)
