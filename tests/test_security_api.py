"""Security API authorization, data quality and non-sensitive scan history."""
import time

import pytest
from fastapi.testclient import TestClient

from app import main, store


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "security-test.sqlite")
    monkeypatch.setattr(main, "SETUP_TOKEN", "setup-test-token")
    main.failed_logins.clear()
    with TestClient(main.app) as client:
        response=client.post("/api/auth/setup",json={
            "username":"admin","password":"secure-test-password-1234",
            "setup_token":"setup-test-token"})
        assert response.status_code==200
        yield client


def sample_report():
    return {
        "timestamp":int(time.time()),"hostname":"test-host",
        "selinux":{"mode":"enforcing","configured":"enforcing","available":True},
        "firewall":{"state":"running","service":"active","zones":[]},
        "ssh":{"service":"active","available":False,"effective":{}},
        "ports":{"available":True,"non_loopback":2,"items":[]},
        "authentication":{"available":False,"ssh_failed":None},
        "summary":{"critical":0,"high":0,"medium":1,"info":0,
                   "visible_ports":2,"checks_available":3,"checks_total":5},
        "findings":[{"id":"example","severity":"medium","title":"Example","detail":"test"}]
    }


def test_security_requires_session(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "security-noauth.sqlite")
    with TestClient(main.app) as client:
        assert client.get("/api/security/report").status_code==401
        assert client.get("/api/security/history").status_code==401
        assert client.post("/api/security/report").status_code in (404,405)


def test_scan_and_history_without_sensitive_data(admin_client, monkeypatch):
    async def relay(method, path, timeout=65):
        assert method=="GET" and path.startswith("/v1/security/report?")
        return sample_report()
    monkeypatch.setattr(main,"agent_request",relay)
    response=admin_client.get("/api/security/report")
    assert response.status_code==200,response.text
    data=response.json()
    assert data["summary"]["checks_available"]==3
    result=admin_client.get("/api/security/history?days=7")
    assert result.status_code==200
    rows=result.json()["items"]
    assert len(rows)==1 and rows[0]["medium"]==1
    assert rows[0]["selinux"]=="enforcing"
    assert rows[0]["ssh_failed"] is None
    assert "hostname" not in rows[0]
    assert "findings" not in rows[0]


def test_history_query_boundaries(admin_client):
    assert admin_client.get("/api/security/history?days=31").status_code==422
    assert admin_client.get("/api/security/history?days=1").status_code==422
    assert admin_client.get("/api/security/history?days=7").status_code==200


def test_manual_refresh_is_audited(admin_client, monkeypatch):
    async def relay(method, path, timeout=65):
        assert path.endswith("refresh=true")
        return sample_report()
    monkeypatch.setattr(main,"agent_request",relay)
    assert admin_client.get("/api/security/report?refresh=true").status_code==200
    audit=admin_client.get("/api/audit").json()["items"]
    assert any(e["action"]=="security_scan" and e["target"]=="fedora" for e in audit)


def test_security_scan_throttling(admin_client):
    snapshot=sample_report()
    assert store.record_security_scan(snapshot) is True
    assert store.record_security_scan(snapshot) is False
    assert len(store.security_history(7))==1
