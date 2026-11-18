"""Opt-in HomeLab alerting with durable incident state, bounded probes and Telegram.

No arbitrary commands, URL configuration, or bot credentials are supplied by API
callers. Monitored HTTP endpoints come from owner-maintained local configuration.
The worker runs as the Fedora user, with private SQLite state and no Docker socket
exposed to the web service.
"""
import fcntl
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psutil

try:
    from . import enhancements, backup_manager, docker_manager
except ImportError:
    import enhancements
    import backup_manager
    import docker_manager

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path.home() / ".config/homelabos"
STATE = Path.home() / ".local/state/homelabos/alerts"
RULES = CONFIG / "alerts.json"
TELEGRAM = CONFIG / "telegram.json"
DATABASE = STATE / "incidents.sqlite"
LOCK = STATE / "monitor.lock"
SERVICES = ROOT / "config/services.json"
TLS_TARGETS = ROOT / "config/tls_endpoints.json"

TYPES = ("containers", "postgres", "http", "cpu", "memory", "disk",
         "temperature", "tls", "backup")
THRESHOLDS = {
    "cpu": (90, 10, 100), "memory": (90, 10, 100),
    "disk": (85, 10, 100), "temperature": (85, 30, 115),
    "tls": (15, 1, 90), "backup": (36, 1, 720),
}
MAX_TARGETS = 100
NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")
ID_RE = re.compile(r"[a-z0-9][a-z0-9_.:/@-]{0,190}\Z")
_ID_MUTEX = threading.Lock()
_CACHE = {"at": 0, "data": None}


class AlertError(Exception):
    pass


def _private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _read_private(path):
    if not path.is_file():
        return None
    st = path.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise AlertError("Insecure local permissions for " + path.name)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_private(path, data):
    _private_dir(path.parent)
    tmp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as out:
            tmp.chmod(0o600)
            json.dump(data, out, ensure_ascii=False, indent=2)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def default_rules():
    return {
        "enabled": False,
        "consecutive_failures": 2,
        "cooldown_minutes": 60,
        "notify_recovery": True,
        "notify_telegram": False,
        "checks": {kind: True for kind in TYPES},
        "thresholds": {name: value[0] for name, value in THRESHOLDS.items()},
        "expected_containers": [],
        "silent_until": 0,
    }


