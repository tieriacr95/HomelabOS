import pytest
from fastapi.testclient import TestClient

from app import main, store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "homelab-test.db")
    monkeypatch.setattr(main, "SETUP_TOKEN", "ci-setup-token-for-tests")
    monkeypatch.setattr(main, "AGENT_TOKEN", "a" * 60)
    monkeypatch.setattr(main, "SERVICES_PATH", tmp_path / "no-services.json")
    main.failed_logins.clear()
    with TestClient(main.app) as c:
        yield c


def create_admin(client):
    r = client.post("/api/auth/setup", json={
        "username": "admin", "password": "very-long-test-password",
        "setup_token": "ci-setup-token-for-tests",
    })
    assert r.status_code == 200, r.text
    return r.json()["csrf"]


def test_health_and_setup_protection(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/auth/status").json()["configured"] is False
    bad = client.post("/api/auth/setup", json={
        "username": "admin", "password": "very-long-test-password", "setup_token": "bad"
    })
    assert bad.status_code == 403
    token = create_admin(client)
    status = client.get("/api/auth/status").json()
    assert status["configured"] and status["authenticated"]
    assert status["csrf"] == token
    assert client.post("/api/auth/setup", json={
        "username": "other", "password": "another-long-password", "setup_token": "ci-setup-token-for-tests"
    }).status_code == 409


def test_login_logout_and_csrf(client):
    token = create_admin(client)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get("/api/dashboard").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    logged = client.post("/api/auth/login", json={"username": "admin", "password": "very-long-test-password"})
    assert logged.status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"]


def test_dashboard_reports_agent_offline_without_fake_data(client):
    create_admin(client)
    data = client.get("/api/dashboard").json()
    assert not data["agent_online"]
    assert data["host"] is None
    assert data["alerts"][0]["message"] == "Agente Fedora desconectado"
    assert client.get("/api/history?hours=2").status_code == 422


def test_container_restart_requires_csrf_and_confirmation(client):
    csrf = create_admin(client)
    endpoint = "/api/containers/plex/restart"
    assert client.post(endpoint, json={"confirm": True}).status_code == 403
    assert client.post(endpoint, json={"confirm": False}, headers={"X-CSRF-Token": csrf}).status_code == 400
    assert client.post(endpoint, json={"confirm": True}, headers={"X-CSRF-Token": csrf}).status_code == 503


def test_sample_history(client):
    create_admin(client)
    store.add_metric({"cpu": {"percent": 7}, "memory": {"percent": 21},
                      "disks": [{"mount": "/", "percent": 40}],
                      "containers": [{"state": "running"}]})
    items = client.get("/api/history?hours=1").json()["items"]
    assert len(items) == 1
    assert items[0]["running_containers"] == 1
