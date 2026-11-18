"""Fedora package inspection and explicitly approved update jobs.

The agent runs as the desktop user. Root updates require an optional,
root-owned, argument-locked sudo helper installed manually by the owner.
No arbitrary package installation or untrusted command arguments.
"""
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

COMMANDS = ("dnf", "flatpak-user", "flatpak-system")
PHRASES = {"dnf": "ACTUALIZAR DNF", "flatpak-user": "ACTUALIZAR FLATPAK USUARIO",
           "flatpak-system": "ACTUALIZAR FLATPAK SISTEMA"}
HELPER = "/usr/local/libexec/homelabos/package-helper"
LIMIT = 3000
_LOCK = threading.Lock()
_JOBS = {}
_ACTIVE = None
_CACHE = {"at": 0, "data": None}


def run(argv, timeout=25, output_limit=160_000):
    if not argv or not all(isinstance(x, str) for x in argv):
        return 127, "", "Invalid arguments"
    try:
        completed = subprocess.run(argv, capture_output=True, timeout=timeout,
                                   check=False, env={k: v for k, v in os.environ.items() if k in (
                                       "PATH", "HOME", "USER", "LOGNAME", "XDG_RUNTIME_DIR",
                                       "DBUS_SESSION_BUS_ADDRESS", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                                       "XDG_CONFIG_HOME", "LANG") } | {"LC_ALL": "C"})
        return (completed.returncode, completed.stdout[:output_limit].decode("utf-8", "replace"),
                completed.stderr[:5000].decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired):
        return 124, "", "Command unavailable or timed out"


def rows(text, columns=3, limit=LIMIT):
    parsed = []
    for line in text.splitlines()[:limit]:
        values = line.split("\t")
        if len(values) >= columns:
            parsed.append([v.strip()[:250] for v in values[:columns]])
    return parsed


def dnf_binary():
    return shutil.which("dnf5") or shutil.which("dnf")


def dnf_status():
    exe = dnf_binary()
    if not exe:
        return {"available": False, "error": "DNF no instalado", "updates": [],
                "installed": [], "history": []}
    code, raw, err = run([exe, "repoquery", "--upgrades",
                          "--queryformat", "%{name}\t%{evr}\t%{arch}\t%{repoid}\n"])
    updates = [{"name": r[0], "version": r[1], "arch": r[2], "repo": r[3]}
               for r in rows(raw, 4, 1000)] if code == 0 else []
    rc, out, rpm_err = run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n"])
    installed = [{"name": r[0], "version": r[1], "arch": r[2]}
                 for r in rows(out, 3, 3000)] if rc == 0 else []
    hc, history, _ = run([exe, "history", "list"], timeout=20, output_limit=20_000)
    return {"available": True, "binary": os.path.basename(exe),
            "updates": updates, "installed": installed,
            "history": history.splitlines()[:25] if hc == 0 else [],
            "error": (err or "No se pudieron consultar actualizaciones")[:180] if code else None,
            "installed_error": rpm_err[:180] if rc else None,
            "total_installed_sample": len(installed),
            "upgrade_enabled": os.path.isfile(HELPER) and os.access(HELPER, os.X_OK)}


def flatpak_status(scope):
    executable = shutil.which("flatpak")
    if not executable:
        return {"available": False, "error": "Flatpak no instalado",
                "installed": [], "updates": []}
    installation = "--user" if scope == "user" else "--system"
    rc, raw, err = run([executable, "list", installation,
                        "--columns=application,name,branch,origin"], timeout=30)
    installed = [{"id": r[0], "name": r[1], "branch": r[2], "origin": r[3]}
                 for r in rows(raw, 4, 1000)] if rc == 0 else []
    uc, updates_raw, update_err = run([executable, "remote-ls", installation,
                                "--updates", "--columns=application,name,branch"], timeout=45)
    updates = [{"id": r[0], "name": r[1], "branch": r[2]}
               for r in rows(updates_raw, 3, 1000)] if uc == 0 else []
    return {"available": True, "installed": installed, "updates": updates,
            "error": (err or "No se pudo consultar Flatpak")[:180] if rc else
                     ((update_err or "Consulta de actualizaciones fallida")[:180] if uc else None),
            "upgrade_enabled": scope == "user" or (
                os.path.isfile(HELPER) and os.access(HELPER, os.X_OK))}


def inspect(refresh=False):
    now = time.time()
    with _LOCK:
        if not refresh and _CACHE["data"] and now - _CACHE["at"] < 300:
            return _CACHE["data"]
    # RPM/DNF and two Flatpak installations can query their remotes in parallel.
    with ThreadPoolExecutor(max_workers=3) as pool:
        dnf_future = pool.submit(dnf_status)
        user_future = pool.submit(flatpak_status, "user")
        system_future = pool.submit(flatpak_status, "system")
        result = {"timestamp": int(time.time()), "dnf": dnf_future.result(),
                  "flatpak_user": user_future.result(),
                  "flatpak_system": system_future.result(),
                  "active_job": _ACTIVE}
    with _LOCK:
        _CACHE.update(at=time.time(), data=result)
    return result


def upgrade_command(kind):
    if kind == "dnf":
        return ["sudo", "-n", HELPER, "dnf-upgrade"]
    if kind == "flatpak-system":
        return ["sudo", "-n", HELPER, "flatpak-system-upgrade"]
    if kind == "flatpak-user":
        flatpak = shutil.which("flatpak")
        if not flatpak:
            raise RuntimeError("Flatpak no disponible")
        return [flatpak, "update", "--user", "--noninteractive", "--assumeyes"]
    raise ValueError("Unsupported operation")


def upgrade_status(job_id):
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise LookupError("Job not found")
        return dict(job)


def _worker(job_id, kind):
    global _ACTIVE
    started = int(time.time())
    with _LOCK:
        _JOBS[job_id].update(state="running", started_at=started)
    try:
        argv = upgrade_command(kind)
        code, stdout, stderr = run(argv, timeout=1800, output_limit=80_000)
        with _LOCK:
            _JOBS[job_id].update(
                state="success" if code == 0 else "failed",
                returncode=code, output=(stdout + "\n" + stderr)[-9000:],
                finished_at=int(time.time()))
            _CACHE.update(at=0, data=None)
    except Exception:
        with _LOCK:
            _JOBS[job_id].update(state="failed",
                                output="No fue posible iniciar la actualización",
                                finished_at=int(time.time()))
    finally:
        with _LOCK:
            _ACTIVE = None


def start_upgrade(kind, confirmation):
    global _ACTIVE
    if kind not in COMMANDS:
        raise ValueError("Invalid update kind")
    if confirmation != PHRASES[kind]:
        raise PermissionError("Typed confirmation required")
    if kind in ("dnf", "flatpak-system") and (
            not os.path.isfile(HELPER) or not os.access(HELPER, os.X_OK)):
        raise PermissionError("Root helper not installed")
    with _LOCK:
        if _ACTIVE is not None:
            raise RuntimeError("Another package transaction is running")
        job_id = uuid.uuid4().hex
        _JOBS[job_id] = {"id": job_id, "kind": kind, "state": "queued",
                         "created_at": int(time.time()), "output": "",
                         "returncode": None}
        _ACTIVE = job_id
        for old in list(_JOBS)[:-20]:
            if old != _ACTIVE:
                _JOBS.pop(old, None)
    thread = threading.Thread(target=_worker, args=(job_id, kind), daemon=True)
    thread.start()
    return dict(_JOBS[job_id])


def last_jobs():
    with _LOCK:
        return [dict(j) for j in list(_JOBS.values())[-20:]][::-1]