def validate_rules(candidate):
    if not isinstance(candidate, dict) or set(candidate) != set(default_rules()):
        raise ValueError("Rules must contain exactly the supported settings")
    result = {}
    for key in ("enabled", "notify_recovery", "notify_telegram"):
        if type(candidate[key]) is not bool:
            raise ValueError("Expected boolean for " + key)
        result[key] = candidate[key]
    for name, low, high in (("consecutive_failures", 1, 8),
                            ("cooldown_minutes", 5, 1440)):
        value = candidate[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Invalid numeric setting " + name)
        result[name] = value
    checks = candidate["checks"]
    if not isinstance(checks, dict) or set(checks) != set(TYPES) or not all(
            type(value) is bool for value in checks.values()):
        raise ValueError("Invalid check switches")
    result["checks"] = checks.copy()
    thresholds = candidate["thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != set(THRESHOLDS):
        raise ValueError("Invalid threshold keys")
    result["thresholds"] = {}
    for name, (_, minimum, maximum) in THRESHOLDS.items():
        value = thresholds[name]
        if type(value) not in (int, float) or not minimum <= value <= maximum:
            raise ValueError("Invalid threshold " + name)
        result["thresholds"][name] = value
    expected = candidate["expected_containers"]
    if not isinstance(expected, list) or len(expected) > MAX_TARGETS or not all(
            isinstance(name, str) and NAME_RE.fullmatch(name) for name in expected):
        raise ValueError("Invalid expected container names")
    result["expected_containers"] = sorted(set(expected))
    until = candidate["silent_until"]
    if type(until) is not int or until < 0 or until > 4_102_444_800:
        raise ValueError("Invalid silence time")
    result["silent_until"] = until
    return result


def rules():
    data = _read_private(RULES)
    return validate_rules(data) if data is not None else default_rules()


def set_rules(value):
    checked = validate_rules(value)
    _write_private(RULES, checked)
    return checked


def telegram_status():
    try:
        obj = _read_private(TELEGRAM)
    except (ValueError, AlertError, OSError, TypeError):
        return {"configured": False, "error": "El archivo Telegram no se puede leer o tiene permisos inseguros"}
    if not obj:
        return {"configured": False, "error": None}
    if not isinstance(obj, dict):
        return {"configured": False, "error": "El archivo Telegram debe contener un objeto JSON"}
    token = obj.get("bot_token")
    chat = obj.get("chat_id")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9]{5,15}:[A-Za-z0-9_-]{30,128}", token):
        return {"configured": False, "error": "Token Telegram inválido"}
    if not isinstance(chat, str) or not re.fullmatch(r"-?[0-9]{4,20}", chat):
        return {"configured": False, "error": "Chat Telegram inválido"}
    return {"configured": True, "error": None}


# Only stable, token-free error identifiers leave this module.
TELEGRAM_FAILURES = {
    400: "telegram_bad_request",
    401: "telegram_invalid_token",
    403: "telegram_chat_forbidden",
    404: "telegram_invalid_token",
    409: "telegram_conflict",
    429: "telegram_rate_limited",
}


def _notify(text):
    status = telegram_status()
    if not status["configured"]:
        raise AlertError("telegram_credentials_missing")
    try:
        obj = _read_private(TELEGRAM)
    except (OSError, ValueError, TypeError, AlertError):
        raise AlertError("telegram_credentials_unreadable")
    if not isinstance(obj, dict):
        raise AlertError("telegram_credentials_unreadable")
    token = obj["bot_token"]
    body = urllib.parse.urlencode({"chat_id": obj["chat_id"],
                                   "text": text[:3500],
                                   "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=body, headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.loads(response.read(2000))
        if not isinstance(result, dict) or result.get("ok") is not True:
            code = result.get("error_code") if isinstance(result, dict) else None
            raise AlertError(TELEGRAM_FAILURES.get(code, "telegram_rejected"))
        return True
    except urllib.error.HTTPError as exc:
        # HTTPError is also URLError. Never log or propagate the URL because
        # Telegram embeds the secret bot token in the request path.
        raise AlertError(TELEGRAM_FAILURES.get(exc.code, "telegram_http_error")) from None
    except urllib.error.URLError:
        raise AlertError("telegram_network_error") from None
    except (TimeoutError, ConnectionError, OSError):
        raise AlertError("telegram_network_error") from None
    except (ValueError, TypeError):
        raise AlertError("telegram_invalid_response") from None


def test_telegram():
    state = telegram_status()
    if not state["configured"]:
        if state["error"]:
            raise AlertError("telegram_credentials_invalid")
        raise AlertError("telegram_credentials_missing")
    _notify("✅ HomeLab OS: prueba de notificaciones. Ninguna operación del sistema fue ejecutada.")
    return {"sent": True}


def _db():
    _private_dir(STATE)
    db = sqlite3.connect(DATABASE, timeout=15)
    DATABASE.chmod(0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS incidents(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      check_key TEXT NOT NULL UNIQUE,
      category TEXT NOT NULL,
      subject TEXT NOT NULL,
      title TEXT NOT NULL,
      severity TEXT NOT NULL,
      state TEXT NOT NULL,
      failures INTEGER NOT NULL DEFAULT 0,
      first_seen INTEGER NOT NULL,
      last_seen INTEGER NOT NULL,
      opened_at INTEGER,
      recovered_at INTEGER,
      acknowledged_at INTEGER,
      muted_until INTEGER NOT NULL DEFAULT 0,
      last_notified_at INTEGER NOT NULL DEFAULT 0,
      notified_open INTEGER NOT NULL DEFAULT 0,
      pending_recovery INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      incident_id INTEGER NOT NULL,
      timestamp INTEGER NOT NULL,
      event TEXT NOT NULL,
      note TEXT NOT NULL,
      FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    CREATE INDEX IF NOT EXISTS events_timestamp ON events(timestamp);
    CREATE TABLE IF NOT EXISTS checks(
      key TEXT PRIMARY KEY,
      time INTEGER NOT NULL,
      category TEXT NOT NULL,
      status TEXT NOT NULL,
      title TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      timestamp INTEGER NOT NULL,
      inspected INTEGER NOT NULL,
      failed INTEGER NOT NULL,
      unknown INTEGER NOT NULL,
      notifications INTEGER NOT NULL
    );
    """)
    return db


def _one(db, key):
    row = db.execute("SELECT * FROM incidents WHERE check_key=?", (key,)).fetchone()
    return dict(row) if row else None


def _event(db, item, action, note, now):
    db.execute("INSERT INTO events(incident_id,timestamp,event,note) VALUES(?,?,?,?)",
               (item["id"], now, action, note[:180]))


def record_results(checks, config, now=None, sender=None):
    """Incident state transitions: two failures open, one healthy closes.

    Unknown readings never create or recover incidents. Notification retries
    and cooldown are held per incident, not per timer process.
    """
    now = int(now or time.time())
    sender = sender or _notify
    emitted = 0
    with _db() as db:
        for item in checks:
            key = item["key"]
            if not isinstance(key, str) or not ID_RE.fullmatch(key):
                continue
            kind, status, subject, title = (item["category"], item["status"],
                                          item["subject"][:120], item["title"][:220])
            if kind not in TYPES or status not in ("ok", "fail", "unknown"):
                continue
            db.execute("""INSERT INTO checks(key,time,category,status,title) VALUES(?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET time=excluded.time,
                category=excluded.category,status=excluded.status,title=excluded.title""",
                (key,now,kind,status,title))
            previous = _one(db,key)
            if status == "unknown":
                continue
            if previous is None:
                db.execute("""INSERT INTO incidents(check_key,category,subject,title,
                    severity,state,failures,first_seen,last_seen)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (key,kind,subject,title,item.get("severity","warning"),
                     "pending" if status == "fail" else "healthy",
                     0,now,now))
                previous = _one(db,key)
            failures = previous["failures"]+1 if status == "fail" else 0
            next_state = previous["state"]
            opened_at = previous["opened_at"]
            recovered_at = previous["recovered_at"]
            notified_open = previous["notified_open"]
            pending_recovery = previous["pending_recovery"]
            if status == "fail" and previous["state"] in ("healthy","resolved"):
                next_state = "pending"
                opened_at = None
                recovered_at = None
                notified_open = 0
                pending_recovery = 0
            if status == "fail" and failures >= config["consecutive_failures"]:
                if next_state != "open":
                    next_state = "open"
                    opened_at = now
                    _event(db,previous,"opened",title,now)
            if status == "ok":
                if previous["state"] == "open":
                    next_state = "resolved"
                    recovered_at = now
                    pending_recovery = int(previous["notified_open"] and config["notify_recovery"])
                    _event(db,previous,"recovered",title,now)
                else:
                    next_state = "healthy"
                    pending_recovery = 0
            db.execute("""UPDATE incidents SET category=?,subject=?,title=?,
                severity=?,state=?,failures=?,last_seen=?,opened_at=?,recovered_at=?,
                notified_open=?,pending_recovery=? WHERE id=?""",
                (kind,subject,title,item.get("severity","warning"),next_state,failures,
                 now,opened_at,recovered_at,notified_open,pending_recovery,previous["id"]))
            new = _one(db,key)
            can_send = bool(config["notify_telegram"] and
                            telegram_status()["configured"] and
                            now >= config["silent_until"] and
                            now >= new["muted_until"])
            if not can_send:
                continue
            target_event = None
            if new["state"] == "open" and (
                    not new["notified_open"] or
                    (not new["acknowledged_at"] and now-new["last_notified_at"] >=
                     config["cooldown_minutes"]*60)):
                target_event = "open"
            elif new["state"] == "resolved" and new["pending_recovery"]:
                target_event = "recovery"
            if not target_event or emitted >= 5:
                continue
            label = "🔴 Alerta" if target_event == "open" else "✅ Recuperado"
            msg = f"{label} HomeLab OS\n{new['title']}\nOrigen: {new['subject']}\nID: {new['id']}"
            try:
                sender(msg)
            except (AlertError, OSError):
                _event(db,new,"delivery_failed","Telegram no disponible",now)
                continue
            emitted += 1
            if target_event == "open":
                db.execute("UPDATE incidents SET notified_open=1,last_notified_at=? WHERE id=?",
                           (now,new["id"]))
            else:
                db.execute("UPDATE incidents SET pending_recovery=0,last_notified_at=? WHERE id=?",
                           (now,new["id"]))
            _event(db,new,"telegram_"+target_event,"Notificación enviada",now)
        db.execute("DELETE FROM events WHERE timestamp<?",
                   (now-90*86400,))
        db.execute("DELETE FROM checks WHERE time<?",
                   (now-30*86400,))
        db.execute("DELETE FROM runs WHERE timestamp<?",
                   (now-90*86400,))
        db.execute("INSERT INTO runs(timestamp,inspected,failed,unknown,notifications) VALUES(?,?,?,?,?)",
                   (now,len(checks),sum(x["status"]=="fail" for x in checks),
                    sum(x["status"]=="unknown" for x in checks),emitted))
    return {"inspected":len(checks),"failed":sum(x["status"]=="fail" for x in checks),
            "unknown":sum(x["status"]=="unknown" for x in checks),
            "notifications":emitted,"timestamp":now}


def _check(kind, subject, title, status, severity="warning"):
    # Key is deterministically bound to a known source and fixed check type.
    key = f"{kind}:{subject}".lower()
    if len(key) > 190 or not ID_RE.fullmatch(key):
        return None
    return {"key":key,"category":kind,"subject":subject,
            "title":title,"status":status,"severity":severity}


def collect_host(config):
    results = []
    def put(kind, subject, title, status, severity="warning"):
        item = _check(kind,subject,title,status,severity)
        if item:
            results.append(item)
    checks=config["checks"]
    thresholds=config["thresholds"]
    if checks["cpu"]:
        cpu=psutil.cpu_percent(interval=0.15)
        put("cpu","host",f"CPU al {cpu:.1f}% (umbral {thresholds['cpu']}%)",
            "fail" if cpu>=thresholds["cpu"] else "ok")
    if checks["memory"]:
        value=psutil.virtual_memory().percent
        put("memory","host",f"RAM al {value:.1f}% (umbral {thresholds['memory']}%)",
            "fail" if value>=thresholds["memory"] else "ok")
    if checks["disk"]:
        try:
            mount = psutil.disk_usage("/")
            put("disk","root",f"Disco raíz al {mount.percent:.1f}%",
                "fail" if mount.percent>=thresholds["disk"] else "ok")
        except OSError:
            put("disk","root","No se puede leer el disco raíz","unknown")
    if checks["temperature"]:
        try:
            temperatures=psutil.sensors_temperatures()
            values=[float(item.current) for group in temperatures.values()
                    for item in group if item.current is not None]
            if values:
                high=max(values)
                put("temperature","host",f"Temperatura máxima {high:.1f} °C",
                    "fail" if high>=thresholds["temperature"] else "ok")
            else:
                put("temperature","host","Sensores de temperatura no disponibles","unknown")
        except (OSError, AttributeError):
            put("temperature","host","No se pueden leer sensores","unknown")
    if checks["containers"]:
        data=docker_manager.inventory()
        if not data.get("connected"):
            put("containers","docker","Docker no disponible","unknown")
        else:
            found={row["name"]:row for row in data["containers"]}
            for name in config["expected_containers"]:
                row=found.get(name)
                state=row.get("state") if row else "missing"
                put("containers",name,f"Contenedor {name}: {state}",
                    "ok" if state=="running" else "fail","critical")
    if checks["postgres"]:
        inspected=enhancements.postgres_checks()
        if not inspected.get("available"):
            put("postgres","engine","No se pudieron consultar PostgreSQL","unknown")
        else:
            for db in inspected.get("items",[])[:30]:
                name=db["container"]
                status=db["status"]
                put("postgres",name,f"PostgreSQL {name}: {status}",
                    "ok" if status=="accepting" else
                    ("fail" if status in ("stopped","rejecting") else "unknown"),"critical")
    return results


def _service_checks(config):
    if not config["checks"]["http"]:
        return []
    try:
        services=json.loads(SERVICES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [_check("http","configuration","Sin configuración de servicios HTTP","unknown")]
    checks=[]
    for i,entry in enumerate(services[:30]):
        if not isinstance(entry,dict) or not entry.get("enabled",True):
            continue
        url=entry.get("url","")
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme not in ("http","https") or not parsed.hostname:
            continue
        # Endpoint configuration lives on the host, not in browser-provided data.
        name=entry.get("name","Servicio")
        if not isinstance(name,str):
            continue
        name=re.sub(r"[^a-zA-Z0-9_.-]","_",name)[:60]
        try:
            request=urllib.request.Request(url,method="GET",
                    headers={"User-Agent":"HomeLabOS-Monitor/0.6"})
            with urllib.request.urlopen(request,timeout=4) as response:
                code=response.status
            status="ok" if code<500 else "fail"
        except urllib.error.HTTPError as exc:
            status="ok" if exc.code<500 else "fail"
        except (urllib.error.URLError,OSError,ValueError):
            status="fail"
        item=_check("http",name,f"Servicio HTTP {name}: {status}",status)
        if item:
            checks.append(item)
    return checks


def _tls_checks(config):
    if not config["checks"]["tls"]:
        return []
    try:
        manual=json.loads(TLS_TARGETS.read_text(encoding="utf-8"))
        services=json.loads(SERVICES.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return []
    targets=[]
    for item in manual:
        if isinstance(item,dict):
            targets.append((item.get("host"),item.get("port",443)))
    for service in services:
        if isinstance(service,dict):
            parsed=urllib.parse.urlparse(service.get("url",""))
            if parsed.scheme=="https":
                targets.append((parsed.hostname,parsed.port or 443))
    checks=[]
    for host,port in list(dict.fromkeys(targets))[:24]:
        if not isinstance(host,str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}",host):
            continue
        if type(port) is not int or not 1<=port<=65535:
            continue
        try:
            context=ssl.create_default_context()
            with socket.create_connection((host,port),timeout=4) as raw:
                with context.wrap_socket(raw,server_hostname=host) as connection:
                    cert=connection.getpeercert()
            expiry=datetime.strptime(cert["notAfter"],"%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days=int((expiry-datetime.now(timezone.utc)).total_seconds()/86400)
            state="fail" if days<=config["thresholds"]["tls"] else "ok"
            title=f"TLS {host}: {days} días restantes"
        except (OSError,ssl.SSLError,ValueError,KeyError):
            state,title="fail",f"Certificado TLS {host}: no disponible o no confiable"
        item=_check("tls",host,f"{title}",state,"critical" if state=="fail" else "warning")
        if item:
            checks.append(item)
    return checks


def _backup_checks(config):
    if not config["checks"]["backup"]:
        return []
    details=backup_manager.status()
    if not details.get("configured"):
        return []  # Never alarm about backups the owner has not configured.
    records=details.get("jobs",[])
    last_success=next((j for j in records
                       if j.get("operation")=="backup" and j.get("state")=="success"),None)
    last_failed=next((j for j in records
                      if j.get("operation")=="backup" and j.get("state")=="failed"),None)
    results=[]
    if last_success:
        timestamp=last_success.get("finished") or last_success.get("created") or 0
        elapsed=(time.time()-timestamp)/3600
        results.append(_check("backup","freshness",f"Último backup: hace {elapsed:.1f} horas",
            "fail" if elapsed>=config["thresholds"]["backup"] else "ok","critical"))
    else:
        results.append(_check("backup","freshness",
                              "Todavía no hay un backup terminado correctamente","fail","critical"))
    if last_failed and (not last_success or
                        last_failed.get("finished",0)>last_success.get("finished",0)):
        results.append(_check("backup","failure",
                              "La última tarea de backup falló","fail","critical"))
    else:
        results.append(_check("backup","failure","Último backup sin fallos nuevos","ok"))
    verify_last=next((j for j in records if j.get("operation")=="verify"
                      and j.get("state") in ("success","failed")),None)
    if verify_last:
        results.append(_check("backup","verification",
            "Última verificación de backups: "+verify_last["state"],
            "fail" if verify_last["state"]=="failed" else "ok","critical"))
    return results


def collect(config):
    results=collect_host(config)
    results.extend(_service_checks(config))
    results.extend(_tls_checks(config))
    results.extend(_backup_checks(config))
    return [x for x in results if x]


def _take_lock():
    _private_dir(STATE)
    f=open(LOCK,"a+")
    try:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return f
    except BlockingIOError:
        f.close()
        raise AlertError("Otra evaluación de alertas está en ejecución")


def poll():
    config=rules()
    if not config["enabled"]:
        return {"enabled":False,"inspected":0,"notifications":0}
    with _take_lock() as lock:
        sampled=collect(config)
        return {"enabled":True,**record_results(sampled,config)}


def rows(table, limit=100):
    with _db() as db:
        return [dict(r) for r in db.execute(
            f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?",(limit,)).fetchall()]


def summary():
    config=rules()
    with _db() as db:
        incident=[dict(r) for r in db.execute(
            "SELECT * FROM incidents WHERE state='open' ORDER BY opened_at DESC LIMIT 200")]
        recent=[dict(r) for r in db.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT 100")]
        latest=db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        checks=[dict(r) for r in db.execute(
            "SELECT * FROM checks ORDER BY key LIMIT 200")]
    scheduled=_timer_active()
    maintenance=_timer_active("homelabos-maintenance.timer")
    return {"rules":config,"telegram":telegram_status(),"timer":scheduled,
            "maintenance_timer":maintenance,"incidents":incident,"events":recent,"checks":checks,
            "last_run":dict(latest) if latest else None}


def _timer_active(name="homelabos-alerts.timer"):
    try:
        proc=subprocess.run(["systemctl","--user","is-enabled",
                             name],capture_output=True,timeout=3)
        return proc.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False


def incident_action(incident_id, action, minutes=0):
    if type(incident_id) is not int or incident_id<1:
        raise ValueError("Invalid incident id")
    if action not in ("acknowledge","silence","unsilence"):
        raise ValueError("Invalid incident action")
    if action=="silence" and (type(minutes) is not int or not 5<=minutes<=10080):
        raise ValueError("Invalid silence duration")
    now=int(time.time())
    with _db() as db:
        row=db.execute("SELECT * FROM incidents WHERE id=?",(incident_id,)).fetchone()
        if not row or row["state"]!="open":
            raise LookupError("Open incident not found")
        if action=="acknowledge":
            db.execute("UPDATE incidents SET acknowledged_at=? WHERE id=?",(now,incident_id))
        elif action=="silence":
            db.execute("UPDATE incidents SET muted_until=? WHERE id=?",
                       (now+minutes*60,incident_id))
        else:
            db.execute("UPDATE incidents SET muted_until=0 WHERE id=?",(incident_id,))
        _event(db,row,action,"Acción manual confirmada",now)
    return {"ok":True,"incident_id":incident_id,"action":action}


if __name__=="__main__":
    print(json.dumps(poll(),ensure_ascii=False))
