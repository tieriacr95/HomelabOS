#!/usr/bin/env python3
"""Unprivileged Fedora host collector, bound to 127.0.0.1 only.

Deliberately no generic shell endpoint, no Docker socket passed into the UI.
Restart is an explicit, name-by-name opt-in via HOMELAB_ALLOWED_CONTAINERS.
"""
import hmac
import json
import os
import re
import socket
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit, parse_qs

if __package__:
    from . import docker_manager, package_manager, security_center, enhancements, backup_manager
else:
    import docker_manager
    import package_manager
    import security_center
    import enhancements
    import backup_manager

import psutil

TOKEN = os.getenv("HOMELAB_AGENT_TOKEN", "")
PORT = int(os.getenv("HOMELAB_AGENT_PORT", "18765"))
ALLOWED = {s.strip() for s in os.getenv("HOMELAB_ALLOWED_CONTAINERS", "").split(",") if s.strip()}
SYSTEMD_ALLOWED = {x.strip() for x in os.getenv("HOMELAB_ALLOWED_SYSTEMD_UNITS", "").split(",") if x.strip()}
SERVICES = ("docker", "sshd", "firewalld", "NetworkManager", "cloudflared")


def run(*args, timeout=5):
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=timeout, check=False)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 127, "", "command not available"


def docker_containers():
    rc, out, err = run("docker", "ps", "-a", "--format", "{{json .}}", timeout=7)
    if rc != 0:
        return [], err[:160] or "Docker no disponible"
    items = []
    for line in out.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        name = entry.get("Names", "").lstrip("/")
        items.append({
            "name": name,
            "image": entry.get("Image", ""),
            "state": entry.get("State", "unknown").lower(),
            "status": entry.get("Status", ""),
            "id": entry.get("ID", ""),
            "ports": entry.get("Ports", ""),
            "restart_allowed": name in ALLOWED,
        })
    return items, None


def host_snapshot():
    cpu_percent = psutil.cpu_percent(interval=0.15)
    memory = psutil.virtual_memory()
    disks = []
    seen = set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({"mount": part.mountpoint, "device": part.device,
                          "fstype": part.fstype, "total": usage.total, "used": usage.used,
                          "free": usage.free, "percent": usage.percent})
        except (PermissionError, OSError):
            continue
    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "username"]):
        try:
            info = proc.info
            rss = info["memory_info"].rss if info["memory_info"] else 0
            processes.append({"pid": info["pid"], "name": info["name"],
                              "user": info["username"], "rss": rss})
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            pass
    processes.sort(key=lambda p: p["rss"], reverse=True)
    statuses = {}
    for service in SERVICES:
        rc, out, _ = run("systemctl", "is-active", service, timeout=2)
        statuses[service] = out if out else ("unknown" if rc == 127 else "inactive")
    _, selinux, _ = run("getenforce", timeout=2)
    containers, docker_error = docker_containers()
    io = psutil.net_io_counters()
    temperatures = []
    try:
        for sensor, values in psutil.sensors_temperatures().items():
            for value in values[:3]:
                if value.current is not None:
                    temperatures.append({"sensor": sensor, "label": value.label or sensor,
                                         "celsius": round(float(value.current), 1)})
    except (AttributeError, OSError):
        pass
    return {
        "hostname": socket.gethostname(),
        "cpu": {"percent": cpu_percent, "cores": psutil.cpu_count(logical=True),
                "load": list(os.getloadavg())},
        "memory": {"total": memory.total, "used": memory.used,
                   "available": memory.available, "percent": memory.percent},
        "disks": disks,
        "processes": processes[:12],
        "services": statuses,
        "selinux": selinux.lower() or "unknown",
        "containers": containers, "docker_error": docker_error,
        "network": {"bytes_sent": io.bytes_sent, "bytes_recv": io.bytes_recv},
        "temperatures": temperatures[:12],
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "timestamp": int(time.time()),
    }


def can_restart(name):
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name)) and name in ALLOWED


