"""Authenticated Docker Manager API. All Docker commands run in the host agent."""
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

VALID_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
ACTIONS = frozenset(("start", "stop", "restart"))


class ConfirmAction(BaseModel):
    confirm: bool


def require_name(name):
    if not VALID_NAME.fullmatch(name):
        raise HTTPException(422, "Nombre de contenedor inválido")
    return quote(name, safe="")


def make_router(current_user, csrf_user, relay, store):
    router = APIRouter(prefix="/api/docker", tags=["docker"])

    async def call(method, path, timeout=25):
        try:
            return await relay(method, path, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 403:
                raise HTTPException(403, "Acción no autorizada por el agente")
            if status == 422:
                raise HTTPException(422, "Parámetros inválidos")
            raise HTTPException(502, "Docker no pudo completar la solicitud")
        except (httpx.HTTPError, RuntimeError, ValueError):
            raise HTTPException(503, "Agente Fedora no disponible")

    @router.get("/inventory")
    async def inventory(user=Depends(current_user)):
        return await call("GET", "/v1/docker/inventory")

    @router.get("/stats")
    async def stats(user=Depends(current_user)):
        return await call("GET", "/v1/docker/stats")

    @router.get("/containers/{name}/logs")
    async def logs(name: str,
                   tail: int = Query(200, ge=1, le=500),
                   since: str = Query("30m", pattern=r"^(5m|30m|1h|24h|all)$"),
                   user=Depends(current_user)):
        encoded = require_name(name)
        return await call("GET",
                          f"/v1/docker/containers/{encoded}/logs?tail={tail}&since={since}")

    @router.post("/containers/{name}/{action}")
    async def control(name: str, action: str, body: ConfirmAction, user=Depends(csrf_user)):
        encoded = require_name(name)
        if action not in ACTIONS:
            raise HTTPException(422, "Operación no permitida")
        if not body.confirm:
            raise HTTPException(400, "Debes confirmar la operación")
        try:
            result = await call("POST", f"/v1/docker/containers/{encoded}/{action}", timeout=45)
        except HTTPException as exc:
            store.log(user["username"], action, name, "denied" if exc.status_code == 403 else "failed")
            raise
        store.log(user["username"], action, name, "ok" if result.get("ok") else "failed")
        if not result.get("ok"):
            raise HTTPException(502, "Docker no pudo completar la operación")
        return result

    return router
