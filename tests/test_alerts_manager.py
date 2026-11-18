"""Alerting state-machine tests: no duplicate storms, recovery and safe rules."""
import json
import sqlite3

import pytest

from agent import alerts_manager as am


@pytest.fixture
def configured(tmp_path,monkeypatch):
    config=tmp_path/"config"
    state=tmp_path/"state"
    config.mkdir(mode=0o700)
    monkeypatch.setattr(am,"CONFIG",config)
    monkeypatch.setattr(am,"RULES",config/"alerts.json")
    monkeypatch.setattr(am,"TELEGRAM",config/"telegram.json")
    monkeypatch.setattr(am,"STATE",state)
    monkeypatch.setattr(am,"DATABASE",state/"incidents.sqlite")
    monkeypatch.setattr(am,"LOCK",state/"monitor.lock")
    return config,state


def sample(state="fail"):
    return {"key":"containers:test-db-1","category":"containers","subject":"test-db-1",
            "title":"Contenedor test-db-1: "+state,"status":state,"severity":"critical"}


def test_defaults_disabled_and_strict_rule_validation(configured):
    current=am.rules()
    assert not current["enabled"] and not current["notify_telegram"]
    assert current["checks"]["postgres"]
    with pytest.raises(ValueError):
        am.validate_rules({**current,"enable_root_shell":True})
    with pytest.raises(ValueError):
        am.validate_rules({**current,"cooldown_minutes":0})
    with pytest.raises(ValueError):
        am.validate_rules({**current,"thresholds":{**current["thresholds"],"cpu":-1}})
    with pytest.raises(ValueError):
        am.validate_rules({**current,"expected_containers":["name; rm -rf /"]})
    with pytest.raises(ValueError):
        am.validate_rules({**current,"notify_telegram":"yes"})


def test_rules_persist_privately_and_never_contain_telegram_token(configured):
    current=am.rules()
    current["enabled"]=True
    current["expected_containers"]=["plex","planner-db-1","plex"]
    applied=am.set_rules(current)
    assert applied["expected_containers"]==["planner-db-1","plex"]
    assert am.RULES.stat().st_mode&0o077==0
    assert am.rules()["enabled"]
    assert "bot_token" not in am.RULES.read_text()


def test_two_failures_open_one_incident_then_recovery(configured,monkeypatch):
    current=am.rules()
    current.update(enabled=True,notify_telegram=True,cooldown_minutes=60)
    monkeypatch.setattr(am,"telegram_status",lambda:{"configured":True})
    sent=[]
    notify=lambda text:sent.append(text)
    r=am.record_results([sample("fail")],current,now=10000,sender=notify)
    assert r["notifications"]==0
    assert am.summary()["incidents"]==[]
    r=am.record_results([sample("fail")],current,now=10120,sender=notify)
    assert r["notifications"]==1
    assert len(am.summary()["incidents"])==1
    assert len(sent)==1
    r=am.record_results([sample("fail")],current,now=10360,sender=notify)
    assert r["notifications"]==0
    assert len(sent)==1
    r=am.record_results([sample("ok")],current,now=10480,sender=notify)
    assert r["notifications"]==1
    assert len(sent)==2
    assert am.summary()["incidents"]==[]
    events=am.summary()["events"]
    assert any(e["event"]=="recovered" for e in events)


def test_muted_and_acknowledged_incidents_do_not_repeat(configured,monkeypatch):
    conf=am.rules()
    conf.update(notify_telegram=True,consecutive_failures=1,cooldown_minutes=5)
    monkeypatch.setattr(am,"telegram_status",lambda:{"configured":True})
    messages=[]
    am.record_results([sample()],conf,now=10000,sender=messages.append)
    assert len(messages)==1
    iid=am.summary()["incidents"][0]["id"]
    assert am.incident_action(iid,"silence",60)["ok"]
    am.record_results([sample()],conf,now=10000+360,sender=messages.append)
    assert len(messages)==1
    am.incident_action(iid,"unsilence")
    am.incident_action(iid,"acknowledge")
    am.record_results([sample()],conf,now=11000,sender=messages.append)
    assert len(messages)==1
    with pytest.raises(ValueError):
        am.incident_action(iid,"silence",0)


def test_telegram_failure_is_retryable_and_no_token_leaked(configured,monkeypatch):
    conf=am.rules()
    conf.update(notify_telegram=True,consecutive_failures=1)
    monkeypatch.setattr(am,"telegram_status",lambda:{"configured":True})
    def fail(msg):
        raise am.AlertError("Telegram delivery failed")
    result=am.record_results([sample()],conf,now=10000,sender=fail)
    assert result["notifications"]==0
    assert len(am.summary()["incidents"])==1
    sent=[]
    result=am.record_results([sample()],conf,now=10120,sender=sent.append)
    assert result["notifications"]==1
    assert len(sent)==1


