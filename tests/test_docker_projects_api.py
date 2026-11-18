"""API action preview and typed confirmation safety checks."""
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main, store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.sqlite")
    monkeypatch.setattr(main, "SETUP_TOKEN", "test-secret")
    main.failed_logins.clear()
    with TestClient(main.app) as http:
        r = http.post("/api/auth/setup", json={"username": "admin",
                       "password": "long-password-123456", "setup_token": "test-secret"})
        assert r.status_code == 200
        yield http, r.json()["csrf"]


def test_preview_and_execution_not_mixing_http_methods(client, monkeypatch):
    http, csrf = client
    calls = []
    async def relay(method, path, timeout=9.0, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return {"scope": "project", "name": "lab", "containers": ["lab-db-1"],
                    "critical": ["lab-db-1"], "confirmation_phrase": "DETENER PROYECTO lab",
                    "requires_confirmation": True}
        if body != {"confirmation_text": "DETENER PROYECTO lab"}:
            raise httpx.HTTPStatusError(
                "no confirmation", request=httpx.Request("POST", "http://host"),
                response=httpx.Response(403, request=httpx.Request("POST", "http://host")))
        return {"ok": True, "completed": ["lab-db-1"]}
    monkeypatch.setattr(main, "agent_request", relay)
    p = http.get("/api/docker/plan/project/lab/stop")
    assert p.status_code == 200 and p.json()["requires_confirmation"]
    assert http.post("/api/docker/execute/project/lab/stop", json={"confirm": True}).status_code == 403
    assert http.post("/api/docker/execute/project/lab/stop",
                     headers={"X-CSRF-Token": csrf},
                     json={"confirm": False}).status_code == 400
    good = http.post("/api/docker/execute/project/lab/stop",
                     headers={"X-CSRF-Token": csrf},
                     json={"confirm": True, "confirmation_text": "DETENER PROYECTO lab"})
    assert good.status_code == 200
    assert calls[0][0] == "GET"
    assert calls[-1] == ("POST", "/v1/docker/execute/project/lab/stop",
                         {"confirmation_text": "DETENER PROYECTO lab"})
    audit = http.get("/api/audit").json()["items"]
    assert audit[0]["target"] == "project:lab"


def test_denies_invalid_scope_or_command(client):
    http, csrf = client
    assert http.get("/api/docker/plan/stack/lab/stop").status_code == 422
    assert http.get("/api/docker/plan/project/lab/remove").status_code == 422
    assert http.post("/api/docker/execute/project/lab/prune",
                     headers={"X-CSRF-Token":csrf}, json={"confirm": True}).status_code == 422