class Handler(BaseHTTPRequestHandler):
    server_version = "HomeLabOS-Agent"

    def reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        return bool(TOKEN) and hmac.compare_digest(supplied, "Bearer " + TOKEN)

    def do_GET(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        if self.path == "/v1/snapshot":
            try:
                return self.reply(200, host_snapshot())
            except Exception:
                return self.reply(500, {"error": "collector_error"})
        path = urlsplit(self.path)
        if path.path == "/v1/backup/status":
            return self.reply(200, backup_manager.status())
        if path.path == "/v1/backup/jobs":
            return self.reply(200, {"items": backup_manager.jobs()})
        backup_job = re.fullmatch(r"/v1/backup/jobs/([a-f0-9]{32})", path.path)
        if backup_job:
            for job in backup_manager.jobs():
                if job["id"] == backup_job.group(1):
                    return self.reply(200, job)
            return self.reply(404, {"error": "not_found"})
        if path.path == "/v1/backup/snapshots":
            try:
                return self.reply(200, {"items": backup_manager.snapshots()})
            except backup_manager.BackupError as exc:
                return self.reply(503, {"error": str(exc)[:180]})
        if path.path == "/v1/extras/postgres":
            return self.reply(200, enhancements.postgres_checks())
        if path.path == "/v1/extras/systemd":
            return self.reply(200, enhancements.systemd_units(SYSTEMD_ALLOWED))
        if path.path == "/v1/security/report":
            try:
                refresh = parse_qs(path.query).get("refresh", ["false"])[0] == "true"
                return self.reply(200, security_center.cached_report(refresh))
            except Exception:
                return self.reply(500, {"error": "security_collector_failed"})
        if path.path == "/v1/packages":
            refresh = parse_qs(path.query).get("refresh", ["false"])[0] == "true"
            return self.reply(200, package_manager.inspect(refresh))
        if path.path == "/v1/packages/jobs":
            return self.reply(200, {"items": package_manager.last_jobs()})
        package_job = re.fullmatch(r"/v1/packages/jobs/([a-f0-9]{32})", path.path)
        if package_job:
            try:
                return self.reply(200, package_manager.upgrade_status(package_job.group(1)))
            except LookupError:
                return self.reply(404, {"error": "not_found"})
        if path.path == "/v1/docker/inventory":
            return self.reply(200, docker_manager.inventory(ALLOWED))
        if path.path == "/v1/docker/stats":
            return self.reply(200, docker_manager.stats())
        preview = re.fullmatch(
            r"/v1/docker/plan/(container|project)/([^/]+)/(start|stop|restart)", path.path)
        if preview:
            scope, name, action = preview.groups()
            try:
                plan = docker_manager.operation_plan(scope, unquote(name), action, ALLOWED)
                return self.reply(200, plan)
            except PermissionError:
                return self.reply(403, {"error": "not_allowed"})
            except (ValueError, LookupError):
                return self.reply(422, {"error": "invalid_target"})
            except RuntimeError:
                return self.reply(503, {"error": "docker_unavailable"})

        match = re.fullmatch(r"/v1/docker/containers/([^/]+)/logs", path.path)
        if match:
            name = unquote(match.group(1))
            query = parse_qs(path.query)
            try:
                tail = int(query.get("tail", ["200"])[0])
                since = query.get("since", ["30m"])[0]
                result = docker_manager.logs(name, tail, since)
            except (ValueError, TypeError):
                return self.reply(422, {"error": "invalid_log_request"})
            return self.reply(502 if "error" in result else 200, result)
        return self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        backup = re.fullmatch(r"/v1/backup/(backup|verify|restore)", self.path)
        if backup:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 512:
                    return self.reply(413, {"error": "oversized_body"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                phrase = payload.get("confirmation_text", "")
                snapshot = payload.get("snapshot")
                if not isinstance(phrase, str) or len(phrase) > 130 or (
                    snapshot is not None and not isinstance(snapshot, str)):
                    return self.reply(422, {"error": "bad_parameters"})
                result = backup_manager.start(backup.group(1), phrase, snapshot)
                return self.reply(202, result)
            except PermissionError:
                return self.reply(403, {"error": "explicit_confirmation_required"})
            except (TypeError, ValueError, AttributeError):
                return self.reply(422, {"error": "bad_parameters"})
            except backup_manager.BackupError as exc:
                return self.reply(409, {"error": str(exc)[:180]})
        sysd = re.fullmatch(r"/v1/extras/systemd/(user|system)/([^/]+)/(start|stop|restart)", self.path)
        if sysd:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 512:
                    return self.reply(413, {"error": "oversized_body"})
                payload = json.loads(self.rfile.read(size) or b"{}")
                scope, unit, operation = sysd.groups()
                confirmed = payload.get("confirmation_text", "")
                if not isinstance(confirmed, str) or len(confirmed) > 200:
                    return self.reply(422, {"error": "invalid_confirmation"})
                result = enhancements.systemd_execute(
                    scope, unquote(unit), operation, SYSTEMD_ALLOWED, confirmed)
                return self.reply(200 if result["ok"] else 502, result)
            except PermissionError:
                return self.reply(403, {"error": "systemd_not_allowed"})
            except (ValueError, AttributeError, TypeError):
                return self.reply(422, {"error": "invalid_request"})
        pkg = re.fullmatch(r"/v1/packages/upgrade/(dnf|flatpak-user|flatpak-system)", self.path)
        if pkg:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 512:
                    return self.reply(413, {"error": "oversized_body"})
                payload = json.loads(self.rfile.read(size) or b"{}")
                phrase = payload.get("confirmation_text", "")
                if not isinstance(phrase, str) or len(phrase) > 100:
                    return self.reply(422, {"error": "invalid_confirmation"})
                result = package_manager.start_upgrade(pkg.group(1), phrase)
                return self.reply(202, result)
            except PermissionError:
                return self.reply(403, {"error": "requires_approved_helper_or_phrase"})
            except RuntimeError:
                return self.reply(409, {"error": "upgrade_already_running"})
            except (ValueError, TypeError, AttributeError):
                return self.reply(422, {"error": "invalid_request"})
        transaction = re.fullmatch(
            r"/v1/docker/execute/(container|project)/([^/]+)/(start|stop|restart)", self.path)
        if transaction:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 1024:
                    return self.reply(413, {"error": "oversized_body"})
                payload = json.loads(self.rfile.read(size) or b"{}")
                confirmation = payload.get("confirmation_text", "")
                if not isinstance(confirmation, str) or len(confirmation) > 250:
                    return self.reply(422, {"error": "invalid_confirmation"})
                scope, name, action = transaction.groups()
                plan = docker_manager.operation_plan(scope, unquote(name), action, ALLOWED)
                result = docker_manager.execute_plan(plan, ALLOWED, confirmation)
                return self.reply(200 if result["ok"] else 502, result)
            except PermissionError:
                return self.reply(403, {"error": "not_allowed_or_unconfirmed"})
            except (ValueError, LookupError, TypeError, AttributeError):
                return self.reply(422, {"error": "invalid_target_or_payload"})
            except RuntimeError:
                return self.reply(503, {"error": "docker_unavailable"})
        operation = re.fullmatch(r"/v1/docker/containers/([^/]+)/(start|stop|restart)", self.path)
        if operation:
            name, action = unquote(operation.group(1)), operation.group(2)
            try:
                plan = docker_manager.operation_plan("container", name, action, ALLOWED)
                if plan["requires_confirmation"]:
                    return self.reply(403, {"error": "use_confirmed_endpoint"})
                result = docker_manager.execute_plan(plan, ALLOWED)
            except PermissionError:
                return self.reply(403, {"error": "not_allowed"})
            except (ValueError, LookupError):
                return self.reply(422, {"error": "invalid_target"})
            except RuntimeError:
                return self.reply(503, {"error": "docker_unavailable"})
            return self.reply(200 if result["ok"] else 502, result)
        match = re.fullmatch(r"/v1/containers/([^/]+)/restart", self.path)
        if not match:
            return self.reply(404, {"error": "not_found"})
        name = unquote(match.group(1))
        try:
            plan = docker_manager.operation_plan("container", name, "restart", ALLOWED)
            if plan["requires_confirmation"]:
                return self.reply(403, {"error": "use_confirmed_endpoint"})
            result = docker_manager.execute_plan(plan, ALLOWED)
            return self.reply(200 if result["ok"] else 502, result)
        except PermissionError:
            return self.reply(403, {"error": "not_allowed"})
        except (ValueError, LookupError):
            return self.reply(422, {"error": "invalid_target"})
        except RuntimeError:
            return self.reply(503, {"error": "docker_unavailable"})

    def log_message(self, fmt, *args):
        # Logs omit request headers (including the shared secret).
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    if not TOKEN or len(TOKEN) < 32:
        raise SystemExit("HOMELAB_AGENT_TOKEN must be configured (>=32 chars)")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("HomeLab OS host agent listening on 127.0.0.1:%d" % PORT, flush=True)
    server.serve_forever()
