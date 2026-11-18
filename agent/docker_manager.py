"""Read-only Docker discovery and tightly allowlisted container operations.

The browser/API never touches the Docker socket. This module executes a fixed
set of Docker CLI argument vectors as the host agent's unprivileged user.
"""
import json
import re
import subprocess

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
ACTIONS = frozenset(("start", "stop", "restart"))
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_ITEMS = 400


def valid_name(name):
    return bool(isinstance(name, str) and NAME_RE.fullmatch(name))


def command(*argv, timeout=12, max_output=900_000):
    """Fixed-argument subprocess with bounded stdout/stderr and a timeout."""
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return 124, "", "Docker command timed out"
        return (proc.returncode,
                stdout[:max_output].decode("utf-8", "replace"),
                stderr[:4096].decode("utf-8", "replace"))
    except (OSError, ValueError):
        return 127, "", "Docker command unavailable"


def json_lines(*arguments, timeout=12):
    code, output, error = command("docker", *arguments, timeout=timeout)
    if code:
        return [], (error.strip()[:180] or "Docker no disponible")
    items = []
    for line in output.splitlines()[:MAX_ITEMS]:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                items.append(item)
        except json.JSONDecodeError:
            continue
    return items, None


def compose_labels(names):
    """Retrieve only container labels; never return full inspect/env/mounts."""
    if not names:
        return {}
    labels = {}
    for idx in range(0, len(names), 40):
        batch = names[idx:idx + 40]
        rc, raw, _ = command(
            "docker", "inspect", "--type", "container",
            "--format", "{{json .Config.Labels}}", *batch, timeout=12)
        if rc:
            continue
        for name, line in zip(batch, raw.splitlines()):
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    labels[name] = {
                        "project": str(item.get("com.docker.compose.project") or "")[:128],
                        "service": str(item.get("com.docker.compose.service") or "")[:128],
                    }
            except json.JSONDecodeError:
                pass
    return labels


def inventory(allowed=frozenset()):
    rows, error = json_lines("ps", "-a", "--no-trunc", "--format", "{{json .}}")
    if error:
        return {"connected": False, "error": error,
                "containers": [], "images": [], "volumes": [], "networks": [], "projects": []}
    containers = []
    for row in rows:
        name = str(row.get("Names") or "").lstrip("/")
        if not valid_name(name):
            continue
        containers.append({
            "name": name, "id": str(row.get("ID") or "")[:64],
            "image": str(row.get("Image") or "")[:250],
            "state": str(row.get("State") or "unknown").lower()[:40],
            "status": str(row.get("Status") or "")[:180],
            "ports": str(row.get("Ports") or "")[:400],
            "allowed_actions": list(sorted(ACTIONS)) if name in allowed else [],
            "critical_reason": critical_reason(name, str(row.get("Image") or "")),
        })
    labels = compose_labels([c["name"] for c in containers])
    groups = {}
    for container in containers:
        pair = labels.get(container["name"], {})
        container["project"] = pair.get("project", "")
        container["service"] = pair.get("service", "")
        if container["project"]:
            project = groups.setdefault(container["project"], {
                "name": container["project"], "total": 0,
                "running": 0, "containers": [], "services": [],
            })
            project["total"] += 1
            project["running"] += int(container["state"] == "running")
            project["containers"].append(container["name"])
            if container["service"] and container["service"] not in project["services"]:
                project["services"].append(container["service"])

    images, images_error = json_lines("image", "ls", "--format", "{{json .}}")
    volumes, volumes_error = json_lines("volume", "ls", "--format", "{{json .}}")
    networks, networks_error = json_lines("network", "ls", "--format", "{{json .}}")
    return {
        "connected": True, "error": None,
        "containers": containers,
        "images": [{"id": str(i.get("ID") or "")[:64],
                    "repository": str(i.get("Repository") or "")[:250],
                    "tag": str(i.get("Tag") or "")[:128],
                    "size": str(i.get("Size") or "")[:60],
                    "created": str(i.get("CreatedSince") or "")[:100]} for i in images],
        "volumes": [{"name": str(v.get("Name") or "")[:250],
                     "driver": str(v.get("Driver") or "")[:70]} for v in volumes],
        "networks": [{"id": str(n.get("ID") or "")[:64],
                      "name": str(n.get("Name") or "")[:250],
                      "driver": str(n.get("Driver") or "")[:70],
                      "scope": str(n.get("Scope") or "")[:70]} for n in networks],
        "projects": sorted(groups.values(), key=lambda x: x["name"]),
        "errors": {"images": images_error, "volumes": volumes_error, "networks": networks_error},
    }


def stats():
    rows, error = json_lines("stats", "--no-stream", "--format", "{{json .}}", timeout=18)
    if error:
        return {"items": [], "error": error}
    items = []
    for row in rows:
        name = str(row.get("Name") or "").lstrip("/")
        if not valid_name(name):
            continue
        items.append({
            "name": name, "cpu": str(row.get("CPUPerc") or "0%")[:32],
            "memory": str(row.get("MemUsage") or "")[:85],
            "memory_percent": str(row.get("MemPerc") or "0%")[:32],
            "network": str(row.get("NetIO") or "")[:85],
            "disk_io": str(row.get("BlockIO") or "")[:85],
            "pids": str(row.get("PIDs") or "")[:25],
        })
    return {"items": items, "error": None}


