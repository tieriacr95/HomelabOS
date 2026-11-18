"""Extended host diagnostics, secure user-systemd actions, metrics and TLS targets."""
import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent import enhancements as extra
from app import main, store, tls_monitor


def test_systemd_inventory_and_user_allowlist(monkeypatch):
    calls=[]
    def fake(*args, **kwargs):
        calls.append(args)
        return 0, "homepage.service loaded active running Homepage\nhomelabos-agent.service loaded active running Agent\n", ""
    monkeypatch.setattr(extra, "command", fake)
    data=extra.systemd_units({"homelabos-agent.service"})
    assert len(data["groups"])==2
    assert data["groups"][0]["items"][1]["manageable"] is True
    assert data["groups"][1]["items"][1]["manageable"] is False
    assert all("list-units" in call for call in calls)


def test_systemd_rejects_unauthorized_and_root(monkeypatch):
    calls=[]
    monkeypatch.setattr(extra, "command", lambda *args, **kw:(calls.append(args) or 0, "", ""))
    allowed={"homepage.service"}
    for scope,unit,action in [
        ("system","homepage.service","stop"),
        ("user","sshd.service","restart"),
        ("user","../../tmp.service","stop"),
        ("user","homepage.service","enable"),
    ]:
        with pytest.raises((ValueError,PermissionError)):
            extra.systemd_execute(scope,unit,action,allowed,"STOP homepage.service")
    with pytest.raises(PermissionError):
        extra.systemd_execute("user","homepage.service","stop",allowed,"wrong")
    assert not calls
    r=extra.systemd_execute("user","homepage.service","stop",allowed,"STOP homepage.service")
    assert r["ok"]
    assert calls == [("systemctl","--user","stop","homepage.service")]


def test_pg_readiness_uses_no_password(monkeypatch):
    monkeypatch.setattr(extra.docker, "inventory", lambda: {
        "connected": True,
        "containers": [
            {"name":"planner-db-1","image":"postgres:17","project":"planner","state":"running"},
            {"name":"finance-web-1","image":"nginx:latest","project":"finance","state":"running"},
            {"name":"cloud-db-1","image":"postgres:17","project":"cloud","state":"exited"},
        ]
    })
    calls=[]
    def fake(*args, **kwargs):
        calls.append(args)
        return 0,"",""
    monkeypatch.setattr(extra, "command", fake)
    out=extra.postgres_checks()
    assert len(out["items"])==2
    assert out["items"][0]["status"]=="accepting"
    assert out["items"][1]["status"]=="stopped"
    assert calls==[("docker","exec","planner-db-1","pg_isready","-h","127.0.0.1","-p","5432","-q")]


def test_metrics_history_bounded_and_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"db.sqlite")
    store.initialize()
    snapshot={"items":[{"name":"plex","cpu":"12.7%","memory_percent":"4.5%","pids":"18"},
                      {"name":"bad;inject","cpu":"2%","memory_percent":"3%","pids":"1"}]}
    assert store.record_container_stats(snapshot)==1
    assert store.record_container_stats(snapshot)==0
    row=store.container_history("plex")[0]
    assert row["cpu_percent"]==12.7
    assert row["mem_percent"]==4.5
    with pytest.raises(ValueError):
        store.container_history("../passwd")
    with pytest.raises(ValueError):
        store.container_history("plex",999)


def test_tls_load_from_admin_files_only(tmp_path):
    config=tmp_path/"services.json"
    manual=tmp_path/"tls.json"
    config.write_text(json.dumps([
        {"name":"App HTTPS","url":"https://app.example.com:8443/health","enabled":True},
        {"name":"Local","url":"http://localhost:8080","enabled":True},
        {"name":"Disabled","url":"https://hidden.example.net","enabled":False},
    ]))
    manual.write_text(json.dumps([
        {"name":"Personal","host":"personal.example.net","port":443},
        {"host":"bad host","port":443},
        {"host":"invalid.example.org","port":70000},
        {"name":"Duplicate","host":"app.example.com","port":8443},
    ]))
    targets=tls_monitor.load_targets(config,manual)
    assert len(targets)==2
    assert targets[0]["host"]=="app.example.com" and targets[0]["port"]==8443


@pytest.fixture
def logged_client(tmp_path, monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"app.sqlite")
    monkeypatch.setattr(main,"SETUP_TOKEN","setup-test")
    main.failed_logins.clear()
    with TestClient(main.app) as client:
        login=client.post("/api/auth/setup",json={"username":"admin",
            "password":"correct-horse-battery-2026","setup_token":"setup-test"})
        assert login.status_code==200
        yield client, login.json()["csrf"]


def test_api_requires_login_and_csrf(tmp_path, monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"api.sqlite")
    with TestClient(main.app) as client:
        assert client.get("/api/extras/postgres").status_code==401
        assert client.get("/api/extras/systemd").status_code==401
        assert client.get("/api/extras/tls").status_code==401
        assert client.get("/api/extras/containers/plex/history").status_code==401
        assert client.post("/api/extras/systemd/user/homepage.service/stop",
            json={"confirm":True,"confirmation_text":"STOP homepage.service"}).status_code==401


def test_user_systemd_api_audited(logged_client,monkeypatch):
    client,csrf=logged_client
    calls=[]
    async def fake(method,path,timeout=25,body=None):
        calls.append((method,path,body))
        return {"ok":True,"unit":"homepage.service"}
    monkeypatch.setattr(main,"agent_request",fake)
    url="/api/extras/systemd/user/homepage.service/stop"
    assert client.post(url,json={"confirm":True,"confirmation_text":"STOP homepage.service"}).status_code==403
    assert client.post(url,headers={"X-CSRF-Token":csrf},json={
        "confirm":True,"confirmation_text":"wrong"}).status_code==403
    assert client.post("/api/extras/systemd/system/sshd.service/stop",
        headers={"X-CSRF-Token":csrf},json={"confirm":True,"confirmation_text":"STOP sshd.service"}).status_code==422
    assert calls==[]
    r=client.post(url,headers={"X-CSRF-Token":csrf},json={
        "confirm":True,"confirmation_text":"STOP homepage.service"})
    assert r.status_code==200 and r.json()["ok"]
    assert calls[-1][2]=={"confirmation_text":"STOP homepage.service"}
    assert any(x["action"]=="systemd_stop" for x in client.get("/api/audit").json()["items"])
