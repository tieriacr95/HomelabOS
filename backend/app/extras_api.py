"""Monitoring extras API: Postgres readiness, systemd user units, trends, TLS."""
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import tls_monitor


class TypedApproval(BaseModel):
    confirm: bool
    confirmation_text: str = Field(max_length=160)


VALID_UNIT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,127}\.service\Z")
VALID_CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
ACTIONS = frozenset(("start", "stop", "restart"))


def make_router(current_user, csrf_user, relay, store,
                services_path, tls_path):
    router = APIRouter(prefix="/api/extras", tags=["extras"])

    async def call(method, path, body=None, timeout=25):
        try:
            if body is not None:
                return await relay(method, path, body=body, timeout=timeout)
            return await relay(method, path, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (403, 422):
                raise HTTPException(status, "Acción rechazada por la lista de autorización o confirmación")
            raise HTTPException(502, "El agente no pudo realizar la operación")
        except (httpx.HTTPError, RuntimeError, ValueError):
            raise HTTPException(503, "Agente Fedora no disponible")

    @router.get("/postgres")
    async def postgres(user=Depends(current_user)):
        return await call("GET", "/v1/extras/postgres", timeout=40)

    @router.get("/systemd")
    async def systemd(user=Depends(current_user)):
        return await call("GET", "/v1/extras/systemd")

    @router.post("/systemd/{scope}/{unit}/{action}")
    async def systemd_action(scope: str, unit: str, action: str, body: TypedApproval,
                             user=Depends(csrf_user)):
        if scope != "user" or not VALID_UNIT.fullmatch(unit) or action not in ACTIONS:
            raise HTTPException(422, "Solo se permite operar servicios systemd de usuario")
        phrase = action.upper() + " " + unit
        if not body.confirm or body.confirmation_text != phrase:
            raise HTTPException(403, "Escribe la confirmación indicada")
        try:
            result = await call("POST", f"/v1/extras/systemd/user/{quote(unit, safe='')}/{action}",
                                {"confirmation_text": phrase}, timeout=35)
            store.log(user["username"], "systemd_"+action, unit,
                      "ok" if result.get("ok") else "failed")
            return result
        except HTTPException:
            store.log(user["username"], "systemd_"+action, unit, "failed")
            raise

    @router.get("/containers/{name}/history")
    async def history(name: str, hours: int = Query(24), user=Depends(current_user)):
        if not VALID_CONTAINER.fullmatch(name) or hours not in (1,6,24,168,720):
            raise HTTPException(422, "Parámetros de historial inválidos")
        return {"items": store.container_history(name, hours), "hours": hours,
                "container": name}

    @router.get("/tls")
    def tls(user=Depends(current_user)):
        return tls_monitor.report(services_path, tls_path)

    return router
