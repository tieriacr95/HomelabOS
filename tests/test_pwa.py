"""PWA only caches static assets; API routes remain authenticated and network-only."""
import json
from pathlib import Path

from fastapi.testclient import TestClient
from app import main, store


def test_pwa_manifest_and_sw_do_not_include_private_api_cache(tmp_path,monkeypatch):
    root=tmp_path/"public"
    root.mkdir()
    (root/"manifest.webmanifest").write_text(json.dumps({
        "id":"/","start_url":"/","display":"standalone","icons":[]}))
    (root/"sw.js").write_text(
        'const VERSION="homelabos-static-v0.6.5";\n'
        '// only assets, not /api/\n'
        'self.addEventListener("fetch",()=>{});')
    monkeypatch.setattr(main,"FRONTEND",root)
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"pwa.db")
    with TestClient(main.app) as client:
        manifest=client.get("/manifest.webmanifest")
        assert manifest.status_code==200
        assert manifest.json()["display"]=="standalone"
        script=client.get("/sw.js")
        assert script.status_code==200
        assert "application/javascript" in script.headers["content-type"]
        assert script.headers["cache-control"]=="no-cache"
        assert client.get("/api/dashboard").status_code==401
        assert client.get("/api/observability/overview").status_code==401


def test_source_service_worker_never_intercepts_navigation_or_private_api():
    source=Path(__file__).resolve().parent.parent/"frontend/pwa/sw.js"
    script=source.read_text(encoding="utf-8")
    assert 'request.mode === "navigate"' in script
    assert 'url.origin !== self.location.origin' in script
    assert 'event.respondWith' in script
    assert '"/assets/app.js"' in script
    assert '"/api/dashboard"' not in script
    assert 'caches.match(request)' in script
    assert 'assets\\/app' in script
