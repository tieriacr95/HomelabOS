"""Authenticated read-only package inventory and audited, confirmed upgrade jobs."""
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

TYPES = {"dnf": "ACTUALIZAR DNF",
         "flatpak-user": "ACTUALIZAR FLATPAK USUARIO",
         "flatpak-system": "ACTUALIZAR FLATPAK SISTEMA"}


class UpgradeApproval(BaseModel):
    confirm: bool
    confirmation_text: str = Field(max_length=100)


def make_router(current_user, csrf_user, relay, store):
    router = APIRouter(prefix="/api/packages", tags=["packages"])

    async def call(method, path, body=None, timeout=110):
        try:
            if body is not None:
                return await relay(method, path, timeout=timeout, body=body)
            return await relay(method, path, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 403:
                raise HTTPException(403, "No autorizado: revisa la confirmación o el helper privilegiado")
            if code == 409:
                raise HTTPException(409, "Ya existe una actualización en ejecución")
            if code == 404:
                raise HTTPException(404, "Trabajo no encontrado")
            raise HTTPException(502, "El agente rechazó la solicitud")
        except (httpx.HTTPError, RuntimeError, ValueError):
            raise HTTPException(503, "Agente Fedora desconectado")

    @router.get("/status")
    async def status(refresh: bool = False, user=Depends(current_user)):
        return await call("GET", "/v1/packages?refresh=" + ("true" if refresh else "false"))

    @router.get("/jobs")
    async def jobs(user=Depends(current_user)):
        return await call("GET", "/v1/packages/jobs")

    @router.get("/jobs/{job_id}")
    async def job(job_id: str, user=Depends(current_user)):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise HTTPException(422, "ID inválido")
        return await call("GET", "/v1/packages/jobs/" + job_id)

    @router.post("/upgrade/{kind}")
    async def upgrade(kind: str, approval: UpgradeApproval, user=Depends(csrf_user)):
        phrase = TYPES.get(kind)
        if phrase is None:
            raise HTTPException(422, "Tipo de actualización inválido")
        if not approval.confirm:
            raise HTTPException(400, "Confirmación requerida")
        if approval.confirmation_text != phrase:
            raise HTTPException(403, "Escribe la frase indicada para autorizar")
        try:
            result = await call("POST", "/v1/packages/upgrade/" + kind,
                                body={"confirmation_text": phrase}, timeout=20)
            store.log(user["username"], "package_upgrade", kind, "accepted")
            return result
        except HTTPException as exc:
            store.log(user["username"], "package_upgrade", kind, "denied_or_failed")
            raise

    return router