def test_unknown_never_opens_or_closes(configured,monkeypatch):
    conf=am.rules()
    conf["consecutive_failures"]=1
    am.record_results([sample("unknown")],conf,now=11000)
    assert not am.summary()["incidents"]
    am.record_results([sample()],conf,now=11200)
    assert len(am.summary()["incidents"])==1
    am.record_results([sample("unknown")],conf,now=11300)
    assert len(am.summary()["incidents"])==1


def test_disconnected_docker_is_unknown_not_mass_outage(configured,monkeypatch):
    conf=am.rules()
    conf["expected_containers"]=["plex","finance-os-db-1"]
    monkeypatch.setattr(am.docker_manager,"inventory",
                        lambda:{"connected":False,"error":"unreachable"})
    for key in ("cpu","memory","disk","temperature","postgres"):
        conf["checks"][key]=False
    result=am.collect_host(conf)
    assert len(result)==1
    assert result[0]["status"]=="unknown"
    assert result[0]["category"]=="containers"


def test_no_automatic_changes_in_monitoring(configured,monkeypatch):
    conf=am.rules()
    conf["enabled"]=False
    assert am.poll()=={"enabled":False,"inspected":0,"notifications":0}
    assert not am.DATABASE.exists()


def test_private_telegram_rejects_bad_credentials(configured):
    with pytest.raises(am.AlertError):
        am.test_telegram()
    am._write_private(am.TELEGRAM,{"bot_token":"bad-token","chat_id":"1234"})
    assert am.telegram_status()["configured"] is False
    assert "bad-token" not in str(am.telegram_status())


def test_backup_verification_failures_create_monitor_signal(configured,monkeypatch):
    config=am.rules()
    records=[
        {"operation":"verify","state":"failed","finished":10002},
        {"operation":"backup","state":"success","finished":10000},
    ]
    monkeypatch.setattr(am.backup_manager,"status",lambda:{"configured":True,"jobs":records})
    monkeypatch.setattr(am.time,"time",lambda:11000)
    signals=am._backup_checks(config)
    assert any(x["key"]=="backup:verification" and x["status"]=="fail" for x in signals)
    assert any(x["key"]=="backup:freshness" and x["status"]=="ok" for x in signals)


def test_maintenance_timer_status_exposed_only_as_boolean(configured,monkeypatch):
    monkeypatch.setattr(am,"_timer_active",
        lambda name="homelabos-alerts.timer":name=="homelabos-maintenance.timer")
    result=am.summary()
    assert result["timer"] is False
    assert result["maintenance_timer"] is True
    assert "bot_token" not in str(result)


def test_telegram_error_codes_do_not_expose_bot_token(configured, monkeypatch):
    from urllib.error import HTTPError
    token = "123456789:" + "a" * 35
    am._write_private(am.TELEGRAM, {"bot_token": token, "chat_id": "123456"})
    def http_error(req, timeout):
        raise HTTPError(req.full_url, 403, "Forbidden", {}, None)
    monkeypatch.setattr(am.urllib.request, "urlopen", http_error)
    with pytest.raises(am.AlertError) as exc:
        am.test_telegram()
    assert str(exc.value) == "telegram_chat_forbidden"
    assert token not in str(exc.value)
    assert token not in str(am.telegram_status())


def test_telegram_invalid_token_returns_safe_code(configured, monkeypatch):
    from urllib.error import HTTPError
    token = "123456789:" + "b" * 35
    am._write_private(am.TELEGRAM, {"bot_token": token, "chat_id": "123456"})
    def bad_token(req, timeout):
        raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(am.urllib.request, "urlopen", bad_token)
    with pytest.raises(am.AlertError, match="^telegram_invalid_token$"):
        am.test_telegram()


def test_telegram_network_failure_is_sanitized(configured, monkeypatch):
    from urllib.error import URLError
    token = "123456789:" + "b" * 35
    am._write_private(am.TELEGRAM, {"bot_token": token, "chat_id": "123456"})
    monkeypatch.setattr(am.urllib.request, "urlopen",
                        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("https://api.telegram.org/bot"+token)))
    with pytest.raises(am.AlertError) as exc:
        am.test_telegram()
    assert str(exc.value) == "telegram_network_error"
    assert token not in str(exc.value)


def test_telegram_status_rejects_non_object_json(configured):
    am._write_private(am.TELEGRAM, ["not", "credentials"])
    result = am.telegram_status()
    assert result["configured"] is False
    assert "JSON" in result["error"]
