"""Alert API: authenticated reads, CSRF, strict rule update and audit."""
import pytest
from fastapi.testclient import TestClient
from app import main,store
from agent import alerts_manager as am


@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"api.sqlite")
    monkeypatch.setattr(main,"SETUP_TOKEN","alert-setup-token")
    main.failed_logins.clear()
    with TestClient(main.app) as client:
        response=client.post("/api/auth/setup",json={
            "setup_token":"alert-setup-token","username":"admin",
            "password":"very-strong-test-password-1234"})
        assert response.status_code==200
        yield client,response.json()["csrf"]


def test_alert_endpoints_require_session(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"unauthed.sqlite")
    with TestClient(main.app) as client:
        assert client.get("/api/alerts/status").status_code==401
        assert client.get("/api/alerts/rules").status_code==401
        assert client.put("/api/alerts/rules",json={"rules":am.default_rules()}).status_code==401
        assert client.post("/api/alerts/check",json={"confirm":True}).status_code==401


def test_rules_changes_require_csrf_and_are_audited(session,monkeypatch):
    client,csrf=session
    actions=[]
    async def relay(method,path,body=None,timeout=35):
        actions.append((method,path,body))
        return body["rules"] if body else am.default_rules()
    monkeypatch.setattr(main,"agent_request",relay)
    rules=am.default_rules()
    rules["enabled"]=True
    assert client.put("/api/alerts/rules",json={"rules":rules}).status_code==403
    good=client.put("/api/alerts/rules",headers={"X-CSRF-Token":csrf},
                    json={"rules":rules})
    assert good.status_code==200
    assert good.json()["enabled"]
    assert actions==[("POST","/v1/alerts/rules",{"rules":rules})]
    assert any(a["action"]=="alerts_rules" for a in client.get("/api/audit").json()["items"])


def test_manual_checks_and_telegram_test_explicit(session,monkeypatch):
    client,csrf=session
    calls=[]
    async def relay(method,path,body=None,timeout=35):
        calls.append((path,body))
        return {"inspected":3}
    monkeypatch.setattr(main,"agent_request",relay)
    for endpoint in ("check","telegram/test"):
        assert client.post("/api/alerts/"+endpoint,headers={"X-CSRF-Token":csrf},
                           json={"confirm":False}).status_code==400
        assert client.post("/api/alerts/"+endpoint,
                           json={"confirm":True}).status_code==403
        good=client.post("/api/alerts/"+endpoint,headers={"X-CSRF-Token":csrf},
                         json={"confirm":True})
        assert good.status_code==200
    assert calls==[("/v1/alerts/check",{"confirm":True}),
                   ("/v1/alerts/telegram/test",{"confirm":True})]


def test_incident_action_restricted(session,monkeypatch):
    client,csrf=session
    sent=[]
    async def relay(method,path,body=None,timeout=35):
        sent.append((method,path,body))
        return {"ok":True}
    monkeypatch.setattr(main,"agent_request",relay)
    url="/api/alerts/incidents/15/silence"
    assert client.post(url,headers={"X-CSRF-Token":csrf},
                       json={"minutes":1}).status_code==422
    assert client.post("/api/alerts/incidents/15/delete",headers={"X-CSRF-Token":csrf},
                       json={"minutes":60}).status_code==422
    assert not sent
    good=client.post(url,headers={"X-CSRF-Token":csrf},
                     json={"minutes":60})
    assert good.status_code==200
    assert sent[0]==("POST","/v1/alerts/incidents/15/silence",{"minutes":60})


def test_telegram_failure_returns_safe_actionable_explanation(session,monkeypatch):
    import httpx
    client,csrf=session
    request=httpx.Request("POST","http://127.0.0.1:18765/v1/alerts/telegram/test")
    response=httpx.Response(409,request=request,json={"error":"telegram_chat_forbidden"})
    async def relay(method,path,body=None,timeout=35):
        raise httpx.HTTPStatusError("Rejected",request=request,response=response)
    monkeypatch.setattr(main,"agent_request",relay)
    result=client.post("/api/alerts/telegram/test",
         headers={"X-CSRF-Token":csrf},json={"confirm":True})
    assert result.status_code==409
    assert "/start" in result.json()["detail"]


def test_telegram_never_relays_unknown_error_messages(session,monkeypatch):
    import httpx
    client,csrf=session
    secret="example-secret-do-not-leak"
    request=httpx.Request("POST","http://127.0.0.1:18765/v1/alerts/telegram/test")
    response=httpx.Response(409,request=request,json={"error":secret})
    async def relay(method,path,body=None,timeout=35):
        raise httpx.HTTPStatusError("Rejected",request=request,response=response)
    monkeypatch.setattr(main,"agent_request",relay)
    result=client.post("/api/alerts/telegram/test",
         headers={"X-CSRF-Token":csrf},json={"confirm":True})
    assert result.status_code==409
    assert secret not in result.text
    assert "Operación rechazada" in result.text
