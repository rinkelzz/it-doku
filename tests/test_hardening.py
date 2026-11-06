"""Härtung: CSRF, Proxy-Schlüssel, CSV-Formeln, Login-Sperre, HTTP-Hinweis, Rechte."""
import os

import pytest
from fastapi.testclient import TestClient

from app import csvsafe, dsm_auth
from app.main import app

LOCAL = ("127.0.0.1", 50000)


@pytest.fixture(scope="module")
def admin():
    with TestClient(app, base_url="https://zeit.example.de") as c:
        assert c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["ITD_ADMIN_PASSWORD"]}).status_code == 200
        yield c


@pytest.fixture(scope="module")
def emp(admin):
    r = admin.post("/api/v1/users", json={"username": "harti", "display_name": "=1+2", "password": "geheim123"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    with TestClient(app, base_url="https://zeit.example.de") as c:
        assert c.post("/api/v1/auth/login", json={"username": "harti", "password": "geheim123"}).status_code == 200
        yield {"c": c, "uid": uid}


# --- CSRF --------------------------------------------------------------------

def test_csrf_cross_site_blocked(emp):
    c = emp["c"]
    for h in ({"Sec-Fetch-Site": "cross-site"},
              {"Origin": "https://evil.example"},
              {"Origin": "null"},
              {"Sec-Fetch-Site": "same-site", "Origin": "https://blog.example.de"},
              {"Referer": "https://evil.example/seite"}):
        r = c.patch("/api/v1/me", content=b'{"display_name": "Gehackt"}', headers={"Content-Type": "text/plain", **h})
        assert r.status_code == 403, h
        assert "fremden Webseite" in r.json()["detail"]
    # Lesen bleibt erlaubt (ändert nichts)
    assert c.get("/api/v1/me", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
    assert c.get("/api/v1/me").json()["display_name"] == "=1+2"


def test_csrf_own_page_allowed(emp):
    c = emp["c"]
    body = {"display_name": "=1+2"}
    assert c.patch("/api/v1/me", json=body, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert c.patch("/api/v1/me", json=body, headers={"Origin": "https://zeit.example.de"}).status_code == 200
    assert c.patch("/api/v1/me", json=body).status_code == 200          # ohne Origin (Werkzeuge wie curl)
    # eigener Header → kein CSRF-Fall (eine fremde Seite kann ihn nicht setzen); ungültiges Token → 401
    assert c.patch("/api/v1/me", json=body, headers={"Origin": "https://evil.example",
                                                      "X-Session-Token": "egal"}).status_code in (200, 401)


def test_csrf_public_url_and_forwarded_host(emp, monkeypatch):
    from app.config import settings
    c = emp["c"]
    # hinter dem Reverse Proxy kommt oft Host: localhost:8780 an – dann zählt X-Forwarded-Host bzw. die öffentliche Adresse
    h = {"Host": "localhost:8780", "Origin": "https://zeit.meine.de"}
    body = {"display_name": "=1+2"}
    assert c.patch("/api/v1/me", json=body, headers=h).status_code == 403
    assert c.patch("/api/v1/me", json=body, headers={**h, "X-Forwarded-Host": "zeit.meine.de"}).status_code == 200
    monkeypatch.setattr(settings, "public_url", "https://zeit.meine.de")
    assert c.patch("/api/v1/me", json=body, headers=h).status_code == 200


# --- Proxy-Schlüssel nur von der NAS selbst -----------------------------------

def test_proxy_secret_only_from_loopback(admin):
    h = {"X-ITD-Proxy-Secret": dsm_auth.proxy_secret(), "X-DSM-User": "admin", "X-DSM-Admin": "1"}
    with TestClient(app, client=("8.8.8.8", 5000)) as c:
        assert c.get("/api/v1/me", headers=h).status_code == 401
    with TestClient(app, client=("192.168.1.20", 5000)) as c:
        assert c.get("/api/v1/me", headers=h).status_code == 401
    with TestClient(app, client=LOCAL) as c:
        assert c.get("/api/v1/me", headers=h).json()["via_dsm"] is True
        # über den Reverse Proxy durchgereicht (auch 127.0.0.1, aber mit X-Forwarded-For) → zählt nicht
        assert c.get("/api/v1/me", headers={**h, "X-Forwarded-For": "8.8.8.8"}).status_code == 401
        # falscher Schlüssel
        assert c.get("/api/v1/me", headers={**h, "X-ITD-Proxy-Secret": "x" * 43}).status_code == 401


# --- Rechte: Mitarbeiter sind keine Admins -----------------------------------

def test_member_cannot_admin(admin, emp):
    admin.patch("/api/v1/settings", json={"smtp_host": "mail.example.de", "smtp_password": "geheim"})
    c = emp["c"]
    for method, path in (("GET", "/api/v1/users"), ("GET", "/api/v1/backups"), ("GET", "/api/v1/audit"),
                         ("PATCH", "/api/v1/settings"), ("POST", "/api/v1/settings/port"), ("GET", "/api/v1/updates"),
                         ("PATCH", "/api/v1/branding"), ("POST", "/api/v1/users")):
        assert c.request(method, path, json={}).status_code in (403, 422), (method, path)
    s = c.get("/api/v1/settings").json()
    assert not [k for k in s if k.startswith("smtp_")] and "dsm_url" not in s
    full = admin.get("/api/v1/settings").json()
    assert full["smtp_host"] == "mail.example.de" and full["smtp_password_set"] is True
    assert "smtp_password" not in full  # Passwort wird nie ausgeliefert


# --- CSV/Excel: keine Formeln aus Freitext ------------------------------------

def test_csvsafe_cell():
    assert csvsafe.cell('=HYPERLINK("x")') == "'=HYPERLINK(\"x\")"
    assert csvsafe.cell("+49 30 123") == "'+49 30 123"
    assert csvsafe.cell("@SUM(A1)") == "'@SUM(A1)"
    assert csvsafe.cell("-0:14") == "-0:14" and csvsafe.cell("-1,5") == "-1,5" and csvsafe.cell("-10 min") == "-10 min"
    assert csvsafe.cell("-cmd|' /C calc'!A0") == "'-cmd|' /C calc'!A0"
    assert csvsafe.cell("Urlaub") == "Urlaub" and csvsafe.cell(5) == 5 and csvsafe.cell(None) is None


def test_csv_exports_neutralized(admin, emp):
    log = admin.get("/api/v1/audit/export.csv").text
    assert "'=1+2" in log  # Name des Benutzers „=1+2“ steht entschärft drin
    for line in log.splitlines()[1:]:
        for cell in line.split(";"):
            assert not cell.startswith(("=", "+", "@")), line


# --- Login-Sperre: Speicher bleibt begrenzt -----------------------------------

def test_fail_table_bounded(monkeypatch):
    monkeypatch.setattr(dsm_auth, "MAX_KEYS", 50)
    dsm_auth._fails.clear()
    try:
        dsm_auth.note_failure("opfer")
        for i in range(300):
            dsm_auth.note_failure(f"name{i}")
        assert len(dsm_auth._fails) <= 51
        # abgelaufene Einträge fliegen zuerst raus
        dsm_auth._fails.clear()
        dsm_auth._fails["alt"] = [0.0]
        for i in range(60):
            dsm_auth.note_failure(f"n{i}")
        assert "alt" not in dsm_auth._fails
    finally:
        dsm_auth._fails.clear()


# --- Hinweis bei http aus dem Internet ----------------------------------------

def test_insecure_http_flag():
    with TestClient(app, client=("8.8.8.8", 5000)) as c:
        c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["ITD_ADMIN_PASSWORD"]})
        assert c.get("/api/v1/me").json()["insecure_http"] is True
    for ip in ("192.168.178.20", "10.0.0.5", "100.101.102.103"):
        with TestClient(app, client=(ip, 5000)) as c:
            c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["ITD_ADMIN_PASSWORD"]})
            assert c.get("/api/v1/me").json()["insecure_http"] is False, ip
    with TestClient(app, base_url="https://zeit.example.de", client=("8.8.8.8", 5000)) as c:
        c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["ITD_ADMIN_PASSWORD"]})
        assert c.get("/api/v1/me").json()["insecure_http"] is False