def logs(name, tail=200, since="30m"):
    if not valid_name(name) or not (1 <= tail <= 500) or since not in ("5m", "30m", "1h", "24h", "all"):
        raise ValueError("Invalid container log request")
    args = ["docker", "logs", "--tail", str(tail), "--timestamps"]
    if since != "all":
        args += ["--since", since]
    rc, stdout, stderr = command(*args, name, timeout=12, max_output=220_000)
    if rc:
        return {"error": "No se pudieron consultar los logs", "logs": ""}
    # Docker sends application logs to either stdout or stderr.
    combined = (stdout + "\n" + stderr).strip()
    combined = ANSI.sub("", combined)
    return {"name": name, "logs": combined[-80_000:], "tail": tail, "since": since,
            "truncated": len(combined) > 80_000}


def control(name, action, allowed=frozenset()):
    if not valid_name(name) or action not in ACTIONS or name not in allowed:
        raise PermissionError("Container action not allowlisted")
    # No arbitrary command, image removal, prune, volume deletion or compose down.
    argv = ["docker", action]
    if action in ("stop", "restart"):
        argv += ["--time", "10"]
    rc, _, error = command(*argv, name, timeout=35, max_output=1000)
    if rc:
        return {"ok": False, "error": error.strip()[:180] or "Docker action failed"}
    return {"ok": True, "container": name, "action": action}


# Host-managed group operations: do not read or execute user-supplied compose files.
# Existing containers only; no compose up/down, volume/image deletion or builds.
VERBS = {"start": "INICIAR", "stop": "DETENER", "restart": "REINICIAR"}
CRITICAL_TOKENS = ("postgres", "mariadb", "mysql", "mongo", "redis", "database",
                   "cloudflared", "tunnel", "homelabos", "vaultwarden", "traefik")
CRITICAL_COMPONENTS = frozenset(("db", "database", "database-1", "pg", "pgdata"))


def critical_reason(name, image=""):
    """Conservative server-side guard for services whose loss impacts other apps."""
    lower = (name + " " + image).lower()
    components = re.split(r"[-_.\s/]+", lower)
    if any(token in lower for token in CRITICAL_TOKENS) or any(
            component in CRITICAL_COMPONENTS for component in components):
        return "Servicio crítico: base de datos, túnel, proxy o panel de administración"
    return ""


def project_order(containers, action):
    """Approximate dependencies: databases before APIs, workers and web on start.

    Reversed for stop. This is NOT a substitute for Docker Compose depends_on,
    health checks or a full stack orchestration.
    """
    def priority(c):
        parts = (c.get("service", "") + " " + c["name"]).lower()
        if critical_reason(parts, c.get("image", "")) and any(
                word in parts for word in ("db", "postgres", "mysql", "maria", "redis")):
            return 0
        if "api" in parts or "backend" in parts:
            return 1
        if "worker" in parts:
            return 2
        if "web" in parts or "frontend" in parts:
            return 3
        return 2
    return sorted(containers, key=lambda c: (priority(c), c["name"]),
                  reverse=action == "stop")


def operation_plan(scope, name, action, allowed, snapshot=None):
    if action not in ACTIONS or not valid_name(name) or scope not in ("container", "project"):
        raise ValueError("Invalid Docker operation")
    current = snapshot if snapshot is not None else inventory(allowed)
    if not current["connected"]:
        raise RuntimeError("Docker is unavailable")
    containers = current["containers"]
    if scope == "container":
        selected = [c for c in containers if c["name"] == name]
    else:
        selected = [c for c in containers if c.get("project") == name]
    if not selected:
        raise LookupError("Container or project was not found")
    if len(selected) > 30:
        raise ValueError("Too many containers in project")
    disallowed = [c["name"] for c in selected if c["name"] not in allowed]
    if disallowed:
        raise PermissionError("Not allowlisted: " + ", ".join(disallowed[:5]))
    selected = project_order(selected, action) if scope == "project" else selected
    critical = [c["name"] for c in selected if c.get("critical_reason") or
                critical_reason(c["name"], c.get("image", ""))]
    phrase = (f"{VERBS[action]} PROYECTO {name}" if scope == "project" else
              f"{VERBS[action]} {name}" if critical else "")
    return {
        "scope": scope, "name": name, "action": action,
        "containers": [c["name"] for c in selected],
        "critical": critical, "requires_confirmation": bool(phrase),
        "confirmation_phrase": phrase,
        "warning": ("Las dependencias Compose no se orquestan; se operan contenedores "
                    "existentes individualmente. Se detendrá al primer fallo."
                    if scope == "project" else
                    "Detener o reiniciar este servicio podría afectar otras aplicaciones."),
    }


def execute_plan(plan, allowed, confirmation_text=""):
    # The caller must calculate the plan from a fresh inventory immediately
    # before executing. Never trust a browser-supplied container list.
    expected = plan["confirmation_phrase"]
    if expected and confirmation_text != expected:
        raise PermissionError("Typed confirmation is required")
    done = []
    for name in plan["containers"]:
        if name not in allowed:
            raise PermissionError("Container not on allowlist")
        args = ["docker", plan["action"]]
        if plan["action"] in ("stop", "restart"):
            args += ["--time", "10"]
        rc, _, err = command(*args, name, timeout=35, max_output=1000)
        if rc:
            return {"ok": False, "completed": done, "failed": name,
                    "error": err.strip()[:180] or "Docker operation failed"}
        done.append(name)
    return {"ok": True, "completed": done, "scope": plan["scope"],
            "name": plan["name"], "action": plan["action"]}
