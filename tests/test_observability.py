"""Host observability: verified Compose edges, guarded status, 30d aggregation."""
import time
import pytest
from fastapi.testclient import TestClient
from app import main, store
from app.observability import topology, build_health


def inventory():
    return {
        "connected": True,
        "projects":[{"name":"planner","total":3,"running":2,
                     "services":["db","api","web"]}],
        "containers":[
            {"name":"planner-db-1","image":"postgres:17","project":"planner",
             "service":"db","state":"running"},
            {"name":"planner-api-1","image":"api:latest","project":"planner",
             "service":"api","state":"running"},
            {"name":"planner-web-1","image":"web:latest","project":"planner",
             "service":"web","state":"exited"},
            {"name":"plex","image":"plex:latest","project":"","service":"",
             "state":"running"},
        ],
    }


def test_topology_has_grounded_project_memberships_and_labeled_inference():
    graph=topology(inventory(),{"available":True,"items":[{"container":"planner-db-1","status":"accepting"}]})
    project_links=[link for link in graph["links"] if link["type"]=="membership"]
    inferred=[link for link in graph["links"] if link["inferred"]]
    assert len(project_links)==3
    assert len(inferred)==2
    assert all(link["inferred"] is False for link in project_links)
    assert all(link["type"]=="possible_dependency" for link in inferred)
    assert any(n["id"]=="container:plex" for n in graph["nodes"])
    assert all(n["state"]=="down" for n in graph["nodes"]
               if n["id"]=="container:planner-web-1")


def test_health_does_not_falsely_alert_on_intentionally_stopped_container():
    host={"hostname":"fedora","cpu":{"percent":5.0},"memory":{"percent":23.0},
          "disks":[{"percent":30.0}]}
    report=build_health(host,inventory(),{"available":True,"items":[]},
                        {"incidents":[]},{"configured":False})
    assert report["status"]=="healthy"
    assert not report["findings"]


def test_health_prioritizes_postgres_and_monitor_incidents():
    host={"cpu":{"percent":99.0},"memory":{"percent":45.0},
          "disks":[{"percent":30.0}]}
    report=build_health(host,inventory(),
                        {"available":True,"items":[
                            {"container":"planner-db-1","status":"rejecting"}]},
                        {"incidents":[{"title":"DB sin respuesta","severity":"critical"}]},
                        {"configured":False})
    assert report["status"]=="critical"
    assert len(report["findings"])>=2


def test_host_and_container_thirty_day_buckets_are_complete(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"observability.sqlite")
    store.initialize()
    now=int(time.time())
    with store.connect() as db:
        # 1152 individual readings over 24 days; old LIMIT 1000 truncated data.
        db.executemany("""INSERT INTO metrics(timestamp,cpu,memory,disk,running_containers)
                          VALUES (?,?,?,?,?)""",
                       [(now-24*86400+i*1800,float(i%80),30.0,50+i/1000,3)
                        for i in range(1152)])
        db.executemany("""INSERT INTO container_metrics(timestamp,container,cpu_percent,mem_percent,pids)
                          VALUES (?,?,?,?,?)""",
                       [(now-24*86400+i*1800,"plex",float(i%40),10.0,2)
                        for i in range(1152)])
    host=store.host_history(720)
    docker=store.container_history("plex",720)
    assert 80<=len(host)<=120
    assert len(docker)==len(host)
    assert host[-1]["timestamp"]>now-2*86400
    assert docker[-1]["timestamp"]>now-2*86400
    assert all(row["samples"]>=1 for row in host)
    forecast=store.host_forecast(720)
    assert forecast["available"]
    assert forecast["method"]=="linear_indicative"
    assert "metrics" in forecast
    with pytest.raises(ValueError):
        store.host_history(500)


@pytest.fixture
def logged(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"auth-observe.sqlite")
    monkeypatch.setattr(main,"SETUP_TOKEN","observe-setup-token")
    main.failed_logins.clear()
    with TestClient(main.app) as client:
        registration=client.post("/api/auth/setup",json={
            "setup_token":"observe-setup-token","username":"admin",
            "password":"long-password-for-tests-12345"})
        assert registration.status_code==200,registration.text
        yield client,registration.json()["csrf"]


def test_observability_is_authenticated(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"unauth-observe.sqlite")
    with TestClient(main.app) as client:
        assert client.get("/api/observability/overview").status_code==401
        assert client.get("/api/observability/trends/host?hours=720").status_code==401


def test_observability_api_and_invalid_ranges(logged,monkeypatch):
    client,_=logged
    async def fake(method,path,timeout=20,body=None):
        if path=="/v1/snapshot":
            return {"hostname":"fedora","cpu":{"percent":18},
                    "memory":{"percent":25},"disks":[]}
        if path=="/v1/docker/inventory": return inventory()
        if path=="/v1/extras/postgres":
            return {"available":True,"items":[]}
        if path=="/v1/alerts/status": return {"rules":{"enabled":False},"incidents":[]}
        if path=="/v1/backup/status": return {"configured":False}
        raise AssertionError(path)
    monkeypatch.setattr(main,"agent_request",fake)
    response=client.get("/api/observability/overview")
    assert response.status_code==200,response.text
    assert response.json()["counts"]["containers"]==4
    assert response.json()["topology"]["links"]
    assert client.get("/api/observability/trends/host?hours=777").status_code==422
    assert client.get("/api/observability/trends/host?hours=720").status_code==200
