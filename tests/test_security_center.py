"""Security Center collector tests; all host commands and sockets are mocked."""
import socket
from types import SimpleNamespace

import pytest

from agent import security_center as sc


def test_selinux_configured_and_running_modes(monkeypatch, tmp_path):
    cfg=tmp_path/"config"
    cfg.write_text("# managed by Fedora\nSELINUX=enforcing\nSELINUXTYPE=targeted\n")
    def fake_read(path):
        if path == "/etc/selinux/config":
            return cfg.read_text()[:80]
        return None
    orig = sc.Path
    monkeypatch.setattr(sc, "Path", lambda p: cfg if p == "/etc/selinux/config" else orig(p))
    monkeypatch.setattr(sc, "run", lambda *a, **k: (0, "Permissive\n", ""))
    result = sc.selinux_status()
    assert result["mode"] == "permissive"
    assert result["configured"] == "enforcing"
    assert result["available"]


def test_firewall_zones_are_read_only_and_bounded(monkeypatch):
    calls=[]
    monkeypatch.setattr(sc, "_service_active", lambda name: "active")
    monkeypatch.setattr(sc.shutil, "which", lambda c: "/usr/bin/"+c)
    def fake(*cmd, **kw):
        calls.append(cmd)
        if cmd[-1] == "--state":
            return 0, "running\n", ""
        if cmd[-1] == "--get-active-zones":
            return 0, "public\n  interfaces: enp3s0\n  sources: 192.168.50.0/24\n", ""
        if cmd[-1] == "--list-services":
            return 0, "ssh mdns", ""
        if cmd[-1] == "--list-ports":
            return 0, "32400/tcp", ""
        raise AssertionError(cmd)
    monkeypatch.setattr(sc, "run", fake)
    r=sc.firewall_status()
    assert r["state"] == "running"
    assert r["zones"] == [{
        "name":"public", "interfaces":["enp3s0"],
        "sources":["192.168.50.0/24"], "services":["ssh","mdns"], "ports":["32400/tcp"]}]
    assert not any("--add" in str(item) or "--remove" in str(item) for item in calls)


def test_ssh_reports_only_effective_whitelisted_values(monkeypatch):
    monkeypatch.setattr(sc, "_service_active", lambda name: "active")
    monkeypatch.setattr(sc.shutil, "which", lambda c: "/usr/sbin/sshd")
    monkeypatch.setattr(sc, "run", lambda *cmd, **kw: (
        0, "permitrootlogin prohibit-password\npasswordauthentication yes\n"
        "pubkeyauthentication yes\nhostkey /etc/ssh/ssh_host_ed25519_key\n"
        "permitemptypasswords no\n", ""))
    result=sc.ssh_status()
    assert result["available"] and result["effective"]["passwordauthentication"] == "yes"
    assert "hostkey" not in result["effective"]
    assert result["sample"].startswith("root@localhost")


def test_ports_detect_bind_scope_without_claiming_public_access(monkeypatch):
    def sample(ip,port,kind=socket.SOCK_STREAM,pid=None):
        return SimpleNamespace(laddr=SimpleNamespace(ip=ip,port=port),
                               type=kind,status=sc.psutil.CONN_LISTEN,pid=pid)
    monkeypatch.setattr(sc.psutil, "net_connections", lambda kind:[
        sample("127.0.0.1",8091),sample("0.0.0.0",5432),
        sample("::",32400),sample("::1",18765),sample("192.168.50.1",3000)])
    result=sc.open_ports()
    assert result["available"] and result["total"] == 5
    assert result["non_loopback"] == 3
    assert {x["scope"] for x in result["items"]} == {"loopback","all","interface"}
    assert result["note"].startswith("Un socket escuchando")


def test_ports_access_denied_is_unknown_not_zero(monkeypatch):
    def deny(kind): raise sc.psutil.AccessDenied(pid=1)
    monkeypatch.setattr(sc.psutil, "net_connections", deny)
    result=sc.open_ports()
    assert not result["available"]
    assert result["non_loopback"] is None and result["total"] is None


def test_auth_events_only_return_aggregated_counts(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda c: "/usr/bin/journalctl")
    raw = ("Failed password for invalid user bob from 192.0.2.4\n"
           "Accepted publickey for admin from 192.0.2.7\n"
           "pam_unix(sudo:auth): authentication failure user=root\n")
    monkeypatch.setattr(sc, "run", lambda *a, **k:(0,raw,""))
    result=sc.auth_events()
    assert result["ssh_failed"] == 1
    assert result["ssh_accepted"] == 1
    assert result["sudo_failures"] == 1
    assert "bob" not in repr(result) and "192.0.2.4" not in repr(result)


def test_auth_events_permission_denied_is_not_zero(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda c: "/usr/bin/journalctl")
    monkeypatch.setattr(sc, "run", lambda *a, **k:(1,"","Permission denied"))
    result=sc.auth_events()
    assert result["available"] is False
    assert result["ssh_failed"] is None and result["ssh_accepted"] is None


def test_risk_findings_and_unknown_checks():
    report={
        "selinux":{"mode":"permissive","configured":"enforcing"},
        "firewall":{"state":"not-running"},
        "ssh":{"service":"active","available":True,
               "effective":{"permitrootlogin":"yes","passwordauthentication":"yes",
                            "permitemptypasswords":"no"}},
        "ports":{"items":[{"protocol":"tcp","scope":"all","port":2375,"address":"0.0.0.0"},
                          {"protocol":"tcp","scope":"loopback","port":5432,"address":"127.0.0.1"}]},
        "authentication":{"available":True,"ssh_failed":11},
        "kernel":{"aslr":"2"},
        "privileged_package_helper":False,
    }
    findings=sc.analyze(report)
    ids={x["id"] for x in findings}
    assert "selinux-permissive" in ids
    assert "ssh-root" in ids and "ssh-passwords" in ids
    assert "tcp-port-2375-0.0.0.0" in ids
    assert "ssh-failed-logins" in ids
    assert not any("5432" in x for x in ids)
    assert findings[0]["severity"]=="critical"
    report["ssh"]={"service":"unknown","available":False,"effective":{}}
    report["authentication"]={"available":False,"ssh_failed":None}
    findings=sc.analyze(report)
    assert not any(x["id"] in ("ssh-passwords","ssh-root","ssh-failed-logins") for x in findings)


def test_snapshot_cache_reuse(monkeypatch):
    monkeypatch.setattr(sc, "_REPORT_CACHE",{"at":0.0,"data":None})
    calls=[]
    monkeypatch.setattr(sc, "report",lambda:(calls.append(1) or {"summary":{"critical":0}}))
    assert sc.cached_report()==sc.cached_report()
    assert len(calls)==1
    sc.cached_report(refresh=True)
    assert len(calls)==2
