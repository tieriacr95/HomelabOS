"""Authenticated Docker API safety tests; no real Docker or agent required."""
import pytest
from fastapi.testclient import TestClient

from app import main, store


@pytest.fixture
def logged_client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main, "SETUP_TOKEN", "test-setup-token")
    main.failed_logins.clear()
    with TestClient(main.app) as client:
        response = client.post("/api/auth/setup", json={
            "username": "admin", "password": "example-strong-password",
            "setup_token": "test-setup-token",
        })
        assert response.status_code == 200
        yield client, response.json()["csrf"]


def test_requires_login_and_csrf(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as client:
        assert client.get("/api/docker/inventory").status_code == 401
        assert client.get("/api/docker/stats").status_code == 401
        assert client.get("/api/docker/containers/plex/logs").status_code == 401
        assert client.post("/api/docker/containers/plex/stop",
                           json={"confirm": True}).status_code == 401


def test_readonly_inventory_stats_and_logs(logged_client, monkeypatch):
    client, _ = logged_client
    called = []
    async def relay(method, path, timeout=25):
        called.append((method, path))
        if path.endswith("/inventory"):
            return {"connected": True, "containers": [], "projects": [],
                    "images": [], "volumes": [], "networks": []}
        if path.endswith("/stats"):
            return {"items": [], "error": None}
        if "/logs?" in path:
            return {"name": "plex", "logs": "hello\n", "tail": 5, "since": "5m"}
        raise AssertionError(path)

    monkeypatch.setattr(main, "agent_request", relay)
    assert client.get("/api/docker/inventory").json()["connected"]
    assert client.get("/api/docker/stats").status_code == 200
    logs = client.get("/api/docker/containers/plex/logs?tail=5&since=5m")
    assert logs.json()["logs"] == "hello\n"
    assert len(called) == 3
    assert client.get("/api/docker/containers/plex/logs?tail=900").status_code == 422
    assert client.get("/api/docker/containers/plex/logs?since=--help").status_code == 422


def test_control_requires_confirmation_and_records_audit(logged_client, monkeypatch):
    client, csrf = logged_client
    called = []
    async def relay(method, path, timeout=25):
        called.append((method, path))
        return {"ok": True, "container": "plex", "action": "stop"}

    monkeypatch.setattr(main, "agent_request", relay)
    endpoint = "/api/docker/containers/plex/stop"
    assert client.post(endpoint, json={"confirm": True}).status_code == 403
    assert client.post(endpoint, headers={"X-CSRF-Token": csrf},
                       json={"confirm": False}).status_code == 400
    assert client.post("/api/docker/containers/plex/rm",
                       headers={"X-CSRF-Token": csrf}, json={"confirm": True}).status_code == 422
    assert not called
    response = client.post(endpoint, headers={"X-CSRF-Token": csrf}, json={"confirm": True})
    assert response.status_code == 200, response.text
    assert called == [("POST", "/v1/docker/containers/plex/stop")]
    assert any(row["action"] == "stop" and row["target"] == "plex"
               for row in client.get("/api/audit").json()["items"])
