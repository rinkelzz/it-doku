"""0.4: Fristen-Mail, Notfall-Handbuch, CSV-Import."""
import base64
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import deadlines, importer
from app.db import connect
from app.main import app
from app.timeutil import today_local

from .fresh import fresh_db

PW = os.environ["ITD_ADMIN_PASSWORD"]


@pytest.fixture()
def admin(tmp_path):
    with fresh_db(tmp_path, company="Physio Muster"):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def day(n):
    return (today_local() + timedelta(days=n)).isoformat()


# --- Fristen-Mail ---------------------------------------------------------------

@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(deadlines, "send_mail", lambda conn, to, subject, body, **kw: sent.append((to, subject, body)))
    return sent


def test_deadline_settings_and_send_now(admin, outbox):
    assert admin.patch("/api/v1/deadlines", json={"recipients": "tim@example.de, kaputt"}).status_code == 400
    cfg = admin.patch("/api/v1/deadlines", json={"recipients": "tim@example.de; praxis@example.de", "weekday": 2, "days": 60}).json()
    assert cfg["recipients"] == ["tim@example.de", "praxis@example.de"] and cfg["weekday"] == 2
    assert admin.post("/api/v1/deadlines/send-now").json()["message"].startswith("Gerade ist nichts fällig")
    admin.post("/api/v1/licenses", json={"name": "ESET", "expires_on": day(-3)})
    admin.post("/api/v1/licenses", json={"name": "M365", "expires_on": day(24), "term": "Abo, jährlich"})
    admin.post("/api/v1/licenses", json={"name": "Domain", "kind": "domain", "expires_on": day(80)})  # außerhalb 60 Tage
    assert [p["name"] for p in admin.get("/api/v1/deadlines").json()["preview"]] == ["ESET", "M365"]
    r = admin.post("/api/v1/deadlines/send-now").json()
    assert "2 Fristen" in r["message"] and len(outbox) == 2
    to, subject, body = outbox[0]
    assert subject == "IT-Dokumentation Physio Muster: 2 Fristen, 1 abgelaufen"
    assert "ABGELAUFEN" in body and "ESET (Lizenz)" in body and "M365 (Lizenz, Abo, jährlich)" in body and "in 24 Tagen" in body


def _run_at(conn, local_dt):
    return deadlines.run_due(conn, local_dt.astimezone(timezone.utc))


def test_weekly_digest_and_reminders(admin, outbox):
    admin.patch("/api/v1/deadlines", json={"recipients": "tim@example.de", "weekday": 0, "hour": 7})
    admin.post("/api/v1/licenses", json={"name": "Zertifikat", "kind": "certificate", "expires_on": day(10)})
    admin.post("/api/v1/licenses", json={"name": "Wartung", "kind": "maintenance", "expires_on": day(0)})
    admin.post("/api/v1/licenses", json={"name": "Später", "expires_on": day(50)})
    conn = connect()
    try:
        from app.timeutil import tz
        today = today_local()
        monday = today - timedelta(days=today.weekday())
        is_monday = today == monday
        early = datetime(today.year, today.month, today.day, 6, 0, tzinfo=tz())
        assert _run_at(conn, early) is None  # vor 7 Uhr nichts
        r = _run_at(conn, early.replace(hour=8))
        # Stichtag-Erinnerungen: Zertifikat (≤ 14 Tage) und Wartung (heute) – je einmal
        reminders = [s for s in outbox if s[1].startswith("Erinnerung")]
        assert sorted(s[1] for s in reminders) == ["Erinnerung: Wartung läuft heute ab", "Erinnerung: Zertifikat läuft in 10 Tagen ab"]
        assert r["reminders"] == 2 and (r["digest"] is not None) == is_monday
        assert _run_at(conn, early.replace(hour=9)) is None  # heute schon gelaufen
        conn.execute("UPDATE app_settings SET value = '' WHERE key = 'deadline_last_run'")
        r2 = _run_at(conn, early.replace(hour=10))
        assert r2["reminders"] == 0  # nicht doppelt
        # neues Ablaufdatum → neue Erinnerungen
        conn.execute("UPDATE licenses SET expires_on = ? WHERE name = 'Zertifikat'", (day(12),))
        conn.execute("UPDATE app_settings SET value = '' WHERE key = 'deadline_last_run'")
        assert _run_at(conn, early.replace(hour=11))["reminders"] == 1
        # Sammel-Mail nur am eingestellten Wochentag und einmal pro Woche
        conn.execute("UPDATE app_settings SET value = ? WHERE key = 'deadline_weekday'", (str(today.weekday()),))
        conn.execute("UPDATE app_settings SET value = '' WHERE key IN ('deadline_last_run', 'deadline_last_week')")
        r3 = _run_at(conn, early.replace(hour=12))
        assert r3["digest"]["status"] == "sent" and r3["digest"]["count"] == 3
        conn.execute("UPDATE app_settings SET value = '' WHERE key = 'deadline_last_run'")
        assert _run_at(conn, early.replace(hour=13))["digest"] is None
        # abgeschaltet → nichts
        conn.execute("UPDATE app_settings SET value = '0' WHERE key = 'deadline_enabled'")
        conn.execute("UPDATE app_settings SET value = '' WHERE key = 'deadline_last_run'")
        assert _run_at(conn, early.replace(hour=14)) is None
    finally:
        conn.close()


