"""Weekly maintenance runner only delegates to the approved verification workflow."""
from agent import maintenance_runner as runner


def test_maintenance_runner_invokes_only_backup_verification(monkeypatch):
    calls=[]
    def action(operation,phrase,background):
        calls.append((operation,phrase,background))
        return {"id":"test","state":"success"}
    monkeypatch.setattr(runner.backup_manager,"start",action)
    assert runner.run()==0
    assert calls==[("verify","VERIFICAR RESPALDOS",False)]


def test_maintenance_runner_reports_errors(monkeypatch):
    monkeypatch.setattr(runner.backup_manager,"start",
        lambda *args, **kwargs:{"id":"test","state":"failed"})
    assert runner.run()==1
