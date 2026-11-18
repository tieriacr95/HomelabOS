"""Docker CLI parsing and deny-by-default safety regression tests."""
import pytest
from agent import docker_manager as dm


def test_inventory_compose_and_resources(monkeypatch):
    def cli(*args, **kwargs):
        if args[0] == "ps":
            return ([{
                "Names": "personal-planner-web-1", "Image": "planner-web:latest",
                "ID": "abc123", "State": "running", "Status": "Up 1h",
                "Ports": "127.0.0.1:8080->80/tcp",
            }, {
                "Names": "plex", "Image": "plex:latest", "ID": "def",
                "State": "exited", "Status": "Exited", "Ports": "",
            }], None)
        if args[0] == "image":
            return ([{"ID": "abc123", "Repository": "planner-web", "Tag": "latest",
                      "Size": "120MB", "CreatedSince": "2 hours ago"}], None)
        if args[0] == "volume":
            return ([{"Name": "planner_db_data", "Driver": "local"}], None)
        if args[0] == "network":
            return ([{"ID": "123", "Name": "planner-edge", "Driver": "bridge",
                      "Scope": "local"}], None)
        raise AssertionError("Unexpected Docker command")

    monkeypatch.setattr(dm, "json_lines", cli)
    monkeypatch.setattr(dm, "compose_labels", lambda names: {
        "personal-planner-web-1": {"project": "personal-planner", "service": "web"},
        "plex": {"project": "", "service": ""},
    })
    result = dm.inventory({"plex"})
    assert result["connected"]
    assert len(result["containers"]) == 2
    assert result["projects"] == [{
        "name": "personal-planner", "total": 1, "running": 1,
        "containers": ["personal-planner-web-1"], "services": ["web"],
    }]
    assert result["containers"][0]["allowed_actions"] == []
    assert result["containers"][1]["allowed_actions"] == ["restart", "start", "stop"]
    assert result["images"][0]["repository"] == "planner-web"
    assert result["volumes"][0]["name"] == "planner_db_data"
    assert result["networks"][0]["name"] == "planner-edge"


def test_docker_offline_uses_no_simulated_data(monkeypatch):
    monkeypatch.setattr(dm, "json_lines", lambda *args, **kw: ([], "Docker unavailable"))
    result = dm.inventory()
    assert not result["connected"]
    assert result["error"] == "Docker unavailable"
    assert result["containers"] == []
    assert result["projects"] == []


def test_stats_parsing(monkeypatch):
    monkeypatch.setattr(dm, "json_lines", lambda *a, **k: ([{
        "Name": "plex", "CPUPerc": "3.45%", "MemUsage": "20MiB / 2GiB",
        "MemPerc": "0.97%", "NetIO": "10MB / 1MB",
        "BlockIO": "8MB / 4MB", "PIDs": "15",
    }], None))
    result = dm.stats()
    assert result["items"][0]["name"] == "plex"
    assert result["items"][0]["cpu"] == "3.45%"
    assert result["items"][0]["memory_percent"] == "0.97%"


def test_container_operations_enforce_explicit_allowlist(monkeypatch):
    invoked = []
    monkeypatch.setattr(dm, "command", lambda *args, **kw: (invoked.append(args) or 0, "", ""))
    for name in ("finance-os-db-1", "../plex", "plex;touch /tmp/x", "-root"):
        with pytest.raises(PermissionError):
            dm.control(name, "stop", {"plex"})
    with pytest.raises(PermissionError):
        dm.control("plex", "rm", {"plex"})
    assert not invoked

    result = dm.control("plex", "restart", {"plex"})
    assert result["ok"]
    assert invoked == [("docker", "restart", "--time", "10", "plex")]


def test_logs_bounded_inputs_and_escape_stripping(monkeypatch):
    invoked = []
    def cli(*args, **kwargs):
        invoked.append(args)
        return 0, "\x1b[31mstarted\x1b[0m", ""
    monkeypatch.setattr(dm, "command", cli)
    for tail, since in ((0, "30m"), (501, "30m"), (200, "--help")):
        with pytest.raises(ValueError):
            dm.logs("plex", tail=tail, since=since)
    with pytest.raises(ValueError):
        dm.logs("../plex")
    assert invoked == []
    result = dm.logs("plex", 150, "5m")
    assert result["logs"] == "started"
    assert invoked[0] == ("docker", "logs", "--tail", "150", "--timestamps",
                          "--since", "5m", "plex")
