"""Restic-backed, explicitly configured HomeLab backups and safe staged recovery.

Never accepts arbitrary shell commands, paths or Docker names from the HTTP
client. Backups are encrypted with restic; secrets remain in local 0600 files.
Restores ONLY to a private staging directory, never overwrite live data.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path

CONFIG_DIR = Path.home() / ".config/homelabos"
STATE_DIR = Path.home() / ".local/state/homelabos/backup"
TARGETS = CONFIG_DIR / "backup.json"
CREDENTIALS = CONFIG_DIR / "backup.env"
LOCK = STATE_DIR / "backup.lock"
JOBS = STATE_DIR / "jobs.json"
SNAPSHOT_RE = re.compile(r"[a-f0-9]{8,64}\Z")
NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")
MAX_ITEMS = 30
MAX_BYTES = 60 * 1024**3
_ACTIVE_LOCK = threading.Lock()
_ACTIVE = None
_RUNNING = {}


class BackupError(Exception):
    pass


def _secure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _assert_private(path):
    st = path.stat()
    if not path.is_file() or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise BackupError(f"Unsafe permissions or ownership for {path.name}")


def settings():
    if not TARGETS.exists() or not CREDENTIALS.exists():
        return None, "Backup not configured. Run python3 scripts/setup_backups.py"
    try:
        _assert_private(TARGETS)
        _assert_private(CREDENTIALS)
        config = json.loads(TARGETS.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Bad config")
        sources = config.get("sources", [])
        if not isinstance(sources, list) or len(sources) > MAX_ITEMS:
            raise ValueError("Too many configured resources")
        clean = []
        for item in sources:
            if not isinstance(item, dict) or item.get("type") not in (
                    "postgres", "volume", "directory", "homelab"):
                raise ValueError("Unknown target")
            kind = item["type"]
            name = item.get("name", "")
            if not isinstance(name, str) or not NAME_RE.fullmatch(name):
                raise ValueError("Invalid resource name")
            if kind == "directory":
                path = item.get("path")
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise ValueError("Directory target must have an absolute path")
                resolved = Path(path).resolve(strict=True)
                if not resolved.is_dir() or Path(path).is_symlink() or (
                    resolved != Path.home() and Path.home() not in resolved.parents):
                    raise ValueError("Directory target must be inside the user's home")
                clean.append({"type": kind, "name": name, "path": str(resolved)})
            else:
                clean.append({"type": kind, "name": name})
        retention = config.get("retention", {})
        if not isinstance(retention, dict):
            raise ValueError("Bad retention policy")
        policy = {}
        for key, default in (("daily", 7), ("weekly", 4), ("monthly", 6)):
            value = retention.get(key, default)
            if not isinstance(value, int) or not 1 <= value <= 120:
                raise ValueError("Invalid retention policy")
            policy[key] = value
        conf = {"sources": clean, "retention": policy,
                "utility_image": "busybox:1.36",
                "configured": True}
        env = {}
        for line in CREDENTIALS.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep or key not in ("RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE"):
                raise ValueError("Unknown credential setting")
            env[key] = value
        if set(env) != {"RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE"}:
            raise ValueError("Missing restic setting")
        pwd = Path(env["RESTIC_PASSWORD_FILE"])
        _assert_private(pwd)
        if not pwd.read_text(encoding="utf-8").strip():
            raise ValueError("Empty repository password")
        if not shutil.which("restic"):
            return conf, "restic is not installed on Fedora"
        return conf, None
    except (ValueError, OSError, BackupError) as exc:
        return None, "Invalid backup configuration or permissions: " + type(exc).__name__


def _restic_env():
    _assert_private(CREDENTIALS)
    conf = {}
    for line in CREDENTIALS.read_text(encoding="utf-8").splitlines():
        k, sep, value = line.partition("=")
        if sep and k in ("RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE"):
            conf[k] = value
    if set(conf) != {"RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE"}:
        raise BackupError("Missing repository or password file")
    _assert_private(Path(conf["RESTIC_PASSWORD_FILE"]))
    # No shell expansion or implicit restic password from environment.
    env = {k: v for k, v in os.environ.items() if k in (
        "HOME", "PATH", "USER", "XDG_RUNTIME_DIR", "LANG", "SSL_CERT_FILE",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")}
    env.update(conf)
    env["RESTIC_CACHE_DIR"] = str(STATE_DIR / "cache")
    return env


def _run(args, timeout=900, max_output=80_000):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout,
                                check=False, env=_restic_env())
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("Backup tool unavailable or timed out")
    if result.returncode:
        raise BackupError("Backup tool failed (exit " + str(result.returncode) + ")")
    return result.stdout[:max_output].decode("utf-8", "replace")


def _load_jobs():
    try:
        if JOBS.exists():
            return json.loads(JOBS.read_text(encoding="utf-8"))[-30:]
    except (ValueError, OSError):
        pass
    return []


def _record(job):
    _secure_dir(STATE_DIR)
    jobs = [j for j in _load_jobs() if j["id"] != job["id"]]
    jobs.append(job)
    tmp = STATE_DIR / ("jobs." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(jobs[-30:], ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(JOBS)


def jobs():
    return list(reversed(_load_jobs()))


def inventory():
    """Discovery only: never automatically include discovered resources in backups."""
    results = {"postgres": [], "volumes": [], "error": None}
    try:
        d = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"],
                           capture_output=True, timeout=12, check=False)
        if d.returncode:
            raise BackupError("Docker unavailable")
        for line in d.stdout.decode("utf-8", "replace").splitlines()[:300]:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            image = str(row.get("Image", "")).lower()
            name = str(row.get("Names", ""))
            if NAME_RE.fullmatch(name) and any(x in image for x in (
                    "postgres", "postgis", "timescaledb")):
                results["postgres"].append({
                    "name": name, "running": row.get("State") == "running"})
        v = subprocess.run(["docker", "volume", "ls", "--format", "{{json .}}"],
                           capture_output=True, timeout=12, check=False)
        if v.returncode:
            raise BackupError("Volumes unavailable")
        for line in v.stdout.decode("utf-8", "replace").splitlines()[:300]:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if NAME_RE.fullmatch(str(row.get("Name", ""))):
                results["volumes"].append(str(row["Name"]))
    except (OSError, subprocess.TimeoutExpired, BackupError):
        results["error"] = "Docker inventory unavailable"
    return results


def status():
    conf, err = settings()
    try:
        schedule = subprocess.run(
            ["systemctl", "--user", "is-enabled", "homelabos-backup.timer"],
            capture_output=True, timeout=3, check=False)
        scheduled = schedule.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        scheduled = False
    return {
        "configured": conf is not None, "error": err,
        "sources": conf["sources"] if conf else [],
        "retention": conf["retention"] if conf else {},
        "scheduled": scheduled,
        "active_job": _ACTIVE,
        "jobs": jobs(),
        "inventory": inventory(),
        "restore_mode": "staging-only",
    }


def snapshots():
    conf, error = settings()
    if error:
        raise BackupError(error)
    output = _run(["restic", "snapshots", "--tag", "homelabos", "--json"], timeout=45)
    try:
        rows = json.loads(output)
    except ValueError:
        raise BackupError("Invalid snapshot response")
    return [{"id": x.get("id"), "time": x.get("time"), "hostname": x.get("hostname"),
             "paths": len(x.get("paths", []))}
            for x in rows[-60:] if isinstance(x.get("id"), str) and
            SNAPSHOT_RE.fullmatch(x["id"])][::-1]


def _take_lock():
    _secure_dir(STATE_DIR)
    handle = open(LOCK, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise BackupError("Another backup or restore operation is already in progress")
    return handle


def _stage():
    _secure_dir(STATE_DIR)
    base = STATE_DIR / "work"
    _secure_dir(base)
    if shutil.disk_usage(base).free < 1_000_000_000:
        raise BackupError("Less than 1 GB free for temporary backup data")
    path = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    path.chmod(0o700)
    return path


def _pg_dump(name, target):
    if not NAME_RE.fullmatch(name):
        raise BackupError("Invalid PostgreSQL target")
    # pg_dumpall uses the container's local Unix socket; no passwords exposed.
    with target.open("wb") as out:
        try:
            result = subprocess.run(
                ["docker", "exec", "-u", "postgres", name,
                 "pg_dumpall", "-U", "postgres", "--no-role-passwords"],
                stdout=out, stderr=subprocess.PIPE, check=False, timeout=900)
        except (OSError, subprocess.TimeoutExpired):
            raise BackupError("PostgreSQL dump failed or timed out: " + name)
    if result.returncode or target.stat().st_size == 0:
        raise BackupError("PostgreSQL dump unavailable: " + name)


def _volume(name, target, utility_image):
    if not NAME_RE.fullmatch(name):
        raise BackupError("Invalid Docker volume name")
    with target.open("wb") as out:
        try:
            # Read-only volume, no network, no capabilities, no image downloads.
            result = subprocess.run([
                "docker", "run", "--rm", "--pull=never", "--network=none",
                "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--mount", f"type=volume,source={name},target=/source,readonly",
                utility_image, "tar", "-C", "/source", "-cf", "-", "."],
                stdout=out, stderr=subprocess.PIPE, timeout=1200, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise BackupError("Volume export unavailable: " + name)
    if result.returncode:
        raise BackupError("Volume export failed; confirm busybox:1.36 is installed locally: " + name)


def _safe_archive(path):
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive:
                p = Path(member.name)
                if p.is_absolute() or ".." in p.parts or member.isdev() or (
                    member.issym() or member.islnk()):
                    raise BackupError("Unsafe tar content; refusing recovery")
    except tarfile.TarError:
        raise BackupError("Volume archive is corrupted")


def _prepare_stage(stage, conf):
    src = stage / "homelabos"
    _secure_dir(src)
    manifest = {"created_at": int(time.time()), "resources": []}
    repo_root = Path(__file__).resolve().parent.parent
    for item in conf["sources"]:
        name = item["name"]
        kind = item["type"]
        if kind == "homelab":
            db = repo_root / "data/homelabos.db"
            if not db.is_file():
                raise BackupError("HomeLab SQLite database not present")
            dest = src / "homelabos.db"
            with sqlite3.connect(str(db)) as conn, sqlite3.connect(str(dest)) as backup:
                conn.backup(backup)
            safe_config = src / "configuration"
            _secure_dir(safe_config)
            for filename in ("services.json", "tls_endpoints.json"):
                candidate = repo_root / "config" / filename
                if candidate.is_file() and not candidate.is_symlink():
                    shutil.copy2(candidate, safe_config / filename)
            manifest["resources"].append({"type": kind, "name": name,
                                           "file": "homelabos/homelabos.db"})
        elif kind == "postgres":
            dest = src / (name + ".sql")
            _pg_dump(name, dest)
            manifest["resources"].append({"type": kind, "name": name,
                                           "file": "homelabos/" + dest.name})
        elif kind == "volume":
            dest = src / (name + ".tar")
            _volume(name, dest, conf["utility_image"])
            _safe_archive(dest)
            manifest["resources"].append({"type": kind, "name": name,
                                           "file": "homelabos/" + dest.name})
        elif kind == "directory":
            target = Path(item["path"])
            # Copies files for staging without modifying them.
            dest = src / ("directory-" + name)
            shutil.copytree(target, dest, symlinks=True)
            manifest["resources"].append({"type": kind, "name": name,
                                           "file": "homelabos/" + dest.name})
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def backup():
    conf, err = settings()
    if err:
        raise BackupError(err)
    if not conf["sources"]:
        raise BackupError("No backup resources configured")
    with _take_lock():
        stage = _stage()
        try:
            manifest = _prepare_stage(stage, conf)
            _run(["restic", "backup", "--tag", "homelabos",
                  "--tag", "homelabos-v0.5", str(stage)], timeout=3600)
            # Delete only HomeLab-tagged snapshots outside retention policy.
            policy = conf["retention"]
            _run(["restic", "forget", "--tag", "homelabos",
                  "--group-by", "host,tags",
                  "--keep-daily", str(policy["daily"]),
                  "--keep-weekly", str(policy["weekly"]),
                  "--keep-monthly", str(policy["monthly"]),
                  "--prune"], timeout=3600)
            return {"resources": len(manifest["resources"]),
                    "retention_applied": True, "encrypted": True}
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def verify():
    conf, err = settings()
    if err:
        raise BackupError(err)
    with _take_lock():
        _run(["restic", "check", "--read-data"], timeout=3600)
        return {"verified": True, "method": "restic check",
                "note": "Repository structure and references checked; no production data modified"}


def restore(snapshot_id):
    if not SNAPSHOT_RE.fullmatch(snapshot_id):
        raise BackupError("Invalid snapshot id")
    conf, err = settings()
    if err:
        raise BackupError(err)
    with _take_lock():
        matching = {s["id"] for s in snapshots()}
        if snapshot_id not in matching:
            raise BackupError("Snapshot not found among HomeLab OS backups")
        recover_dir = STATE_DIR / "restores"
        _secure_dir(recover_dir)
        destination = recover_dir / (time.strftime("%Y%m%d-%H%M%S") + "-" + snapshot_id[:12])
        if destination.exists():
            raise BackupError("Restore destination already exists")
        _secure_dir(destination)
        try:
            _run(["restic", "restore", snapshot_id, "--target", str(destination)],
                 timeout=3600)
            located = list(destination.rglob("manifest.json"))
            if len(located) != 1:
                raise BackupError("Missing or ambiguous restored manifest")
            manifest = json.loads(located[0].read_text(encoding="utf-8"))
            if not isinstance(manifest.get("resources"), list):
                raise BackupError("Invalid restored manifest")
            for item in manifest["resources"]:
                path = located[0].parent / item["file"]
                if not path.resolve().is_relative_to(destination.resolve()) or not path.exists():
                    raise BackupError("Restored resource missing or unsafe")
                if item["type"] == "homelab":
                    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                        result = db.execute("PRAGMA integrity_check").fetchone()[0]
                        if result != "ok":
                            raise BackupError("Restored SQLite integrity check failed")
                if item["type"] == "volume":
                    _safe_archive(path)
            return {"snapshot": snapshot_id, "destination": str(destination),
                    "restored_root": str(located[0].parent),
                    "resources": len(manifest["resources"]),
                    "live_data_modified": False,
                    "next_step": "Review the restored files and follow docs/RECOVERY.md for manual cutover"}
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise


def _perform(job_id, operation, snapshot_id=None):
    global _ACTIVE
    job = _RUNNING[job_id]
    job.update(state="running", started=int(time.time()))
    _record(job)
    try:
        result = {"backup": backup, "verify": verify,
                  "restore": lambda: restore(snapshot_id)}[operation]()
        job.update(state="success", result=result)
    except Exception as exc:
        job.update(state="failed", error=str(exc)[:240])
    finally:
        job["finished"] = int(time.time())
        _record(job)
        with _ACTIVE_LOCK:
            _ACTIVE = None


def start(operation, confirmation, snapshot_id=None, background=True):
    global _ACTIVE
    if operation not in ("backup", "verify", "restore"):
        raise ValueError("Invalid operation")
    phrase = ("EJECUTAR RESPALDO" if operation == "backup" else
              "VERIFICAR RESPALDOS" if operation == "verify" else
              f"RESTAURAR {snapshot_id}")
    if confirmation != phrase:
        raise PermissionError("Typed confirmation required")
    if operation == "restore" and (not snapshot_id or not SNAPSHOT_RE.fullmatch(snapshot_id)):
        raise ValueError("Invalid restore snapshot")
    with _ACTIVE_LOCK:
        if _ACTIVE:
            raise BackupError("Another backup task is active")
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "operation": operation, "state": "queued",
               "created": int(time.time()), "snapshot": snapshot_id}
        _RUNNING[job_id] = job
        _ACTIVE = job_id
    _record(job)
    if background:
        threading.Thread(target=_perform, args=(job_id,operation,snapshot_id),
                         daemon=True).start()
    else:
        _perform(job_id,operation,snapshot_id)
    return job


def cron():
    # Systemd user timer calls the same lock-protected operation.
    job = start("backup", "EJECUTAR RESPALDO", background=False)
    if job["state"] != "success":
        raise BackupError(job.get("error", "Backup failed"))
    return job


if __name__ == "__main__":
    cron()
