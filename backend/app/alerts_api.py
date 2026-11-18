"""Session-protected alerting API with CSRF and change auditing."""
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


# Only controlled identifiers are translated. Never forward a raw agent error,
# HTTP exception text or Telegram URL (which includes the secret bot token).
SAFE_ERRORS = {
    "telegram_credentials_missing": "Telegram no está configurado. Ejecuta python3 scripts/alerts_setup.py --telegram.",
    "telegram_credentials_invalid": "El archivo de credenciales Telegram es inválido o tiene permisos inseguros.",
    "telegram_credentials_unreadable": "El agente no puede leer las credenciales Telegram; verifica permisos y reinicia el servicio.",
    "telegram_invalid_token": "Telegram rechazó el token del bot (401/404). Reconfigúralo en Fedora con --replace.",
    "telegram_bad_request": "Telegram rechazó la solicitud (400). Revisa el ID del chat y abre una conversación con el bot antes de probar.",
    "telegram_chat_forbidden": "Telegram denegó enviar al chat (403). Inicia el bot con /start o comprueba que esté agregado al grupo.",
    "telegram_target_is_bot": "El chat ID corresponde a una cuenta de bot. Telegram no permite mensajes de bot a bot: usa el chat ID personal o de un grupo donde esté agregado.",
    "telegram_conflict": "Telegram notificó un conflicto (409). Revisa el estado del bot.",
    "telegram_rate_limited": "Telegram limitó temporalmente los mensajes (429). Espera antes de repetir la prueba.",
    "telegram_rejected": "Telegram rechazó el envío. Comprueba el bot y su chat.",
    "telegram_http_error": "Telegram devolvió un error HTTP no reconocido.",
    "telegram_network_error": "El agente Fedora no pudo conectar con api.telegram.org. Revisa DNS, conexión, proxy y TLS.",
    "telegram_invalid_response": "Telegram respondió con contenido inesperado. Comprueba la conectividad.",
}

class RulesUpdate(BaseModel):
    rules: dict


class IncidentAction(BaseModel):
    minutes: int = Field(default=0, ge=0, le=10080)


class Confirmation(BaseModel):
    confirm: bool


def make_router(current_user, csrf_user, relay, store):
    router=APIRouter(prefix="/api/alerts",tags=["alerts"])

    async def call(method,path,body=None,timeout=35):
        try:
            if body is None:
                return await relay(method,path,timeout=timeout)
            return await relay(method,path,body=body,timeout=timeout)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403,404,409,413,422):
                detail = "Operación rechazada por el agente"
                if path == "/v1/alerts/telegram/test":
                    try:
                        error = exc.response.json().get("error")
                        if isinstance(error, str):
                            detail = SAFE_ERRORS.get(error, detail)
                    except (ValueError, TypeError, AttributeError):
                        pass
                raise HTTPException(exc.response.status_code, detail)
            raise HTTPException(502,"No fue posible completar la operación")
        except (httpx.HTTPError,RuntimeError,ValueError):
            raise HTTPException(503,"Agente Fedora no disponible")

    @router.get("/status")
    async def status(user=Depends(current_user)):
        return await call("GET","/v1/alerts/status")

    @router.get("/rules")
    async def rules(user=Depends(current_user)):
        return await call("GET","/v1/alerts/rules")

    @router.put("/rules")
    async def put_rules(body:RulesUpdate,user=Depends(csrf_user)):
        try:
            result=await call("POST","/v1/alerts/rules",{"rules":body.rules})
        except HTTPException:
            store.log(user["username"],"alerts_rules","fedora","failed")
            raise
        store.log(user["username"],"alerts_rules","fedora","ok")
        return result

    @router.post("/check")
    async def check(body:Confirmation,user=Depends(csrf_user)):
        if not body.confirm:
            raise HTTPException(400,"Confirmación requerida")
        try:
            result=await call("POST","/v1/alerts/check",{"confirm":True},timeout=90)
        except HTTPException:
            store.log(user["username"],"alerts_check","fedora","failed")
            raise
        store.log(user["username"],"alerts_check","fedora","ok")
        return result

    @router.post("/telegram/test")
    async def telegram_test(body:Confirmation,user=Depends(csrf_user)):
        if not body.confirm:
            raise HTTPException(400,"Confirmación requerida")
        try:
            result=await call("POST","/v1/alerts/telegram/test",{"confirm":True},timeout=20)
        except HTTPException:
            store.log(user["username"],"alerts_telegram_test","telegram","failed")
            raise
        store.log(user["username"],"alerts_telegram_test","telegram","ok")
        return result

    @router.post("/incidents/{incident_id}/{action}")
    async def incident_action(incident_id:int,action:str,body:IncidentAction,
                              user=Depends(csrf_user)):
        if not 0 < incident_id <= 2**31 or action not in (
                "acknowledge","silence","unsilence"):
            raise HTTPException(422,"Acción no válida")
        if action=="silence" and not 5<=body.minutes<=10080:
            raise HTTPException(422,"Silenciamiento entre 5 y 10080 minutos")
        if action!="silence" and body.minutes != 0:
            raise HTTPException(422,"Duración inesperada")
        try:
            result=await call("POST",f"/v1/alerts/incidents/{incident_id}/{action}",
                              {"minutes":body.minutes})
        except HTTPException:
            store.log(user["username"],"alerts_"+action,str(incident_id),"failed")
            raise
        store.log(user["username"],"alerts_"+action,str(incident_id),"ok")
        return result

    return router
