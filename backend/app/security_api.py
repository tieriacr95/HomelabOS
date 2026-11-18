"""Authenticated, read-only Fedora Security Center API."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query


def make_router(current_user, relay, store):
    router = APIRouter(prefix="/api/security", tags=["security"])

    @router.get("/report")
    async def report(refresh: bool = False, user=Depends(current_user)):
        try:
            snapshot = await relay(
                "GET", "/v1/security/report?refresh=" + ("true" if refresh else "false"),
                timeout=65)
        except (httpx.HTTPError, ValueError, RuntimeError):
            raise HTTPException(503, "Agente Fedora no disponible para la auditoría")
        if not isinstance(snapshot, dict) or "summary" not in snapshot:
            raise HTTPException(502, "Respuesta de auditoría no válida")
        store.record_security_scan(snapshot)
        if refresh:
            store.log(user["username"], "security_scan", "fedora", "ok")
        return snapshot

    @router.get("/history")
    async def history(days: int = Query(7, ge=1, le=30), user=Depends(current_user)):
        if days not in (7, 30):
            raise HTTPException(422, "Solo se admiten 7 o 30 días")
        return {"items": store.security_history(days)}

    return router
