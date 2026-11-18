"""Read-only TLS endpoint certificate inventory from owner-controlled configuration.

No browser-provided URLs, no arbitrary certificate reissuance or private key
access. Connections are bounded and certificates are checked for trust and expiry.
"""
import concurrent.futures
import json
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509

MAX_HOSTS = 24


def load_targets(services_path, tls_path):
    data = []
    try:
        services = json.loads(Path(services_path).read_text(encoding="utf-8"))
        for item in services:
            if not isinstance(item, dict) or not item.get("enabled", True):
                continue
            parsed = urlparse(item.get("url", ""))
            if parsed.scheme == "https" and parsed.hostname:
                data.append({"name": str(item.get("name", parsed.hostname))[:70],
                             "host": parsed.hostname, "port": parsed.port or 443})
    except (ValueError, OSError, TypeError):
        pass
    try:
        manual = json.loads(Path(tls_path).read_text(encoding="utf-8"))
        for item in manual:
            if isinstance(item, dict):
                data.append({"name": str(item.get("name") or item.get("host"))[:70],
                             "host": item.get("host"), "port": item.get("port", 443)})
    except (ValueError, OSError, TypeError):
        pass
    result = []
    seen = set()
    for item in data:
        host, port = item["host"], item["port"]
        if not isinstance(host, str) or not (0 < len(host) <= 253):
            continue
        if not all(c.isascii() and (c.isalnum() or c in ".-:") for c in host):
            continue
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            continue
        if (host, port) in seen:
            continue
        seen.add((host, port))
        result.append(item)
        if len(result) >= MAX_HOSTS:
            break
    return result


def inspect_one(item):
    host, port = item["host"], item["port"]
    result = {"name": item["name"], "host": host, "port": port, "available": False,
              "trusted": False, "days_remaining": None, "expires_at": None,
              "issuer": None, "subject": None, "error": None}
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=4) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as connection:
                connection.settimeout(4)
                binary = connection.getpeercert(binary_form=True)
        if not binary:
            raise ValueError("El servidor no entregó un certificado")
        cert = x509.load_der_x509_certificate(binary)
        expires = cert.not_valid_after_utc
        result["available"] = True
        result["expires_at"] = expires.isoformat()
        result["days_remaining"] = (expires - datetime.now(timezone.utc)).days
        result["subject"] = cert.subject.rfc4514_string()[:180]
        result["issuer"] = cert.issuer.rfc4514_string()[:180]
        try:
            verified = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=4) as raw:
                with verified.wrap_socket(raw, server_hostname=host) as connection:
                    connection.settimeout(4)
                    connection.getpeercert()
            result["trusted"] = True
        except (ssl.SSLError, OSError):
            result["trusted"] = False
        return result
    except (ssl.SSLError, OSError, ValueError) as exc:
        result["error"] = "No fue posible consultar el certificado TLS"
        return result


def report(services_path, tls_path):
    targets = load_targets(services_path, tls_path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(inspect_one, targets))
    return {"items": items, "configured": len(targets),
            "critical": sum(x["days_remaining"] is not None and x["days_remaining"] <= 7 for x in items),
            "warning": sum(x["days_remaining"] is not None and 7 < x["days_remaining"] <= 30 for x in items),
            "note": "Los certificados HTTPS se consultan, no se emiten ni renuevan."}
