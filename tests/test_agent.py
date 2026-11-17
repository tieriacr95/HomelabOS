from agent import agent


def test_restart_allowlist_rejects_other_containers(monkeypatch):
    monkeypatch.setattr(agent, "ALLOWED", {"plex", "homepage"})
    assert agent.can_restart("plex")
    assert not agent.can_restart("db")
    assert not agent.can_restart("../plex")
    assert not agent.can_restart("plex; rm -rf /")


def test_docker_inventory_parsing(monkeypatch):
    sample = '{"Names":"plex","Image":"plex:latest","State":"running","Status":"Up 12 minutes","ID":"abcd","Ports":"32400/tcp"}'
    monkeypatch.setattr(agent, "ALLOWED", {"plex"})
    monkeypatch.setattr(agent, "run", lambda *a, **k: (0, sample, ""))
    containers, err = agent.docker_containers()
    assert err is None
    assert containers == [{
        "name": "plex", "image": "plex:latest", "state": "running",
        "status": "Up 12 minutes", "id": "abcd", "ports": "32400/tcp",
        "restart_allowed": True
    }]