def test_deadline_mail_error_is_recorded(admin, monkeypatch):
    def boom(*a, **k):
        raise deadlines.MailError("Mailserver nicht erreichbar")
    monkeypatch.setattr(deadlines, "send_mail", boom)
    admin.patch("/api/v1/deadlines", json={"recipients": "tim@example.de"})
    admin.post("/api/v1/licenses", json={"name": "X", "expires_on": day(3)})
    conn = connect()
    try:
        from app.timeutil import tz
        t = today_local()
        r = _run_at(conn, datetime(t.year, t.month, t.day, 22, 0, tzinfo=tz()))
        assert "Mailserver" in r["error"]
    finally:
        conn.close()
    assert "FEHLER" in admin.get("/api/v1/deadlines").json()["last_result"]
    assert admin.post("/api/v1/deadlines/send-now").status_code == 400  # kein SMTP eingetragen → 400


# --- Notfall-Handbuch -------------------------------------------------------------

def test_handbook_pdf(admin):
    admin.post("/api/v1/contacts", json={"name": "Telekom", "emergency": True, "phone": "0800 330 1300", "external": True})
    admin.post("/api/v1/networks", json={"name": "Praxis-LAN", "cidr": "192.168.10.0/24", "dhcp_from": "192.168.10.100",
                                        "dhcp_to": "192.168.10.199"})
    t = admin.get("/api/v1/device-types").json()[0]["id"]
    admin.post("/api/v1/devices", json={"name": "Router", "type_id": t, "ip": "192.168.10.1"})
    site = admin.get("/api/v1/sites").json()[0]
    admin.patch(f"/api/v1/sites/{site['id']}", json={"isp_provider": "Telekom", "isp_customer_no": "4711"})
    png = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "icon.png"), "rb").read()
    admin.post(f"/api/v1/attachments?owner_type=site&owner_id={site['id']}&role=diagram&name=plan.png", content=png)
    # Tresor mit Geheimnis: darf nicht ins Handbuch
    admin.post("/api/v1/vault/setup", json={"password": "tresor-passwort-1"})
    admin.post("/api/v1/credentials", json={"title": "Router", "password": "GEHEIM-123"})
    r = admin.get("/api/v1/handbook.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert b"GEHEIM" not in r.content and b"/Image" in r.content
    assert any(e["action"] == "handbook_pdf" for e in admin.get("/api/v1/audit").json()["entries"])


# --- CSV-Import ---------------------------------------------------------------------

CSV = """Gerätename;Art;Hersteller;Modell;Seriennummer;IP-Adresse;Garantie bis;Status;Bemerkung
Empfang-PC;PC;Dell;OptiPlex 7010;7H2KQ93;192.168.10.21;13.03.2028;in Betrieb;Theorg-Client
Behandlung 1;PC;Dell;OptiPlex 3000;5JX0LM2;192.168.10.31;11/2027;aktiv;
Waage;Medizingerät;Seca;;W-1;;;;=HYPERLINK("x")
;PC;HP;;;;;;ohne Namen
Doppelt;PC;Dell;;7H2KQ93;;;;
Alt;Laptop;Lenovo;;L-9;999.1.1.1;31.02.2026;kaputt;
"""


def b64(text, enc="utf-8"):
    return base64.b64encode(text.encode(enc)).decode()


def test_import_guess_and_preview(admin):
    r = admin.post("/api/v1/devices/import/preview", json={"data_b64": b64(CSV, "cp1252")}).json()
    m = r["mapping"]
    assert r["headers"][0] == "Gerätename" and r["total"] == 6
    assert m == {"name": 0, "type": 1, "manufacturer": 2, "model": 3, "serial": 4, "ip": 5, "warranty_until": 6, "status": 7, "notes": 8}
    rows = {x["line"]: x for x in r["rows"]}
    assert rows[2]["action"] == "create" and rows[2]["values"]["warranty_until"] == "2028-03-13"
    assert rows[3]["values"]["warranty_until"] == "2027-11-30"
    assert rows[4]["values"]["new_type"] == "Medizingerät"
    assert rows[5]["action"] == "error" and rows[5]["errors"] == ["Name fehlt"]
    assert rows[6]["action"] == "skip" and "doppelt" in rows[6]["warnings"][0]
    w = " ".join(rows[7]["warnings"])
    assert "ungültig" in w and "nicht erkannt" in w and "Status" in w
    assert r["counts"] == {"create": 4, "skip": 1, "error": 1}
    # ohne Namensspalte: keine Prüfung
    r = admin.post("/api/v1/devices/import/preview", json={"data_b64": b64(CSV), "mapping": {"serial": 4}}).json()
    assert r["needs_name"] and r["rows"] == []


def test_import_run(admin):
    t = admin.get("/api/v1/device-types").json()[0]["id"]
    admin.post("/api/v1/devices", json={"name": "Schon da", "type_id": t, "serial": "5JX0LM2"})
    admin.post("/api/v1/networks", json={"name": "LAN", "cidr": "192.168.10.0/24"})
    r = admin.post("/api/v1/devices/import", json={"data_b64": b64(CSV), "create_types": True}).json()
    assert r == {"created": 3, "skipped": 2, "errors": 1, "new_types": ["Medizingerät"], "new_sites": []}
    devs = {d["name"]: d for d in admin.get("/api/v1/devices?status=all").json()}
    assert devs["Empfang-PC"]["ips"] == "192.168.10.21" and devs["Empfang-PC"]["notes"] == "Theorg-Client"
    assert devs["Waage"]["type_name"] == "Medizingerät" and devs["Alt"]["status"] == "active" and devs["Alt"]["ips"] is None
    assert devs["Empfang-PC"]["site_name"] == "Hauptstandort"
    ip = admin.get("/api/v1/ips").json()
    assert [i["ip"] for i in ip if i["device_id"] == devs["Empfang-PC"]["id"]] == ["192.168.10.21"]
    # nochmal importieren: alles mit Seriennummer wird übersprungen
    r2 = admin.post("/api/v1/devices/import", json={"data_b64": b64(CSV)}).json()
    assert r2["created"] == 0 and r2["skipped"] == 5
    log = admin.get("/api/v1/audit?category=doku").json()["entries"]
    assert any(e["action"] == "devices_imported" for e in log)
    # Formel bleibt Text, Notiz bleibt erhalten
    assert devs["Waage"]["notes"] == '=HYPERLINK("x")'


def test_import_options_and_limits(admin):
    csv = "Name;Typ;Standort\nA;Unbekannt;Filiale Süd\n"
    r = admin.post("/api/v1/devices/import/preview", json={"data_b64": b64(csv), "create_types": False, "create_sites": False}).json()
    row = r["rows"][0]
    assert "→ Sonstiges" in " ".join(row["warnings"]) and "→ Standard" in " ".join(row["warnings"])
    r = admin.post("/api/v1/devices/import", json={"data_b64": b64(csv), "create_sites": True}).json()
    assert r["new_sites"] == ["Filiale Süd"] and r["new_types"] == ["Unbekannt"]
    assert admin.post("/api/v1/devices/import/preview", json={"data_b64": "%%%"}).status_code == 400
    assert admin.post("/api/v1/devices/import/preview", json={"data_b64": b64(csv), "mapping": {"name": 9}}).status_code == 400
    assert admin.post("/api/v1/devices/import/preview", json={"data_b64": b64(csv), "mapping": {"quatsch": 0}}).status_code == 400
    assert importer.parse("a,b,c\n1,2,3\n")[1] == ["1", "2", "3"]
    assert importer.parse("a\tb\n1\t2\n")[1] == ["1", "2"]
