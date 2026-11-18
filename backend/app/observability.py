"""Bounded, read-only cross-service health and inferred dependency topology."""
import asyncio
import time
from collections import defaultdict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query


def topology(inventory, postgres):
    """Only factual Compose memberships; heuristic links explicitly labeled inferred."""
    containers=inventory.get("containers",[])[:200]
    nodes=[]
    links=[]
    projects={}
    postgres_names={x.get("container"):x.get("status") for x in postgres.get("items",[])}
    for p in inventory.get("projects",[])[:70]:
        if not p.get("name"):
            continue
        key="project:"+p["name"]
        projects[p["name"]]=key
        nodes.append({"id":key,"label":p["name"],"type":"project",
                      "state":"healthy" if p.get("total")==p.get("running") else "degraded"})
    for c in containers:
        name=c.get("name","")
        if not name:
            continue
        health=postgres_names.get(name)
        state=("degraded" if health and health!="accepting" else
               "healthy" if c.get("state")=="running" else "down")
        key="container:"+name
        nodes.append({"id":key,"label":name,"type":"container","state":state,
                      "image":c.get("image",""),"project":c.get("project","")})
        if c.get("project") in projects:
            links.append({"source":projects[c["project"]],"target":key,
                          "type":"membership","inferred":False})
    # Heuristic service dependencies are only informational; not used to
    # determine orchestration or authorize actions.
    by_project=defaultdict(list)
    for c in containers:
        if c.get("project"):
            by_project[c["project"]].append(c)
    for members in by_project.values():
        db=[c for c in members if any(x in (c.get("service","")+" "+c["name"]).lower()
                                 for x in ("postgres","database","-db","redis"))]
        apis=[c for c in members if any(x in (c.get("service","")+" "+c["name"]).lower()
                                      for x in ("api","web","worker","frontend"))]
        for source in db[:5]:
            for destination in apis[:15]:
                if source["name"]!=destination["name"]:
                    links.append({"source":"container:"+source["name"],
                                  "target":"container:"+destination["name"],
                                  "type":"possible_dependency","inferred":True})
    return {"nodes":nodes,"links":links,
            "note":"Las líneas continuas representan pertenencia Compose verificada; las dependencias entre servicios son estimaciones, no pruebas ni planes de ejecución."}


def build_health(snapshot, inventory, postgres, alerts, backups):
    known=0
    failures=[]
    if not snapshot:
        failures.append({"type":"agent","title":"Agente Fedora desconectado","severity":"critical"})
    else:
        known+=1
        disk=max((float(x.get("percent",0)) for x in snapshot.get("disks",[])),default=0)
        for category,value,threshold in (
            ("CPU",snapshot.get("cpu",{}).get("percent",0),95),
            ("RAM",snapshot.get("memory",{}).get("percent",0),95),
            ("Disco",disk,90)):
            known+=1
            if value>=threshold:
                failures.append({"type":category,"title":f"{category} al {value:.1f}%",
                                 "severity":"warning"})
    if inventory.get("connected"):
        known+=1
        for c in inventory.get("containers",[]):
            if c.get("state")!="running":
                # Informational only; stopped containers may be intentional.
                continue
    else:
        failures.append({"type":"docker","title":"Inventario Docker no disponible",
                         "severity":"warning"})
    if postgres.get("available"):
        for item in postgres.get("items",[]):
            known+=1
            if item.get("status") in ("stopped","rejecting"):
                failures.append({"type":"postgres","title":"PostgreSQL: "+item["container"],
                                 "severity":"critical"})
    for inc in alerts.get("incidents",[]):
        failures.append({"type":"incident","title":inc.get("title","Incidencia")[:180],
                         "severity":inc.get("severity","warning")})
    if backups.get("configured"):
        last=next((job for job in backups.get("jobs",[])
                   if job.get("operation")=="backup" and job.get("state")=="success"),None)
        known+=1
        if not last or time.time()-int(last.get("finished") or last.get("created") or 0)>36*3600:
            failures.append({"type":"backup","title":"No hay respaldo reciente verificado como exitoso",
                             "severity":"warning"})
    health=("unknown" if not snapshot else
            "critical" if any(x["severity"]=="critical" for x in failures) else
            "degraded" if failures else "healthy")
    return {"status":health,"verified_sources":known,"findings":failures[:60],
            "notes":"El estado global no reemplaza las pruebas de restauración. Los contenedores detenidos no se consideran incidentes a menos que una regla los espere."}


def make_router(user, relay, store):
    router=APIRouter(prefix="/api/observability",tags=["observability"])

    async def safe(path,timeout=20):
        try:
            return await relay("GET",path,timeout=timeout)
        except (httpx.HTTPError,ValueError,RuntimeError,OSError):
            return {}

    @router.get("/overview")
    async def overview(actor=Depends(user)):
        snap,inv,pg,alerts,backups=await asyncio.gather(
            safe("/v1/snapshot",15),safe("/v1/docker/inventory",22),
            safe("/v1/extras/postgres",35),safe("/v1/alerts/status",15),
            safe("/v1/backup/status",22))
        graph=topology(inv,pg)
        return {"timestamp":int(time.time()),"health":build_health(snap,inv,pg,alerts,backups),
                "topology":graph,"host":snap and {
                    "hostname":snap.get("hostname"),
                    "cpu":snap.get("cpu",{}).get("percent"),
                    "memory":snap.get("memory",{}).get("percent")},
                "counts":{"containers":len(inv.get("containers",[])),
                          "running":sum(x.get("state")=="running" for x in inv.get("containers",[])),
                          "postgres":len(pg.get("items",[])),
                          "incidents":len(alerts.get("incidents",[]))},
                "sources":{"docker":bool(inv.get("connected")),
                           "postgres":bool(pg.get("available")),
                           "alerts":bool(alerts.get("rules"))}}

    @router.get("/trends/host")
    def host_trends(hours:int=Query(24),actor=Depends(user)):
        if hours not in (1,6,24,168,720):
            raise HTTPException(422,"Periodo inválido")
        return {"hours":hours,"items":store.host_history(hours),"forecast":store.host_forecast(hours)}

    return router
