"""Two-stage, deny-by-default Docker Compose project safety."""
import pytest
from agent import docker_manager as dm


def snapshot(allowed):
    containers = [
        {"name": "lab-db-1", "project": "lab", "service": "db", "image": "postgres:17",
         "state": "running", "critical_reason": dm.critical_reason("lab-db-1", "postgres:17")},
        {"name": "lab-api-1", "project": "lab", "service": "api", "image": "api",
         "state": "running", "critical_reason": ""},
        {"name": "lab-web-1", "project": "lab", "service": "web", "image": "web",
         "state": "running", "critical_reason": ""},
    ]
    return {"connected": True, "containers": containers}


def test_project_requires_all_allowlisted_and_reinforced_phrase(monkeypatch):
    with pytest.raises(PermissionError):
        dm.operation_plan("project", "lab", "stop", {"lab-web-1"}, snapshot({"lab-web-1"}))
    all_names = {"lab-db-1", "lab-api-1", "lab-web-1"}
    plan = dm.operation_plan("project", "lab", "stop", all_names, snapshot(all_names))
    assert plan["requires_confirmation"]
    assert plan["confirmation_phrase"] == "DETENER PROYECTO lab"
    assert plan["containers"] == ["lab-web-1", "lab-api-1", "lab-db-1"]
    calls = []
    monkeypatch.setattr(dm, "command", lambda *args, **kw: (calls.append(args) or 0, "", ""))
    with pytest.raises(PermissionError):
        dm.execute_plan(plan, all_names, "")
    assert calls == []
    result = dm.execute_plan(plan, all_names, "DETENER PROYECTO lab")
    assert result["ok"] and len(result["completed"]) == 3
    assert calls[0] == ("docker", "stop", "--time", "10", "lab-web-1")


def test_critical_self_and_db_need_phrase(monkeypatch):
    sample = {"connected": True, "containers": [{
        "name": "homelabos-homelabos-1", "project": "", "image": "homelabos:local",
        "service": "", "critical_reason": dm.critical_reason("homelabos-homelabos-1"),
    }]}
    plan = dm.operation_plan("container", "homelabos-homelabos-1", "stop",
                             {"homelabos-homelabos-1"}, sample)
    assert plan["confirmation_phrase"] == "DETENER homelabos-homelabos-1"
    assert plan["critical"] == ["homelabos-homelabos-1"]
    with pytest.raises(PermissionError):
        dm.execute_plan(plan, {"homelabos-homelabos-1"}, "wrong")
    assert dm.critical_reason("finance-os-db-1")
    assert dm.critical_reason("flamboyant_cloudflared")
    assert not dm.critical_reason("plex")


def test_project_does_not_run_arbitrary_compose(monkeypatch):
    all_names = {"lab-db-1", "lab-api-1", "lab-web-1"}
    plan = dm.operation_plan("project", "lab", "start", all_names, snapshot(all_names))
    commands = []
    monkeypatch.setattr(dm, "command", lambda *args, **kw: (commands.append(args) or 0, "", ""))
    assert dm.execute_plan(plan, all_names, "INICIAR PROYECTO lab")["ok"]
    assert [cmd[-1] for cmd in commands] == ["lab-db-1", "lab-api-1", "lab-web-1"]
    assert all(cmd[0] == "docker" and cmd[1] == "start" for cmd in commands)


def test_partial_failures_stop_sequence(monkeypatch):
    all_names = {"lab-db-1", "lab-api-1", "lab-web-1"}
    plan = dm.operation_plan("project", "lab", "stop", all_names, snapshot(all_names))
    called = []
    def fake(*args, **kwargs):
        called.append(args)
        return ((1, "", "failed") if args[-1] == "lab-api-1" else (0, "", ""))
    monkeypatch.setattr(dm, "command", fake)
    result = dm.execute_plan(plan, all_names, "DETENER PROYECTO lab")
    assert not result["ok"]
    assert result["completed"] == ["lab-web-1"]
    assert result["failed"] == "lab-api-1"
    assert len(called) == 2
