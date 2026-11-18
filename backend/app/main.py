"""HomeLab OS API: local-only UI, session authentication and host-agent proxy."""
import asyncio
import hmac
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store
from .docker_api import make_router
from .package_api import make_router as make_package_router
from .security_api import make_router as make_security_router
from .extras_api import make_router as make_extras_router

AGENT = os.getenv("HOMELAB_AGENT_URL", "http://127.0.0.1:18765").rstrip("/")
AGENT_TOKEN = os.getenv("HOMELAB_AGENT_TOKEN", "")
SETUP_TOKEN = os.getenv("HOMELAB_SETUP_TOKEN", "")
COOKIE_SECURE = os.getenv("HOMELAB_COOKIE_SECURE", "false").lower() == "true"
SERVICES_PATH = Path(os.getenv("HOMELAB_SERVICES_PATH", "/config/services.json"))
FRONTEND = Path(os.getenv("HOMELAB_FRONTEND_DIR", "/app/public"))
COOKIE = "homelabos_session"
ph = PasswordHasher()
failed_logins = {}


async def sample_container_metrics():
    """Collect samples when nobody is viewing the Docker tab."""
    while True:
        await asyncio.sleep(60)
        try:
            stats = await agent_request("GET", "/v1/docker/stats", timeout=25)
            store.record_container_stats(stats)
        except (httpx.HTTPError, RuntimeError, ValueError, OSError):
            pass


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    task = asyncio.create_task(sample_container_metrics())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="HomeLab OS", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class SetupBody(BaseModel):
    setup_token: str
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=12, max_length=256)


class LoginBody(BaseModel):
    username: str
    password: str


class ConfirmBody(BaseModel):
    confirm: bool


def current_user(request: Request):
    user = store.session_user(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Autenticación requerida")
    return user


def csrf_user(request: Request, x_csrf_token: str | None = Header(default=None)):
    user = current_user(request)
    if not x_csrf_token or not hmac.compare_digest(x_csrf_token, user["csrf"]):
        raise HTTPException(403, "Token CSRF inválido")
    return user


def establish_session(response: Response, username: str):
    user = store.find_user(username)
    token, csrf = secrets.token_urlsafe(36), secrets.token_urlsafe(28)
    ttl = 12 * 3600
    store.create_session(user["id"], token, csrf, int(time.time()) + ttl)
    response.set_cookie(COOKIE, token, max_age=ttl, httponly=True,
                        secure=COOKIE_SECURE, samesite="strict", path="/")
    return {"username": username, "csrf": csrf}


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.4.2"}


@app.get("/api/auth/status")
def auth_status(request: Request):
    user = store.session_user(request.cookies.get(COOKIE))
    return {"configured": store.user_count() > 0,
            "authenticated": bool(user),
            "username": user["username"] if user else None,
            "csrf": user["csrf"] if user else None}


@app.post("/api/auth/setup")
def setup(body: SetupBody, response: Response):
    if store.user_count():
        raise HTTPException(409, "La cuenta inicial ya está configurada")
    if not SETUP_TOKEN or not hmac.compare_digest(body.setup_token, SETUP_TOKEN):
        raise HTTPException(403, "Token de instalación incorrecto")
    try:
        store.create_first_user(body.username, ph.hash(body.password))
    except ValueError:
        raise HTTPException(409, "La cuenta inicial ya está configurada")
    store.log(body.username, "setup", "admin", "ok")
    return establish_session(response, body.username)


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    recent = [t for t in failed_logins.get(ip, []) if now - t < 600]
    if len(recent) >= 8:
        raise HTTPException(429, "Demasiados intentos. Intenta más tarde.")
    user = store.find_user(body.username)
    verified = False
    if user:
        try:
            verified = ph.verify(user["password_hash"], body.password)
        except (VerifyMismatchError, VerificationError):
            pass
    if not verified:
        recent.append(now)
        failed_logins[ip] = recent
        raise HTTPException(401, "Credenciales inválidas")
    failed_logins.pop(ip, None)
    store.log(user["username"], "login", "dashboard", "ok")
    return establish_session(response, user["username"])


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, user=Depends(csrf_user)):
    store.remove_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


async def agent_request(method: str, path: str, timeout: float = 9.0, body=None):
    if not AGENT_TOKEN:
        raise RuntimeError("El token del agente no está configurado")
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=2.0)) as client:
        response = await client.request(
            method, AGENT + path, headers={"Authorization": "Bearer " + AGENT_TOKEN}, json=body)
    response.raise_for_status()
    return response.json()


