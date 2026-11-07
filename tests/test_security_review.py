"""0.8.4: Befunde aus dem Sicherheits-Review (DSM-SSO, http, DSM-Adminrechte, DSM-Adresse, Login-Sperre)."""
import grp
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app import dsm_auth, httpguard, proxy
from app.config import settings
from app.db import connect
from app.main import app

PW = os.environ["ITD_ADMIN_PASSWORD"]
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture()
def admin():
    dsm_auth._fails.clear()
    with TestClient(app, client=LOCAL) as c:
        assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
        yield c
        c.patch("/api/v1/settings", json={"dsm_login": True, "dsm_auto_create": False, "dsm_admins": True, "dsm_sso": True})
    dsm_auth._fails.clear()


def sso(user):
    return {"X-ITD-Proxy-Secret": dsm_auth.proxy_secret(), "X-ITD-Proxy-Base": "app.cgi", "X-DSM-User": user, "X-DSM-Admin": "1"}


def test_admin_header_is_ignored_and_revoked(admin, monkeypatch):
    dsm_admins = {"rev_chef"}
    monkeypatch.setattr(dsm_auth, "_is_dsm_admin", lambda u: u in dsm_admins)
    dsm_auth._admin_cache.clear()
    with TestClient(app, client=LOCAL) as c:
        # Header behauptet Admin – DSM sagt nein → kein Zugang (unbekannt) bzw. nur Lesen
        assert c.get("/api/v1/me", headers=sso("rev_mitarbeiter")).status_code == 403
        me = c.get("/api/v1/me", headers=sso("rev_chef")).json()
        assert me["is_admin"] is True
        # In DSM nicht mehr Administrator → beim nächsten Zugriff Vollzugriff weg
        dsm_admins.clear()
        dsm_auth._admin_cache.clear()
        me = c.get("/api/v1/me", headers=sso("rev_chef")).json()
        assert me["is_admin"] is False
        # Wieder Admin, dann „DSM-Admins bekommen Vollzugriff“ ausschalten → sofort weg
        dsm_admins.add("rev_chef")
        dsm_auth._admin_cache.clear()
        assert c.get("/api/v1/me", headers=sso("rev_chef")).json()["is_admin"] is True
    admin.patch("/api/v1/settings", json={"dsm_admins": False})
    conn = connect()
    assert conn.execute("SELECT is_admin FROM users WHERE username = 'rev_chef'").fetchone()[0] == 0
    # von Hand vergebener Vollzugriff bleibt
    uid = admin.post("/api/v1/users", json={"username": "rev_hand", "display_name": "Hand", "is_admin": True}).json()["id"]
    admin.patch("/api/v1/settings", json={"dsm_admins": True})
    admin.patch("/api/v1/settings", json={"dsm_admins": False})
    assert conn.execute("SELECT is_admin FROM users WHERE id = ?", (uid,)).fetchone()[0] == 1
    log = str(admin.get("/api/v1/audit").json())
    assert "Vollzugriff entzogen" in log or "Vollzugriff aus DSM entzogen" in log


def test_dsm_url_only_dsm_ports(monkeypatch):
    monkeypatch.delenv("ITD_DSM_PORTS", raising=False)
    ok = ["http://127.0.0.1:5000", "https://127.0.0.1:5001", "https://localhost:5001"]
    bad = ["http://127.0.0.1:8080", "http://127.0.0.1", "https://127.0.0.1", "http://127.0.0.1:5001", "https://127.0.0.1:5000",
           "http://127.0.0.1:8780"]
    for u in ok:
        assert dsm_auth.local_dsm_url(u) == u, u
    for u in bad:
        assert dsm_auth.local_dsm_url(u) is None, u
    monkeypatch.setenv("ITD_DSM_PORTS", "5080")
    assert dsm_auth.local_dsm_url("http://127.0.0.1:5080") == "http://127.0.0.1:5080"


