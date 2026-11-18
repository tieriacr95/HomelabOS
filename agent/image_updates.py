"""Controlled Docker image downloads, never auto-recreate live containers.

Only a currently discovered, allowlisted container may authorize an image pull.
No registry credentials are sent to the browser; no shell or compose commands.
"""
import re
import threading
import time
import uuid

try:
    from . import docker_manager as dm
except ImportError:
    import docker_manager as dm

REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,240}\Z")
LOCK = threading.Lock()
JOBS = {}
ACTIVE = None

def inspect_target(name, allowed):
    if not dm.valid_name(name) or name not in allowed:
        raise PermissionError("container_not_allowlisted")
    inv = dm.inventory(allowed)
    if not inv["connected"]:
        raise RuntimeError("docker_unavailable")
    item = next((c for c in inv["containers"] if c["name"] == name), None)
    if not item:
        raise ValueError("container_not_found")
    rc, ref, _ = dm.command("docker", "inspect", "--type", "container",
                            "--format", "{{.Config.Image}}", name, timeout=12,
                            max_output=1024)
    ref = ref.strip()
    if rc or not REF.fullmatch(ref) or ref.startswith("/") or ".." in ref or "@sha256:" in ref:
        raise ValueError("image_ref_unsupported")
    rc, image_id, _ = dm.command("docker", "inspect", "--type", "container",
                                 "--format", "{{.Image}}", name, timeout=12)
    if rc or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id.strip()):
        raise ValueError("image_id_unavailable")
    return {"container":name,"image":ref,"running_image_id":image_id.strip(),
            "critical":bool(item["critical_reason"]),
            "confirmation_phrase":"DESCARGAR IMAGEN "+name,
            "requires_manual_redeploy":True,
            "note":"Solo descarga la imagen. Nunca reinicia, recrea o modifica el contenedor activo."}

def _worker(job, allowed):
    global ACTIVE
    with LOCK:
        job["state"] = "running"
    try:
        # Recheck the target immediately before pull; refs can change.
        plan = inspect_target(job["container"], allowed)
        if plan["image"] != job["image"] or plan["running_image_id"] != job["running_image_id"]:
            raise ValueError("image_changed_since_preview")
        rc, before, _ = dm.command("docker","image","inspect","--format","{{.Id}}",
                                    plan["image"],timeout=12,max_output=512)
        rc, _, _ = dm.command("docker", "pull", "--quiet", "--", plan["image"],
                              timeout=600,max_output=256)
        if rc:
            raise RuntimeError("image_pull_failed")
        rc, after, _ = dm.command("docker","image","inspect","--format","{{.Id}}",
                                   plan["image"],timeout=12,max_output=512)
        if rc or not re.fullmatch(r"sha256:[a-f0-9]{64}", after.strip()):
            raise RuntimeError("image_digest_unavailable")
        job.update(state="success",changed=before.strip()!=after.strip(),
                   downloaded_image_id=after.strip(),
                   note="Imagen descargada. La sustitución del contenedor requiere un despliegue separado y aprobado.")
    except (PermissionError, ValueError, RuntimeError) as exc:
        allowed_errors={"image_changed_since_preview","image_pull_failed",
                        "image_digest_unavailable","container_not_found",
                        "docker_unavailable","image_ref_unsupported",
                        "container_not_allowlisted"}
        job.update(state="failed",error=str(exc) if str(exc) in allowed_errors else "pull_unavailable")
    finally:
        with LOCK:
            job["finished"] = int(time.time())
            ACTIVE = None

def submit(name, text, expected_id, allowed):
    global ACTIVE
    plan=inspect_target(name,allowed)
    if text!=plan["confirmation_phrase"] or expected_id!=plan["running_image_id"]:
        raise PermissionError("confirmation_or_digest_mismatch")
    with LOCK:
        if ACTIVE is not None:
            raise RuntimeError("another_pull_in_progress")
        job={"id":uuid.uuid4().hex,"container":name,"image":plan["image"],
             "running_image_id":plan["running_image_id"],
             "state":"queued","created":int(time.time())}
        JOBS[job["id"]]=job
        ACTIVE=job["id"]
        # No image tag, shell command, registry address or credentials from the caller.
        threading.Thread(target=_worker,args=(job,allowed),daemon=True).start()
    return dict(job)

def jobs():
    with LOCK:
        return [dict(j) for j in list(JOBS.values())[-30:]][::-1]
