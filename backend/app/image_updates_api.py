"""Authenticated, explicit Docker image download workflow; production stays running."""
import re
from urllib.parse import quote
import httpx
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field

NAME=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
DIGEST=re.compile(r"sha256:[a-f0-9]{64}\Z")

class ImagePullApproval(BaseModel):
    confirm:bool
    confirmation_text:str=Field(max_length=160)
    running_image_id:str=Field(max_length=71)

def make_router(current_user,csrf_user,relay,store):
    router=APIRouter(prefix="/api/image-updates",tags=["image-updates"])
    async def call(method,path,body=None,timeout=35):
        try:
            if body is not None:
                return await relay(method,path,body=body,timeout=timeout)
            return await relay(method,path,timeout=timeout)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403,409,422):
                raise HTTPException(exc.response.status_code,
                    {403:"Contenedor no autorizado en HOMELAB_ALLOWED_CONTAINERS",
                     409:"Ya existe una descarga o Docker no está disponible",
                     422:"Imagen o contenedor no compatible"}[exc.response.status_code])
            raise HTTPException(502,"El agente no pudo completar la operación")
        except (httpx.HTTPError,RuntimeError,ValueError):
            raise HTTPException(503,"Agente Fedora no disponible")

    @router.get("/jobs")
    async def jobs(user=Depends(current_user)):
        return await call("GET","/v1/docker/image-updates/jobs")

    @router.get("/{name}/preview")
    async def preview(name:str,user=Depends(current_user)):
        if not NAME.fullmatch(name):
            raise HTTPException(422,"Nombre no válido")
        return await call("GET",f"/v1/docker/image-updates/{quote(name,safe='')}/preview")

    @router.post("/{name}/pull")
    async def pull(name:str,body:ImagePullApproval,user=Depends(csrf_user)):
        if not NAME.fullmatch(name) or not DIGEST.fullmatch(body.running_image_id):
            raise HTTPException(422,"Identificador inválido")
        if not body.confirm or body.confirmation_text!="DESCARGAR IMAGEN "+name:
            raise HTTPException(403,"Confirmación escrita obligatoria")
        try:
            result=await call("POST",f"/v1/docker/image-updates/{quote(name,safe='')}/pull",{
                "confirmation_text":body.confirmation_text,
                "running_image_id":body.running_image_id})
        except HTTPException:
            store.log(user["username"],"docker_image_pull",name,"failed")
            raise
        store.log(user["username"],"docker_image_pull",name,"accepted")
        return result
    return router