def test_limiter_bounded_and_per_ip():
    dsm_auth._fails.clear()
    for i in range(1000):
        assert not dsm_auth.too_many_attempts(f"name{i}|1.2.3.4")
    assert len(dsm_auth._fails) == 0  # Nachsehen legt nichts an
    with TestClient(app, client=("192.168.1.77", 1)) as c:
        codes = [c.post("/api/v1/auth/login", json={"username": f"spray{i}", "password": "x"}).status_code for i in range(32)]
    assert codes[:30] == [401] * 30 and codes[30] == 429  # viele Namen von einer Adresse
    with TestClient(app, client=("192.168.1.78", 1)) as c:
        assert c.post("/api/v1/auth/login", json={"username": "spray99", "password": "x"}).status_code == 401
    dsm_auth._fails.clear()


def test_http_guard(admin, monkeypatch):
    monkeypatch.delenv("ITD_HTTP_ACCESS", raising=False)
    httpguard.configure("0")
    try:
        with TestClient(app, client=("192.168.1.20", 1)) as c:
            r = c.get("/")
            assert r.status_code == 403 and "https" in r.text
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 403
            assert c.get("/api/v1/health").status_code == 200
            assert c.get("/agent/itdoku-agent.py").status_code == 200
            assert c.post("/api/agent/v1/report", json={}).status_code == 401  # erreicht die App (Schlüssel fehlt)
        with TestClient(app, client=("192.168.1.20", 1), base_url="https://testserver") as c:
            assert c.get("/").status_code == 200
        # über eingetragenen Reverse Proxy mit https
        admin.put("/api/v1/settings/proxy", json={"trusted_proxies": "192.168.90.26"})
        with TestClient(app, client=("192.168.90.26", 1)) as c:
            assert c.get("/", headers={"X-Forwarded-For": "8.8.8.8", "X-Forwarded-Proto": "https"}).status_code == 200
            assert c.get("/", headers={"X-Forwarded-For": "8.8.8.8", "X-Forwarded-Proto": "http"}).status_code == 403
        assert admin.get("/").status_code == 200  # NAS selbst (DSM-Fenster)
        assert admin.patch("/api/v1/settings", json={"http_access": True}).status_code == 200
        with TestClient(app, client=("192.168.1.20", 1)) as c:
            assert c.get("/").status_code == 200
        admin.patch("/api/v1/settings", json={"http_access": False})
        with TestClient(app, client=("192.168.1.20", 1)) as c:
            assert c.get("/").status_code == 403
    finally:
        admin.put("/api/v1/settings/proxy", json={"trusted_proxies": ""})
        proxy.configure("")
        httpguard.configure("1")


def test_secret_file_permissions_and_sso_switch(admin, tmp_path, monkeypatch):
    ui = tmp_path / "ui"
    ui.mkdir()
    monkeypatch.setattr(settings, "ui_dir", str(ui))
    # Gruppe, in der der Testbenutzer ist, steht für „http“
    monkeypatch.setattr(dsm_auth, "WEB_GROUPS", (grp.getgrgid(os.getgid()).gr_name,))
    old = dsm_auth.proxy_secret()
    dsm_auth.rotate_secret()
    assert dsm_auth.proxy_secret() != old
    assert dsm_auth.publish_proxy_files(True) and dsm_auth.secret_mode == "group"
    f = tmp_path / ".proxy_secret"
    assert stat.S_IMODE(f.stat().st_mode) == 0o640 and f.read_text() == dsm_auth.proxy_secret()
    monkeypatch.setattr(dsm_auth, "WEB_GROUPS", ("gibt-es-nicht-xyz",))
    dsm_auth.publish_proxy_files(True)
    assert dsm_auth.secret_mode == "world" and stat.S_IMODE(f.stat().st_mode) == 0o644
    assert admin.get("/api/v1/settings").json()["dsm_secret_mode"] == "world"
    # SSO aus: Datei weg, Schlüssel zählt nicht mehr
    assert admin.patch("/api/v1/settings", json={"dsm_sso": False}).status_code == 200
    assert not f.exists()
    with TestClient(app, client=LOCAL) as c:
        assert c.get("/api/v1/me", headers=sso("admin")).status_code == 401
    admin.patch("/api/v1/settings", json={"dsm_sso": True})
    assert f.exists() and dsm_auth.secret_mode in ("group", "world")