def load_services():
    try:
        items = json.loads(SERVICES_PATH.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            return []
        return [s for s in items if isinstance(s, dict) and s.get("enabled", True)
                and isinstance(s.get("name"), str) and isinstance(s.get("url"), str)][:30]
    except (OSError, ValueError):
        return []


async def probe_one(service):
    name, url = service["name"][:60], service["url"]
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"name": name, "url": url, "online": False, "error": "URL inválida"}
    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
            response = await client.get(url)
        return {"name": name, "url": url, "online": response.status_code < 500,
                "status_code": response.status_code,
                "latency_ms": round((time.monotonic() - start) * 1000)}
    except (httpx.HTTPError, ValueError):
        return {"name": name, "url": url, "online": False, "error": "Sin respuesta"}


def alerts_for(snapshot, probes):
    if not snapshot:
        return [{"level": "critical", "message": "Agente Fedora desconectado"}]
    alerts = []
    if snapshot.get("cpu", {}).get("percent", 0) >= 90:
        alerts.append({"level": "warning", "message": "CPU sobre el 90%"})
    if snapshot.get("memory", {}).get("percent", 0) >= 90:
        alerts.append({"level": "warning", "message": "Memoria sobre el 90%"})
    for disk in snapshot.get("disks", []):
        if disk.get("percent", 0) >= 85:
            alerts.append({"level": "warning", "message": "Disco " + disk["mount"] + " al " + str(disk["percent"]) + "%"})
    for s in probes:
        if not s["online"]:
            alerts.append({"level": "warning", "message": s["name"] + " no responde"})
    return alerts


@app.get("/api/dashboard")
async def dashboard(user=Depends(current_user)):
    snapshot = None
    agent_error = None
    try:
        snapshot = await agent_request("GET", "/v1/snapshot")
        store.add_metric(snapshot)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        agent_error = "No se pudo conectar al agente Fedora"
    services = await asyncio.gather(*(probe_one(s) for s in load_services()))
    return {"agent_online": snapshot is not None, "agent_error": agent_error,
            "host": snapshot, "services": services, "alerts": alerts_for(snapshot, services),
            "timestamp": int(time.time())}


@app.get("/api/history")
def history(hours: int = 24, user=Depends(current_user)):
    if hours not in (1, 6, 24, 168):
        raise HTTPException(422, "Rango no válido")
    return {"items": store.history(hours)}


@app.get("/api/audit")
def audit(user=Depends(current_user)):
    return {"items": store.recent_audit()}


@app.post("/api/containers/{name}/restart")
async def restart_container(name: str, body: ConfirmBody, user=Depends(csrf_user)):
    if not body.confirm:
        raise HTTPException(400, "Se requiere confirmación explícita")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name):
        raise HTTPException(422, "Nombre de contenedor inválido")
    try:
        result = await agent_request("POST", "/v1/containers/" + quote(name, safe="") + "/restart")
    except httpx.HTTPStatusError as exc:
        store.log(user["username"], "restart", name, "denied_or_failed")
        if exc.response.status_code == 403:
            raise HTTPException(403, "Contenedor no autorizado en HOMELAB_ALLOWED_CONTAINERS")
        raise HTTPException(502, "El agente rechazó la operación")
    except (httpx.HTTPError, RuntimeError, ValueError):
        store.log(user["username"], "restart", name, "agent_unavailable")
        raise HTTPException(503, "Agente no disponible")
    store.log(user["username"], "restart", name, "ok")
    return result


app.include_router(make_router(current_user, csrf_user, lambda *args, **kwargs: agent_request(*args, **kwargs), store))
app.include_router(make_package_router(current_user, csrf_user, lambda *args, **kwargs: agent_request(*args, **kwargs), store))
app.include_router(make_security_router(current_user, lambda *args, **kwargs: agent_request(*args, **kwargs), store))
app.include_router(make_extras_router(current_user, csrf_user,
    lambda *args, **kwargs: agent_request(*args, **kwargs), store,
    SERVICES_PATH, Path(os.getenv("HOMELAB_TLS_PATH", "/config/tls_endpoints.json"))))


if (FRONTEND / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    index = FRONTEND / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Frontend todavía no compilado")
    return FileResponse(index)
