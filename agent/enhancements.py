"""Host-level extras: PostgreSQL readiness and restricted systemd user services.

All command arguments are determined by this module; never execute arbitrary
systemctl commands or user-supplied shell, scope, or unit files.
"""
import json
import re
import shutil
import subprocess

try:
    from . import docker_manager as docker
except ImportError:
    import docker_manager as docker

UNIT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,127}\.service\Z")
ACTIONS = frozenset(("start", "stop", "restart"))
MAX_UNITS = 200
MAX_PG = 30


def command(*argv, timeout=9, limit=100000):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        return (result.returncode,
                result.stdout[:limit].decode("utf-8", "replace"),
                result.stderr[:2000].decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", "Comando no disponible o excedió el tiempo"


def systemd_units(allowed=frozenset()):
    """Inventory system and user services; only user units are controllable."""
    groups = []
    for scope in ("user", "system"):
        rc, output, error = command("systemctl", "--"+scope, "list-units",
                                     "--type=service", "--all", "--no-legend",
                                     "--plain", "--no-pager", timeout=8)
        if rc:
            groups.append({"scope": scope, "available": False, "error": error[:160],
                           "items": []})
            continue
        items = []
        for line in output.splitlines()[:MAX_UNITS]:
            values = line.strip().lstrip("● ").split(None, 4)
            if len(values) < 4 or not UNIT_RE.fullmatch(values[0]):
                continue
            unit, loaded, active, sub = values[:4]
            items.append({"name": unit, "loaded": loaded[:30], "active": active[:30],
                          "sub": sub[:30], "description": values[4][:160] if len(values)>4 else "",
                          "manageable": scope=="user" and unit in allowed})
        groups.append({"scope": scope, "available": True, "error": None,
                       "items": items})
    return {"groups": groups, "read_only_system": True}


def systemd_plan(scope, unit, action, allowed):
    if scope not in ("user", "system") or not UNIT_RE.fullmatch(unit) or action not in ACTIONS:
        raise ValueError("Operación o unidad systemd inválida")
    if scope != "user" or unit not in allowed:
        raise PermissionError("Solo unidades de usuario autorizadas")
    return {"scope": scope, "unit": unit, "action": action,
            "confirmation_phrase": action.upper()+" "+unit,
            "warning": "La unidad puede controlar un servicio activo. Los servicios del sistema son solo lectura."}


def systemd_execute(scope, unit, action, allowed, typed):
    plan = systemd_plan(scope, unit, action, allowed)
    if typed != plan["confirmation_phrase"]:
        raise PermissionError("Confirmación escrita requerida")
    rc, output, error = command("systemctl", "--user", action, unit, timeout=30)
    return {"ok": rc == 0, "unit": unit, "action": action,
            "error": (error or "Falló systemctl")[:180] if rc else None}


def postgres_checks():
    """Use pg_isready inside PostgreSQL containers. No passwords are retrieved."""
    snap = docker.inventory()
    if not snap["connected"]:
        return {"available": False, "error": snap["error"], "items": []}
    matches = []
    for c in snap["containers"]:
        image = c["image"].lower().split("/")[-1].split(":")[0]
        if not (image == "postgres" or image.startswith("postgres-") or
                image.startswith("postgis") or image.startswith("timescaledb")):
            continue
        name = c["name"]
        if not docker.valid_name(name):
            continue
        row = {"container": name, "project": c["project"],
               "running": c["state"] == "running", "status": "stopped",
               "probe": "pg_isready", "note": None}
        if c["state"] == "running":
            rc, _, err = command("docker", "exec", name, "pg_isready",
                                  "-h", "127.0.0.1", "-p", "5432", "-q",
                                  timeout=7, limit=500)
            if rc == 0:
                row["status"] = "accepting"
            elif rc in (1, 2):
                row["status"] = "rejecting"
            else:
                row["status"] = "unknown"
                row["note"] = "No se pudo ejecutar pg_isready dentro del contenedor"
        matches.append(row)
        if len(matches) >= MAX_PG:
            break
    return {"available": True, "items": matches, "error": None,
            "note": "pg_isready comprueba aceptación de conexiones, no consultas SQL ni integridad de datos"}
