"""Image stage-only pulls must not recreate containers or bypass approvals."""
import pytest
from fastapi.testclient import TestClient
from app import main,store
from agent import image_updates as updates


def inventory(allowed=frozenset()):
    return {"connected":True,"containers":[
        {"name":"planner-web-1","state":"running",
         "image":"sample/web:1.2","critical_reason":"",
         "allowed_actions":["start"] if "planner-web-1" in allowed else []}]}


def fake_command(*argv,timeout=12,max_output=900000):
    if argv[0:3]==("docker","inspect","--type"):
        if argv[5]=="{{.Config.Image}}":
            return 0,"sample/web:1.2",""
        if argv[5]=="{{.Image}}":
            return 0,"sha256:"+"a"*64,""
    if argv[:3]==("docker","image","inspect"):
        return 0,"sha256:"+"b"*64,""
    if argv[:3]==("docker","pull","--quiet"):
        return 0,"",""
    raise AssertionError("Unexpected Docker command "+str(argv))


def test_only_allowlisted_image_can_be_previewed(monkeypatch):
    monkeypatch.setattr(updates.dm,"inventory",inventory)
    monkeypatch.setattr(updates.dm,"command",fake_command)
    with pytest.raises(PermissionError):
        updates.inspect_target("planner-web-1",frozenset())
    plan=updates.inspect_target("planner-web-1",{"planner-web-1"})
    assert plan["image"]=="sample/web:1.2"
    assert plan["requires_manual_redeploy"] is True
    assert plan["confirmation_phrase"]=="DESCARGAR IMAGEN planner-web-1"
    assert plan["running_image_id"]=="sha256:"+"a"*64
    with pytest.raises(PermissionError):
        updates.inspect_target("../escape",{"../escape"})


def test_staged_worker_pulls_only_and_does_not_restart(monkeypatch):
    monkeypatch.setattr(updates.dm,"inventory",inventory)
    calls=[]
    def run(*args,**kwargs):
        calls.append(args)
        return fake_command(*args,**kwargs)
    monkeypatch.setattr(updates.dm,"command",run)
    job={"id":"test","container":"planner-web-1","image":"sample/web:1.2",
         "running_image_id":"sha256:"+"a"*64,"state":"queued"}
    updates._worker(job,{"planner-web-1"})
    assert job["state"]=="success",job
    assert "requires_manual_redeploy" not in job or job["state"]=="success"
    assert any(args[1]=="pull" for args in calls)
    assert not any(args[1] in ("start","stop","restart","rm","compose","run")
                   for args in calls)


def test_pull_requires_exact_target_digest_and_phrase(monkeypatch):
    monkeypatch.setattr(updates.dm,"inventory",inventory)
    monkeypatch.setattr(updates.dm,"command",fake_command)
    with pytest.raises(PermissionError):
        updates.submit("planner-web-1","wrong","sha256:"+"a"*64,{"planner-web-1"})
    with pytest.raises(PermissionError):
        updates.submit("planner-web-1","DESCARGAR IMAGEN planner-web-1",
                       "sha256:"+"0"*64,{"planner-web-1"})


@pytest.fixture
def logged(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"image-auth.sqlite")
    monkeypatch.setattr(main,"SETUP_TOKEN","image-test-token")
    main.failed_logins.clear()
    with TestClient(main.app) as client:
        response=client.post("/api/auth/setup",json={"setup_token":"image-test-token",
            "username":"admin","password":"safe-password-for-tests-12345"})
        assert response.status_code==200
        yield client,response.json()["csrf"]


def test_image_pull_endpoints_authenticated_and_csrf(logged,monkeypatch):
    client,csrf=logged
    async def fake(method,path,body=None,timeout=35):
        if method=="GET":
            return {"confirmation_phrase":"DESCARGAR IMAGEN planner-web-1",
                    "running_image_id":"sha256:"+"a"*64}
        return {"state":"queued","id":"a"*32}
    monkeypatch.setattr(main,"agent_request",fake)
    url="/api/image-updates/planner-web-1/pull"
    body={"confirm":True,"confirmation_text":"DESCARGAR IMAGEN planner-web-1",
          "running_image_id":"sha256:"+"a"*64}
    assert client.post(url,json=body).status_code==403
    assert client.post(url,headers={"X-CSRF-Token":csrf},
                       json={**body,"confirmation_text":"wrong"}).status_code==403
    assert client.post(url,headers={"X-CSRF-Token":csrf},
                       json={**body,"running_image_id":"garbage"}).status_code==422
    result=client.post(url,headers={"X-CSRF-Token":csrf},json=body)
    assert result.status_code==200,result.text
    assert result.json()["state"]=="queued"
    assert client.get("/api/image-updates/planner-web-1/preview").status_code==200


def test_image_pull_anonymous_requests_denied(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"anon-image.sqlite")
    with TestClient(main.app) as client:
        assert client.get("/api/image-updates/jobs").status_code==401
        assert client.get("/api/image-updates/plex/preview").status_code==401
        assert client.post("/api/image-updates/plex/pull",json={
            "confirm":True,"confirmation_text":"DESCARGAR IMAGEN plex",
            "running_image_id":"sha256:"+"a"*64}).status_code==401
