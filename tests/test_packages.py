"""Package Manager phase B: safe inventory, fixed privileged commands and API tests."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import package_manager as pm
from app import main, store


def test_dnf_inventory_parses_updates_and_history(monkeypatch):
    monkeypatch.setattr(pm, "dnf_binary", lambda: "/usr/bin/dnf5")
    monkeypatch.setattr(pm, "HELPER", "/not/installed")
    def fake(args, **kw):
        if "repoquery" in args:
            assert "--upgrades" in args
            return 0, "kernel\t6.2\tX86_64\tupdates\nbash\t5.1\tx86_64\tfedora\n", ""
        if args[0] == "rpm":
            return 0, "kernel\t6.1\tx86_64\n", ""
        if args[1:3] == ["history", "list"]:
            return 0, "ID Command\n1 upgrade\n", ""
        raise AssertionError(args)
    monkeypatch.setattr(pm, "run", fake)
    data = pm.dnf_status()
    assert data["available"]
    assert len(data["updates"]) == 2
    assert data["updates"][0]["name"] == "kernel"
    assert data["installed"][0]["version"] == "6.1"
    assert data["history"][-1] == "1 upgrade"
    assert not data["upgrade_enabled"]


def test_flatpak_inventory_scopes_and_updates(monkeypatch):
    monkeypatch.setattr(pm.shutil, "which", lambda binary: "/usr/bin/flatpak")
    command_calls = []
    def fake(args, **kw):
        command_calls.append(args)
        if "list" in args:
            return 0, "org.gnome.Calculator\tCalculadora\tstable\tflathub\n", ""
        return 0, "org.gnome.Calculator\tCalculadora\tstable\n", ""
    monkeypatch.setattr(pm, "run", fake)
    data = pm.flatpak_status("user")
    assert data["available"] and data["upgrade_enabled"]
    assert data["updates"][0]["name"] == "Calculadora"
    assert all("--user" in cmd for cmd in command_calls)
    assert all("--system" not in cmd for cmd in command_calls)


def test_invalid_update_kind_never_runs(monkeypatch):
    invoked = []
    monkeypatch.setattr(pm, "run", lambda *args, **kw: invoked.append(args))
    with pytest.raises(ValueError):
        pm.upgrade_command("shell")
    with pytest.raises(ValueError):
        pm.start_upgrade("anything", "ACTUALIZAR DNF")
    with pytest.raises(PermissionError):
        pm.start_upgrade("flatpak-user", "wrong")
    assert not invoked


def test_exact_root_helper_subcommand(monkeypatch):
    monkeypatch.setattr(pm, "HELPER", "/usr/local/libexec/homelabos/package-helper")
    assert pm.upgrade_command("dnf") == [
        "sudo", "-n", "/usr/local/libexec/homelabos/package-helper", "dnf-upgrade"]
    assert pm.upgrade_command("flatpak-system") == [
        "sudo", "-n", "/usr/local/libexec/homelabos/package-helper", "flatpak-system-upgrade"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "pkgs.sqlite")
    monkeypatch.setattr(main, "SETUP_TOKEN", "test-only")
    main.failed_logins.clear()
    with TestClient(main.app) as c:
        res = c.post("/api/auth/setup", json={
            "username": "admin", "password": "very-strong-demo-password",
            "setup_token": "test-only",
        })
        assert res.status_code == 200
        yield c, res.json()["csrf"]


def test_package_api_requires_csrf_and_exact_phrase(client, monkeypatch):
    c, csrf = client
    calls = []
    async def fake(method, path, timeout=80, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return {"dnf": {"available": True, "updates": [], "installed": []}}
        return {"id": "0"*32, "kind": "dnf", "state": "queued"}
    monkeypatch.setattr(main, "agent_request", fake)
    assert c.get("/api/packages/status").status_code == 200
    assert c.post("/api/packages/upgrade/dnf", json={
        "confirm": True, "confirmation_text": "ACTUALIZAR DNF"}).status_code == 403
    assert c.post("/api/packages/upgrade/dnf", headers={"X-CSRF-Token":csrf},json={
        "confirm": False, "confirmation_text": "ACTUALIZAR DNF"}).status_code == 400
    assert c.post("/api/packages/upgrade/dnf", headers={"X-CSRF-Token":csrf},json={
        "confirm": True, "confirmation_text": "wrong"}).status_code == 403
    assert len(calls) == 1
    response=c.post("/api/packages/upgrade/dnf", headers={"X-CSRF-Token":csrf},json={
        "confirm": True, "confirmation_text": "ACTUALIZAR DNF"})
    assert response.status_code == 200
    assert calls[-1][2] == {"confirmation_text": "ACTUALIZAR DNF"}
    assert any(a["action"]=="package_upgrade" for a in c.get("/api/audit").json()["items"])


def test_start_update_requires_helper_for_root(monkeypatch):
    monkeypatch.setattr(pm, "HELPER", "/definitely/not/existing")
    with pytest.raises(PermissionError):
        pm.start_upgrade("dnf", "ACTUALIZAR DNF")
    with pytest.raises(PermissionError):
        pm.start_upgrade("flatpak-system", "ACTUALIZAR FLATPAK SISTEMA")
