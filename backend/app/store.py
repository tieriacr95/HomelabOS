"""Local state and authentication storage. Every connection is short-lived."""
import hashlib
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.getenv("HOMELAB_DB_PATH", "/data/homelabos.db"))


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf TEXT NOT NULL,
          expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metrics (
          id INTEGER PRIMARY KEY,
          timestamp INTEGER NOT NULL,
          cpu REAL NOT NULL,
          memory REAL NOT NULL,
          disk REAL NOT NULL,
          running_containers INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics(timestamp);
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY,
          timestamp INTEGER NOT NULL,
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          target TEXT NOT NULL,
          result TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS security_scans (
          id INTEGER PRIMARY KEY,
          timestamp INTEGER NOT NULL,
          critical INTEGER NOT NULL,
          high INTEGER NOT NULL,
          medium INTEGER NOT NULL,
          info INTEGER NOT NULL,
          non_loopback INTEGER,
          checks_available INTEGER NOT NULL,
          ssh_failed INTEGER,
          selinux TEXT NOT NULL,
          firewall TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_security_scans_time ON security_scans(timestamp);
        """)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def user_count():
    with connect() as db:
        return db.execute("SELECT count(*) FROM users").fetchone()[0]


def find_user(username):
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


def create_first_user(username, password_hash):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM users").fetchone()[0]:
            raise ValueError("Already configured")
        db.execute("INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                   (username, password_hash, int(time.time())))


def create_session(user_id, token, csrf, expires):
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
        db.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)",
                   (hash_token(token), user_id, csrf, expires))


def session_user(token):
    if not token:
        return None
    with connect() as db:
        row = db.execute("""
          SELECT users.id, users.username, sessions.csrf
          FROM sessions JOIN users ON users.id=sessions.user_id
          WHERE sessions.token_hash=? AND sessions.expires_at>?
        """, (hash_token(token), int(time.time()))).fetchone()
        return dict(row) if row else None


def remove_session(token):
    if token:
        with connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(token),))


def add_metric(snapshot):
    if not snapshot:
        return
    cpu = float(snapshot.get("cpu", {}).get("percent", 0))
    memory = float(snapshot.get("memory", {}).get("percent", 0))
    disks = snapshot.get("disks") or []
    root = next((d for d in disks if d.get("mount") == "/"), None)
    disk = float((root or (disks[0] if disks else {})).get("percent", 0))
    running = sum(1 for c in snapshot.get("containers", []) if c.get("state") == "running")
    now = int(time.time())
    with connect() as db:
        last = db.execute("SELECT timestamp FROM metrics ORDER BY id DESC LIMIT 1").fetchone()
        if last is None or now - last[0] >= 60:
            db.execute("INSERT INTO metrics(timestamp,cpu,memory,disk,running_containers) VALUES(?,?,?,?,?)",
                       (now, cpu, memory, disk, running))
            db.execute("DELETE FROM metrics WHERE timestamp<?", (now - 30 * 86400,))


def history(hours=24):
    since = int(time.time()) - hours * 3600
    with connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT timestamp,cpu,memory,disk,running_containers FROM metrics "
            "WHERE timestamp>=? ORDER BY timestamp", (since,)).fetchall()]


def log(actor, action, target, result):
    with connect() as db:
        db.execute("INSERT INTO audit(timestamp,actor,action,target,result) VALUES(?,?,?,?,?)",
                   (int(time.time()), actor, action, target, result))


def recent_audit():
    with connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT timestamp,actor,action,target,result FROM audit ORDER BY id DESC LIMIT 50").fetchall()]


def record_security_scan(report):
    """Store aggregated findings only; never persist port/process/user or journal details."""
    now = int(time.time())
    summary = report.get("summary", {})
    with connect() as db:
        last = db.execute("SELECT timestamp FROM security_scans ORDER BY id DESC LIMIT 1").fetchone()
        if last is not None and now - last[0] < 600:
            return False
        db.execute("""
            INSERT INTO security_scans(
              timestamp,critical,high,medium,info,non_loopback,
              checks_available,ssh_failed,selinux,firewall
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (now, int(summary.get("critical", 0)), int(summary.get("high", 0)),
              int(summary.get("medium", 0)), int(summary.get("info", 0)),
              summary.get("visible_ports"), int(summary.get("checks_available", 0)),
              report.get("authentication", {}).get("ssh_failed"),
              str(report.get("selinux", {}).get("mode", "unknown"))[:40],
              str(report.get("firewall", {}).get("state", "unknown"))[:40]))
        db.execute("DELETE FROM security_scans WHERE timestamp<?", (now - 30 * 86400,))
    return True


def security_history(days=7):
    since = int(time.time()) - days * 86400
    with connect() as db:
        return [dict(row) for row in db.execute("""
            SELECT timestamp,critical,high,medium,info,non_loopback,
                   checks_available,ssh_failed,selinux,firewall
            FROM security_scans WHERE timestamp>=? ORDER BY timestamp DESC LIMIT 150
        """, (since,)).fetchall()]
