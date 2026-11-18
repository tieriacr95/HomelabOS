"""Phase D regression: encrypted backup, explicit targets, safe staging and locks."""
import json
import os
import sqlite3
import stat
import tarfile
from pathlib import Path

import pytest

from agent import backup_manager as bm


def private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config = tmp_path/"config"
    config.mkdir()
    state=tmp_path/"state"
    repo=tmp_path/"restic-repository"
    pwd=config/"password"
    private(pwd,"a-strong-password-file\n")
    private(config/"backup.env",f"RESTIC_REPOSITORY={repo}\nRESTIC_PASSWORD_FILE={pwd}\n")
    private(config/"backup.json",json.dumps({
        "sources":[{"name":"homelab","type":"homelab"}],
        "retention":{"daily":7,"weekly":4,"monthly":6}
    }))
    monkeypatch.setattr(bm,"CONFIG_DIR",config)
    monkeypatch.setattr(bm,"CREDENTIALS",config/"backup.env")
    monkeypatch.setattr(bm,"TARGETS",config/"backup.json")
    monkeypatch.setattr(bm,"STATE_DIR",state)
    monkeypatch.setattr(bm,"LOCK",state/"backup.lock")
    monkeypatch.setattr(bm,"JOBS",state/"jobs.json")
    monkeypatch.setattr(bm.shutil,"which",lambda name:"/usr/bin/restic")
    monkeypatch.setattr(bm,"_ACTIVE",None)
    monkeypatch.setattr(bm,"_RUNNING",{})
    return config,state,repo


def test_requires_explicit_configuration_and_private_secrets(configured):
    config,_,_=configured
    selected, error=bm.settings()
    assert error is None
    assert selected["sources"]==[{"name":"homelab","type":"homelab"}]
    (config/"backup.env").chmod(0o644)
    selected,error=bm.settings()
    assert selected is None and error is not None


def test_no_arbitrary_target_types(configured):
    config,_,_=configured
    private(config/"backup.json",json.dumps({
        "sources":[{"name":"attack","type":"command","path":"/etc/shadow"}]}))
    assert bm.settings()[0] is None


def test_retention_policy_rejects_unbounded(configured):
    config,_,_=configured
    private(config/"backup.json",json.dumps({
        "sources":[{"name":"homelab","type":"homelab"}],
        "retention":{"daily":999999,"weekly":4,"monthly":6}}))
    assert bm.settings()[0] is None


def test_operation_confirmation_fails_before_running(configured,monkeypatch):
    called=[]
    monkeypatch.setattr(bm,"backup",lambda:called.append("backup"))
    with pytest.raises(PermissionError):
        bm.start("backup","wrong",background=False)
    with pytest.raises(PermissionError):
        bm.start("verify","wrong",background=False)
    with pytest.raises(ValueError):
        bm.start("prune","EJECUTAR RESPALDO",background=False)
    assert not called


def test_lock_prevents_overlapping_tasks(configured):
    first=bm._take_lock()
    try:
        with pytest.raises(bm.BackupError):
            bm._take_lock()
    finally:
        first.close()


def test_no_live_writes_in_restore_flow(configured,monkeypatch):
    config,state,_=configured
    snapshot_id="a"*64
    monkeypatch.setattr(bm,"snapshots",lambda:[{"id":snapshot_id}])
    def restic(args,timeout=0,max_output=80000):
        if args[1]=="restore":
            target=Path(args[args.index("--target")+1])
            restored=target/"home/user/work/run-1"
            restored.mkdir(parents=True)
            db=restored/"homelabos/homelabos.db"
            db.parent.mkdir()
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE demo(id INTEGER PRIMARY KEY)")
            (restored/"manifest.json").write_text(json.dumps({
                "resources":[{"type":"homelab","name":"homelab",
                              "file":"homelabos/homelabos.db"}]}))
        return ""
    monkeypatch.setattr(bm,"_run",restic)
    result=bm.restore(snapshot_id)
    assert not result["live_data_modified"]
    assert Path(result["destination"]).is_dir()
    assert str(Path(result["destination"])).startswith(str(state/"restores"))


def test_recovery_refuses_missing_or_bad_manifest(configured,monkeypatch):
    monkeypatch.setattr(bm,"snapshots",lambda:[{"id":"b"*64}])
    monkeypatch.setattr(bm,"_run",lambda *args,**kwargs:"")
    with pytest.raises(bm.BackupError):
        bm.restore("b"*64)
    with pytest.raises(bm.BackupError):
        bm.restore("../production")


def test_volume_tar_safety(configured,tmp_path):
    import io
    ok=tmp_path/"safe.tar"
    with tarfile.open(ok,"w") as tar:
        info=tarfile.TarInfo("project/index.txt")
        data=b"hello"
        info.size=len(data)
        tar.addfile(info,io.BytesIO(data))
    bm._safe_archive(ok)
    bad=tmp_path/"danger.tar"
    with tarfile.open(bad,"w") as tar:
        info=tarfile.TarInfo("../danger.txt")
        tar.addfile(info)
    with pytest.raises(bm.BackupError):
        bm._safe_archive(bad)


def test_staged_backup_retention_is_scoped_to_homelab(configured,monkeypatch):
    calls=[]
    monkeypatch.setattr(bm,"_prepare_stage",lambda stage,conf:{"resources":[{"name":"homelab"}]})
    monkeypatch.setattr(bm,"_run",lambda args, **kw: calls.append(args) or "")
    result=bm.backup()
    assert result["encrypted"] and result["retention_applied"]
    assert calls[0][:2]==["restic","backup"]
    assert calls[1][:2]==["restic","forget"]
    assert calls[1][calls[1].index("--tag")+1]=="homelabos"
    assert "--prune" in calls[1]


def test_jobs_store_no_password_or_raw_export(configured,monkeypatch):
    monkeypatch.setattr(bm,"backup",lambda:{"encrypted":True,"resources":2})
    job=bm.start("backup","EJECUTAR RESPALDO",background=False)
    assert job["state"]=="success"
    jobs=bm.jobs()
    assert jobs[0]["id"]==job["id"]
    assert "password" not in str(jobs).lower()
    assert "pg_dump" not in str(jobs).lower()
