"""Backup API safety: auth, CSRF, typed approval, immutable recovery target."""
import pytest
from fastapi.testclient import TestClient
from app import main, store


@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"backup-api.db")
    monkeypatch.setattr(main,"SETUP_TOKEN","test-setup-secret")
    main.failed_logins.clear()
    with TestClient(main.app) as client:
        result=client.post("/api/auth/setup",json={
            "username":"admin","password":"long-test-password-123456",
            "setup_token":"test-setup-secret"})
        assert result.status_code==200,result.text
        yield client,result.json()["csrf"]


def test_backup_requires_session(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"backup-noauth.db")
    with TestClient(main.app) as client:
        assert client.get("/api/backup/status").status_code==401
        assert client.get("/api/backup/snapshots").status_code==401
        assert client.get("/api/backup/jobs").status_code==401
        assert client.post("/api/backup/backup",json={
            "confirm":True,"confirmation_text":"EJECUTAR RESPALDO"}).status_code==401


def test_backup_requires_csrf_and_confirmation(session,monkeypatch):
    client,csrf=session
    sent=[]
    async def relay(method,path,body=None,timeout=50):
        sent.append((method,path,body))
        return {"id":"a"*32,"state":"queued"}
    monkeypatch.setattr(main,"agent_request",relay)
    url="/api/backup/backup"
    assert client.post(url,json={"confirm":True,
                         "confirmation_text":"EJECUTAR RESPALDO"}).status_code==403
    assert client.post(url,headers={"X-CSRF-Token":csrf},
                       json={"confirm":False,"confirmation_text":"EJECUTAR RESPALDO"}).status_code==400
    assert client.post(url,headers={"X-CSRF-Token":csrf},
                       json={"confirm":True,"confirmation_text":"no"}).status_code==403
    assert not sent
    response=client.post(url,headers={"X-CSRF-Token":csrf},
                         json={"confirm":True,"confirmation_text":"EJECUTAR RESPALDO"})
    assert response.status_code==200,response.text
    assert sent[0]==("POST","/v1/backup/backup",
                     {"confirmation_text":"EJECUTAR RESPALDO","snapshot":None})
    assert any(e["action"]=="backup_backup" for e in client.get("/api/audit").json()["items"])


def test_restore_requires_valid_snapshot_id_and_specific_phrase(session,monkeypatch):
    client,csrf=session
    called=[]
    async def relay(method,path,body=None,timeout=50):
        called.append(body)
        return {"id":"a"*32,"state":"queued"}
    monkeypatch.setattr(main,"agent_request",relay)
    url="/api/backup/restore"
    bad=client.post(url,headers={"X-CSRF-Token":csrf},json={
        "confirm":True,"confirmation_text":"RESTAURAR x","snapshot":"../../etc/passwd"})
    assert bad.status_code==422
    snapshot="f"*64
    mismatch=client.post(url,headers={"X-CSRF-Token":csrf},json={
        "confirm":True,"confirmation_text":"RESTAURAR "+("e"*64),
        "snapshot":snapshot})
    assert mismatch.status_code==403
    assert called==[]
    good=client.post(url,headers={"X-CSRF-Token":csrf},json={
        "confirm":True,"confirmation_text":"RESTAURAR "+snapshot,
        "snapshot":snapshot})
    assert good.status_code==200
    assert called==[{"confirmation_text":"RESTAURAR "+snapshot,"snapshot":snapshot}]


def test_backup_status_read_only(session,monkeypatch):
    client,_=session
    async def relay(method,path,body=None,timeout=50):
        assert method=="GET"
        return {"configured":True,"sources":[],"jobs":[]}
    monkeypatch.setattr(main,"agent_request",relay)
    assert client.get("/api/backup/status").json()["configured"] is True
    assert client.get("/api/backup/jobs").status_code==200
