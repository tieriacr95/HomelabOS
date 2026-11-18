"""Authenticated Backup & Recovery API. No arbitrary paths/commands from UI."""
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

ID_RE = re.compile(r"[a-f0-9]{8,64}\Z")
OPERATIONS = {"backup": "EJECUTAR RESPALDO", "verify": "VERIFICAR RESPALDOS"}


class BackupAction(BaseModel):
    confirm: bool
    confirmation_text: str = Field(max_length=130)
    snapshot: str | None = Field(default=None, max_length=64)


def make_router(current_user, csrf_user, relay, store):
    router = APIRouter(prefix="/api/backup", tags=["backup"])

    async def relay_call(method, path, payload=None, timeout=50):
        try:
            if payload is not None:
                return await relay(method, path, body=payload, timeout=timeout)
            return await relay(method, path, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (403, 404, 409, 422):
                raise HTTPException(status, "Operación rechazada por el agente: verifica la configuración, selección o confirmación")
            raise HTTPException(503, "Agente Fedora no pudo completar la solicitud")
        except (httpx.HTTPError, RuntimeError, ValueError):
            raise HTTPException(503, "Agente Fedora no disponible")

    @router.get("/status")
    async def status(user=Depends(current_user)):
        return await relay_call("GET", "/v1/backup/status")

    @router.get("/snapshots")
    async def snapshots(user=Depends(current_user)):
        return await relay_call("GET", "/v1/backup/snapshots")

    @router.get("/jobs")
    async def jobs(user=Depends(current_user)):
        return await relay_call("GET", "/v1/backup/jobs")

    @router.get("/jobs/{job_id}")
    async def job(job_id: str, user=Depends(current_user)):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise HTTPException(422, "Identificador inválido")
        return await relay_call("GET", "/v1/backup/jobs/" + job_id)

    @router.post("/{operation}")
    async def execute(operation: str, approval: BackupAction, user=Depends(csrf_user)):
        if operation not in ("backup", "verify", "restore"):
            raise HTTPException(422, "Acción no permitida")
        if not approval.confirm:
            raise HTTPException(400, "Se requiere confirmación")
        if operation == "restore":
            if not approval.snapshot or not ID_RE.fullmatch(approval.snapshot):
                raise HTTPException(422, "Snapshot inválido")
            phrase = "RESTAURAR " + approval.snapshot
        else:
            if approval.snapshot is not None:
                raise HTTPException(422, "No se espera snapshot")
            phrase = OPERATIONS[operation]
        if approval.confirmation_text != phrase:
            raise HTTPException(403, "Debes escribir la frase de aprobación exacta")
        try:
            result = await relay_call("POST", "/v1/backup/" + operation,
                                      {"confirmation_text": phrase,
                                       "snapshot": approval.snapshot}, timeout=20)
        except HTTPException as exc:
            store.log(user["username"], "backup_" + operation,
                      approval.snapshot or "homelabos", "failed_or_denied")
            raise
        store.log(user["username"], "backup_" + operation,
                  approval.snapshot or "homelabos", "accepted")
        return result

    return router
