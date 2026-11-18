"""Real restic encrypted round-trip smoke test; runs only when restic installed."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from agent import backup_manager as bm


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic not installed")
def test_real_encrypted_snapshot_verify_and_staged_recovery(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="homelab-restic-ci-", dir=Path.home()) as root_dir:
        root=Path(root_dir)
        config=root/"config"
        config.mkdir(mode=0o700)
        state=root/"state"
        repository=root/"repository"
        target=root/"project-files"
        target.mkdir()
        (target/"important.txt").write_text("Recovery proof from a real encrypted restic snapshot\n")

        password=config/"password"
        password.write_text("strong-separate-ci-key\n")
        password.chmod(0o600)
        credentials=config/"backup.env"
        credentials.write_text(f"RESTIC_REPOSITORY={repository}\nRESTIC_PASSWORD_FILE={password}\n")
        credentials.chmod(0o600)
        targets=config/"backup.json"
        targets.write_text(json.dumps({
            "sources":[{"type":"directory","name":"project","path":str(target)}],
            "retention":{"daily":7,"weekly":4,"monthly":6}
        }))
        targets.chmod(0o600)

        monkeypatch.setattr(bm,"CONFIG_DIR",config)
        monkeypatch.setattr(bm,"CREDENTIALS",credentials)
        monkeypatch.setattr(bm,"TARGETS",targets)
        monkeypatch.setattr(bm,"STATE_DIR",state)
        monkeypatch.setattr(bm,"LOCK",state/"backup.lock")
        monkeypatch.setattr(bm,"JOBS",state/"jobs.json")
        bm._secure_dir(state)

        assert subprocess.run(["restic", "init"],env=bm._restic_env(),
                              check=False,capture_output=True,timeout=60).returncode==0
        copied=bm.backup()
        assert copied["resources"]==1 and copied["encrypted"]
        snaps=bm.snapshots()
        assert len(snaps)==1 and len(snaps[0]["id"])>=8

        checked=bm.verify()
        assert checked["verified"] and checked["method"]=="restic check"

        restored=bm.restore(snaps[0]["id"])
        assert not restored["live_data_modified"]
        recovered=Path(restored["restored_root"])/"homelabos/directory-project/important.txt"
        assert recovered.read_text()=="Recovery proof from a real encrypted restic snapshot\n"
        assert (target/"important.txt").read_text()==recovered.read_text()
