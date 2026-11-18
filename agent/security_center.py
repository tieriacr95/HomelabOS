"""Read-only Fedora Security Center collector.

Fixed command vectors, no shell, no privileged operations, no raw authentication
logs, passwords, SSH identities, keys, or environment variables in API output.
Unknown/inaccessible checks are explicitly marked unavailable.
"""
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import psutil

MAX_PORTS = 200
MAX_ZONES = 12
SSH_KEYS = ("permitrootlogin", "passwordauthentication", "pubkeyauthentication",
            "permitemptypasswords", "maxauthtries", "port", "x11forwarding")
RISK_PORTS = {
    2375: ("Docker API sin TLS", "critical"),
    5432: ("PostgreSQL", "medium"),
    3306: ("MySQL/MariaDB", "medium"),
    6379: ("Redis", "medium"),
    27017: ("MongoDB", "medium"),
    9200: ("Elasticsearch", "medium"),
    11211: ("Memcached", "medium"),
    5900: ("VNC", "medium"),
}


def run(*argv, timeout=6, max_bytes=120_000):
    """Run only fixed command vectors, with bounded output and timeout."""
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout,
                              check=False, env={**os.environ, "LC_ALL": "C"})
        return (done.returncode, done.stdout[:max_bytes].decode("utf-8", "replace"),
                done.stderr[:2000].decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", "Command unavailable or timed out"


def _line(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()[:80]
    except OSError:
        return None


def selinux_status():
    rc, mode, _ = run("getenforce", timeout=3)
    value = mode.strip().lower() if rc == 0 else ""
    if value not in ("enforcing", "permissive", "disabled"):
        kernel = _line("/sys/fs/selinux/enforce")
        value = {"1": "enforcing", "0": "permissive"}.get(kernel, "unknown")
    configured = None
    config = _line("/etc/selinux/config")
    if config:
        # File may contain comments and blank lines; _line is not sufficient.
        try:
            raw = Path("/etc/selinux/config").read_text(encoding="utf-8")[:10000]
            match = re.search(r"(?im)^\s*SELINUX\s*=\s*(enforcing|permissive|disabled)\s*(?:#.*)?$", raw)
            configured = match.group(1).lower() if match else None
        except OSError:
            pass
    return {"mode": value, "configured": configured,
            "available": value != "unknown", "source": "getenforce / sysfs"}


def _service_active(name):
    rc, output, _ = run("systemctl", "is-active", name, timeout=3)
    status = output.strip()
    if status in ("active", "inactive", "failed", "activating", "deactivating"):
        return status
    return "unknown"


def firewall_status():
    service = _service_active("firewalld")
    if not shutil.which("firewall-cmd"):
        return {"available": False, "service": service, "state": "unknown",
                "zones": [], "error": "firewall-cmd no disponible"}
    rc, output, _ = run("firewall-cmd", "--state", timeout=4)
    if rc != 0 or output.strip() != "running":
        return {"available": True, "service": service, "state": "not-running",
                "zones": [], "error": None}
    rc, raw, _ = run("firewall-cmd", "--get-active-zones", timeout=5)
    if rc != 0:
        return {"available": True, "service": service, "state": "running",
                "zones": [], "error": "No se pudieron consultar zonas activas"}
    zones = []
    for line in raw.splitlines():
        if line and not line.startswith((" ", "\t")):
            name = line.strip()
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
                continue
            zones.append({"name": name, "interfaces": [], "sources": [],
                          "services": [], "ports": []})
        elif zones:
            key, _, values = line.strip().partition(":")
            if key in ("interfaces", "sources"):
                zones[-1][key] = values.split()[:32]
    for zone in zones[:MAX_ZONES]:
        for field, option in (("services", "--list-services"), ("ports", "--list-ports")):
            rc, raw, _ = run("firewall-cmd", "--zone", zone["name"], option, timeout=5)
            zone[field] = raw.split()[:70] if rc == 0 else []
    return {"available": True, "service": service, "state": "running",
            "zones": zones[:MAX_ZONES], "error": None,
            "note": "Los servicios y puertos reflejan firewalld, no todas las reglas de nftables o Docker"}


def ssh_status():
    service = _service_active("sshd")
    binary = shutil.which("sshd") or ("/usr/sbin/sshd" if Path("/usr/sbin/sshd").exists() else None)
    if not binary:
        return {"service": service, "available": False, "effective": {},
                "error": "sshd no disponible"}
    # -T tests a sample connection. Match blocks for other clients may differ.
    rc, raw, _ = run(binary, "-T", "-C", "user=root,host=localhost,addr=127.0.0.1",
                     timeout=6, max_bytes=50_000)
    if rc:
        return {"service": service, "available": False, "effective": {},
                "error": "No se pudo leer la configuración efectiva de sshd"}
    config = {}
    for line in raw.splitlines():
        key, _, value = line.partition(" ")
        if key in SSH_KEYS:
            config[key] = value.strip().lower()[:80]
    return {"service": service, "available": bool(config), "effective": config,
            "sample": "root@localhost (Match puede variar por origen)",
            "error": None if config else "Configuración de SSH incompleta"}


def _scope(address):
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if ip.is_loopback:
            return "loopback"
        return "all" if ip.is_unspecified else "interface"
    except ValueError:
        return "unknown"


def open_ports():
    try:
        connections = psutil.net_connections(kind="inet")
    except (OSError, psutil.AccessDenied):
        return {"available": False, "error": "Sin permisos para consultar sockets",
                "items": [], "total": None, "non_loopback": None}
    entries = {}
    for conn in connections:
        if not conn.laddr:
            continue
        if conn.type == socket.SOCK_STREAM and conn.status != psutil.CONN_LISTEN:
            continue
        if conn.type not in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            continue
        addr, port = conn.laddr.ip, conn.laddr.port
        protocol = "tcp" if conn.type == socket.SOCK_STREAM else "udp"
        key = (protocol, addr, port)
        if key in entries:
            continue
        scope = _scope(addr)
        process_name = None
        if conn.pid is not None:
            try:
                process_name = psutil.Process(conn.pid).name()[:80]
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass
        entries[key] = {"protocol": protocol, "address": addr[:80],
                        "port": port, "scope": scope, "process": process_name}
    items = sorted(entries.values(), key=lambda x: (
        x["scope"] == "loopback", x["port"], x["protocol"], x["address"]))
    return {"available": True, "error": None, "items": items[:MAX_PORTS],
            "total": len(items),
            "non_loopback": sum(x["scope"] in ("all", "interface") for x in items),
            "truncated": len(items) > MAX_PORTS,
            "note": "Un socket escuchando no demuestra accesibilidad desde Internet; comprueba firewall y red"}


def auth_events():
    if not shutil.which("journalctl"):
        return {"available": False, "error": "journalctl no disponible",
                "period_hours": 24, "ssh_failed": None, "ssh_accepted": None,
                "sudo_failures": None, "scanned_lines": 0}
    rc, raw, _ = run("journalctl", "--since=-24h", "--no-pager", "-q",
                     "-o", "cat", "-n", "2500",
                     "-t", "sshd", "-t", "sshd-session", "-t", "sudo",
                     timeout=8, max_bytes=240_000)
    if rc != 0:
        return {"available": False,
                "error": "El journal del sistema no es accesible para este usuario",
                "period_hours": 24, "ssh_failed": None,
                "ssh_accepted": None, "sudo_failures": None, "scanned_lines": 0}
    ssh_failed = ssh_accepted = sudo_failures = 0
    lines = raw.splitlines()
    for line in lines:
        lower = line.lower()
        if ("failed password" in lower or "invalid user" in lower or
                "failed publickey" in lower or
                "pam_unix(sshd:auth): authentication failure" in lower):
            ssh_failed += 1
        if "accepted password" in lower or "accepted publickey" in lower:
            ssh_accepted += 1
        if "pam_unix(sudo:auth): authentication failure" in lower:
            sudo_failures += 1
    return {"available": True, "error": None, "period_hours": 24,
            "ssh_failed": ssh_failed, "ssh_accepted": ssh_accepted,
            "sudo_failures": sudo_failures,
            "scanned_lines": len(lines), "truncated": len(lines) >= 2500,
            "note": "Agregados aproximados; no se exponen usuarios, IP ni contenido de logs"}


def kernel_status():
    keys = {
        "aslr": "/proc/sys/kernel/randomize_va_space",
        "protected_hardlinks": "/proc/sys/fs/protected_hardlinks",
        "protected_symlinks": "/proc/sys/fs/protected_symlinks",
        "kptr_restrict": "/proc/sys/kernel/kptr_restrict",
        "dmesg_restrict": "/proc/sys/kernel/dmesg_restrict",
    }
    return {name: _line(path) for name, path in keys.items()}


def analyze(report):
    findings = []
    def add(code, severity, title, detail, recommendation):
        findings.append({"id": code, "severity": severity, "title": title,
                         "detail": detail, "recommendation": recommendation})

    selinux = report["selinux"]
    if selinux["mode"] == "disabled":
        add("selinux-disabled", "high", "SELinux deshabilitado",
            "No se detecta la protección SELinux en ejecución.",
            "Revisa /etc/selinux/config y la política antes de reactivarlo; puede requerir reinicio y reetiquetado.")
    elif selinux["mode"] == "permissive":
        add("selinux-permissive", "high", "SELinux en modo permisivo",
            "SELinux registra violaciones, pero no impone las políticas.",
            "Analiza denegaciones AVC y vuelve a Enforcing cuando los servicios sean compatibles.")
    if selinux["configured"] == "disabled" and selinux["mode"] != "disabled":
        add("selinux-nextboot", "medium", "SELinux deshabilitado en configuración persistente",
            "El estado configurado para siguientes arranques es disabled.",
            "Revisa la configuración persistente antes del siguiente reinicio.")

    fw = report["firewall"]
    if fw["state"] == "not-running":
        add("firewalld-inactive", "medium", "firewalld no está en ejecución",
            "Esta comprobación no determina si nftables u otro firewall está activo.",
            "Verifica la política real de nftables y si firewalld debería ejecutarse.")

    ssh = report["ssh"]
    if ssh["service"] == "active" and ssh["available"]:
        conf = ssh["effective"]
        if conf.get("permitemptypasswords") == "yes":
            add("ssh-empty-passwords", "critical", "SSH permite contraseñas vacías",
                "La configuración consultada permite sesiones con contraseña vacía.",
                "Desactiva PermitEmptyPasswords y valida la configuración con sshd -t antes de recargar.")
        if conf.get("permitrootlogin") == "yes":
            add("ssh-root", "high", "Inicio de sesión SSH de root permitido",
                "El perfil efectivo consultado contiene PermitRootLogin yes.",
                "Prefiere acceso mediante usuario personal y sudo; revisa Match antes de cambiar.")
        if conf.get("passwordauthentication") == "yes":
            add("ssh-passwords", "medium", "SSH permite autenticación por contraseña",
                "SSH puede aceptar contraseñas; es una decisión de política, no una prueba de compromiso.",
                "Considera llaves y MFA; verifica acceso alternativo antes de deshabilitar contraseñas.")
    ports = report["ports"]
    for row in ports["items"]:
        if row["scope"] == "loopback" or row["protocol"] != "tcp":
            continue
        if row["port"] in RISK_PORTS:
            title, severity = RISK_PORTS[row["port"]]
            add("tcp-port-" + str(row["port"]) + "-" + row["address"].replace(":", "_"),
                severity, title + " escucha fuera de loopback",
                f"{row['address']}:{row['port']} está enlazado a una interfaz no loopback. No implica exposición pública.",
                "Revisa la necesidad del enlace, los puertos publicados de Docker y reglas de firewall.")
    auth = report["authentication"]
    if auth["available"] and auth["ssh_failed"] >= 10:
        add("ssh-failed-logins", "medium", "Múltiples fallos de SSH en las últimas 24 horas",
            f"Se detectaron aproximadamente {auth['ssh_failed']} eventos de fallo en el journal accesible.",
            "Revisa registros de autenticación y controles contra fuerza bruta sin bloquear accesos legítimos.")
    kernel = report["kernel"]
    if kernel["aslr"] == "0":
        add("kernel-aslr", "medium", "ASLR desactivado",
            "kernel.randomize_va_space es 0.",
            "Verifica por qué está desactivado y considera restablecer ASLR según tu política de seguridad.")
    if report["privileged_package_helper"]:
        add("package-helper", "info", "Actualizaciones privilegiadas habilitadas",
            "Está instalado el helper opcional para DNF y Flatpak del sistema.",
            "Protege el acceso al panel y revisa el archivo sudoers correspondiente.")
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return sorted(findings, key=lambda item: (order[item["severity"]], item["id"]))


def report():
    """Collect a bounded security snapshot. Partial data remains explicit."""
    data = {
        "timestamp": int(time.time()),
        "hostname": os.uname().nodename,
        "selinux": selinux_status(),
        "firewall": firewall_status(),
        "ssh": ssh_status(),
        "ports": open_ports(),
        "authentication": auth_events(),
        "kernel": kernel_status(),
        "privileged_package_helper": Path(
            "/usr/local/libexec/homelabos/package-helper").is_file(),
        "read_only": True,
    }
    data["findings"] = analyze(data)
    data["summary"] = {
        "critical": sum(x["severity"] == "critical" for x in data["findings"]),
        "high": sum(x["severity"] == "high" for x in data["findings"]),
        "medium": sum(x["severity"] == "medium" for x in data["findings"]),
        "info": sum(x["severity"] == "info" for x in data["findings"]),
        "visible_ports": data["ports"]["non_loopback"],
        "checks_available": sum([
            data["selinux"]["available"], data["firewall"]["state"] != "unknown",
            data["ssh"]["available"], data["ports"]["available"],
            data["authentication"]["available"]]),
        "checks_total": 5,
    }
    return data

_REPORT_LOCK = threading.Lock()
_REPORT_CACHE = {"at": 0.0, "data": None}


def cached_report(refresh=False):
    with _REPORT_LOCK:
        if not refresh and _REPORT_CACHE["data"] is not None and (
                time.monotonic() - _REPORT_CACHE["at"] < 120):
            return _REPORT_CACHE["data"]
        result = report()
        _REPORT_CACHE.update(at=time.monotonic(), data=result)
        return result
