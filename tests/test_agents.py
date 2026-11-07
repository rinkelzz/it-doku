"""0.6: Agenten – Schlüssel, Bericht, Geräteabgleich, stille Agenten, Rechte, Skripte."""
import copy
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agents
from app.db import connect
from app.deadlines import compose_digest
from app.dsm_auth import _fails
from app.main import app
from app.timeutil import now_utc, to_utc_str

from .fresh import fresh_db

PW = os.environ["ITD_ADMIN_PASSWORD"]
ROOT = Path(__file__).resolve().parent.parent

REPORT = {
    "agent_version": "1.0", "platform": "windows", "hostname": "PRAXIS-DC", "domain": "praxis.local",
    "boot_time": "2026-10-25T06:00:00Z",
    "os": {"name": "Windows Server 2022 Standard", "version": "21H2", "build": "20348.2700", "arch": "64-Bit"},
    "hardware": {"manufacturer": "Dell Inc.", "model": "PowerEdge T150", "serial": "8XK2L93", "cpu": "Intel Xeon E-2314",
                 "cores": 4, "ram_mb": 32768, "chassis": "server", "virtual": False},
    "disks": [{"mount": "C:", "fs": "NTFS", "total_gb": 240, "free_gb": 20}, {"mount": "D:", "fs": "NTFS", "total_gb": 2000, "free_gb": 1500}],
    "network": {"interfaces": [{"name": "Intel I350", "mac": "a4-bb-6d-01-02-03", "ipv4": ["192.168.10.5", "169.254.1.1"],
                                "ipv6": ["fe80::1", "2a01:4f8::5"]}],
                "gateway": ["192.168.10.1"], "dns": ["192.168.10.5", "kaputt"]},
    "software": [{"name": "Theorg", "version": "24.1", "publisher": "SOVDWAER"}, {"name": "=HYPERLINK(\"x\")", "version": "1"},
                 {"name": "Theorg", "version": "24.1", "publisher": "doppelt"}, {"name": ""}],
    "updates": {"pending": 3, "security": 1, "reboot_required": True, "last_installed": "2026-10-14", "items": ["KB1", "KB2", "KB3"]},
    "services": [{"name": "MSSQL$THEORG", "display": "SQL Server (THEORG)", "state": "running", "start": "auto"},
                 {"name": "VeeamBackup", "display": "Veeam", "state": "stopped", "start": "auto"},
                 {"name": "Fax", "state": "stopped", "start": "manual"}],
    "unbekannt": {"x": "wird verworfen"},
}


@pytest.fixture()
def admin(tmp_path):
    _fails.clear()
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def send(token, body=None, client=None):
    c = client or TestClient(app)
    return c.post("/api/agent/v1/report", json=REPORT if body is None else body, headers={"Authorization": "Bearer " + token})


def test_create_report_and_new_device(admin):
    net = admin.post("/api/v1/networks", json={"name": "LAN", "cidr": "192.168.10.0/24"}).json()
    r = admin.post("/api/v1/agents", json={"name": "praxis-dc", "platform": "windows"})
    assert r.status_code == 201
    token = r.json()["token"]
    assert token.startswith("itd_") and r.json()["url"] == "https://doku.example.de"
    lst = admin.get("/api/v1/agents").json()["agents"]
    assert lst[0]["token_hint"] == "…" + token[-4:] and lst[0]["last_report_at"] is None and not lst[0]["stale"]
    # Schlüssel steht nirgends im Klartext
    conn = connect()
    assert token not in json.dumps([dict(x) for x in conn.execute("SELECT * FROM agents")])

    r = send(token)
    assert r.status_code == 200 and r.json()["created"] is True
    did = r.json()["device_id"]
    d = admin.get(f"/api/v1/devices/{did}").json()
    assert d["name"] == "PRAXIS-DC" and d["type_name"] == "NAS / Server" and d["serial"] == "8XK2L93"
    assert d["os"] == "Windows Server 2022 Standard 21H2" and d["manufacturer"] == "Dell Inc."
    # IP aus dem dokumentierten Netz am Gerät, Link-Local nicht
    assert [i["ip"] for i in d["ip_list"]] == ["192.168.10.5"]
    assert d["ip_list"][0]["mac"] == "A4:BB:6D:01:02:03" and d["ip_list"][0]["network_id"] == net["id"]
    assert any("Agent" in h["text"] for h in d["history"])

    rep = admin.get(f"/api/v1/devices/{did}/agent").json()
    assert rep["agent"]["name"] == "praxis-dc" and rep["agent"]["platform_label"] == "Windows"
    p = rep["report"]
    assert "unbekannt" not in p
    assert [s["name"] for s in p["software"]] == ["=HYPERLINK(\"x\")", "Theorg"]  # doppelt/leer entfernt, sortiert
    assert p["network"]["dns"] == ["192.168.10.5"] and p["network"]["interfaces"][0]["ipv6"] == ["2a01:4f8::5"]
    assert rep["agent"]["problems"] == {"disks_full": 1, "services_stopped": ["VeeamBackup"], "updates_pending": 3,
                                        "reboot_required": True}
    csv = admin.get(f"/api/v1/devices/{did}/agent/software.csv").text
    assert "'=HYPERLINK" in csv and "Theorg;24.1" in csv


def test_match_existing_device_by_serial_and_name(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    a = admin.post("/api/v1/devices", json={"name": "Server Praxis", "type_id": types["NAS / Server"], "serial": "8xk2l93",
                                             "os": "Windows Server 2019", "model": "von Hand"}).json()
    b = admin.post("/api/v1/devices", json={"name": "web01", "type_id": types["PC"]}).json()
    t1 = admin.post("/api/v1/agents", json={"name": "dc"}).json()["token"]
    t2 = admin.post("/api/v1/agents", json={"name": "web"}).json()["token"]
    assert send(t1).json() == {"ok": True, "device_id": a["id"], "created": False}
    d = admin.get(f"/api/v1/devices/{a['id']}").json()
    assert d["os"] == "Windows Server 2022 Standard 21H2"   # OS wird nachgezogen
    assert d["model"] == "von Hand" and d["manufacturer"] == "Dell Inc."  # Handarbeit bleibt, Leeres wird ergänzt
    rep = copy.deepcopy(REPORT)
    rep.update({"hostname": "web01.example.de", "platform": "linux"})
    rep["hardware"]["serial"] = "To be filled by O.E.M."
    rep["os"] = {"name": "Ubuntu 24.04.1 LTS", "version": "24.04"}
    assert send(t2, rep).json()["device_id"] == b["id"]
    assert admin.get(f"/api/v1/devices/{b['id']}").json()["serial"] == ""  # Platzhalter-Seriennummer nicht übernommen
    # Ein zweiter Agent mit derselben Seriennummer bekommt NICHT dasselbe Gerät
    t3 = admin.post("/api/v1/agents", json={"name": "klon"}).json()["token"]
    assert send(t3).json()["device_id"] not in (a["id"], b["id"])


def test_device_assignment_on_create(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    d = admin.post("/api/v1/devices", json={"name": "Cloud-Server", "type_id": types["NAS / Server"]}).json()
    tok = admin.post("/api/v1/agents", json={"name": "web01", "device_id": d["id"]}).json()["token"]
    assert admin.post("/api/v1/agents", json={"name": "x", "device_id": d["id"]}).status_code == 409
    assert send(tok).json()["device_id"] == d["id"]
    assert admin.get(f"/api/v1/devices/{d['id']}").json()["name"] == "Cloud-Server"  # Name bleibt


def test_auth_errors_and_brute_force(admin):
    assert send("itd_falsch").status_code == 401
    assert TestClient(app).post("/api/agent/v1/report", json=REPORT).status_code == 401
    # Login-Cookie allein reicht nicht
    assert admin.post("/api/agent/v1/report", json=REPORT).status_code == 401
    aid = admin.post("/api/v1/agents", json={"name": "a"}).json()["id"]
    tok = admin.get("/api/v1/agents").json()  # Schlüssel kommt nie wieder aus der Liste
    assert "token" not in tok["agents"][0]
    new = admin.post(f"/api/v1/agents/{aid}/token").json()["token"]
    assert send(new).status_code == 200
    assert admin.patch(f"/api/v1/agents/{aid}", json={"disabled": True}).status_code == 200
    assert send(new).status_code == 403
    admin.patch(f"/api/v1/agents/{aid}", json={"disabled": False})
    assert send(new, body=[1, 2]).status_code == 400
    assert TestClient(app).post("/api/agent/v1/report", content=b"{kaputt", headers={"Authorization": "Bearer " + new}).status_code == 400
    big = b'{"x":"' + b"a" * (agents.MAX_BODY + 10) + b'"}'
    assert TestClient(app).post("/api/agent/v1/report", content=big, headers={"Authorization": "Bearer " + new}).status_code == 413
    _fails.clear()
    for _ in range(20):
        send("itd_raten")
    assert send(new).status_code == 429  # nach 20 Fehlversuchen von derselben Adresse gesperrt
    _fails.clear()


def test_reader_rights(admin, tmp_path):
    tok = admin.post("/api/v1/agents", json={"name": "a"}).json()["token"]
    did = send(tok).json()["device_id"]
    admin.post("/api/v1/users", json={"username": "leser", "display_name": "Leser", "password": "leser-passwort-1", "is_admin": False})
    with TestClient(app) as r:
        assert r.post("/api/v1/auth/login", json={"username": "leser", "password": "leser-passwort-1"}).status_code == 200
        assert r.get("/api/v1/agents").status_code == 403
        assert r.post("/api/v1/agents", json={"name": "b"}).status_code == 403
        rep = r.get(f"/api/v1/devices/{did}/agent").json()
        assert rep["report"]["hostname"] == "PRAXIS-DC" and "token_hint" not in rep["agent"] and "last_ip" not in rep["agent"]


def test_stale_agents_overview_and_mail(admin):
    tok = admin.post("/api/v1/agents", json={"name": "filiale-pc"}).json()["token"]
    send(tok)
    assert admin.get("/api/v1/overview").json()["agents_stale"] == []
    conn = connect()
    conn.execute("UPDATE agents SET last_report_at = ?", (to_utc_str(now_utc() - timedelta(days=4)),))
    stale = admin.get("/api/v1/overview").json()["agents_stale"]
    assert [a["name"] for a in stale] == ["filiale-pc"] and stale[0]["device_name"] == "PRAXIS-DC"
    assert admin.get("/api/v1/agents").json()["agents"][0]["stale"] is True
    subject, body = compose_digest(conn, [], 90)
    assert "Hinweise" in subject and "AGENTEN" in body and "filiale-pc (PRAXIS-DC)" in body
    admin.patch("/api/v1/agents-settings", json={"stale_days": 7, "agent_url": "http://10.8.0.1:8780/"})
    assert admin.get("/api/v1/overview").json()["agents_stale"] == []
    u = admin.get("/api/v1/agents").json()["settings"]["urls"]
    assert u["external"] == "http://10.8.0.1:8780"
    assert u["lan"] == u["lan_auto"] and u["lan"].endswith(":8780") or u["lan"] == ""
    admin.patch("/api/v1/agents-settings", json={"agent_url_lan": "http://192.168.10.5:8780"})
    r = admin.post("/api/v1/agents", json={"name": "lan"}).json()
    assert r["urls"]["lan"] == "http://192.168.10.5:8780" and r["urls"]["external"] == "http://10.8.0.1:8780"
    assert admin.patch("/api/v1/agents-settings", json={"agent_url_lan": "192.168.10.5"}).status_code == 400
    assert admin.patch("/api/v1/agents-settings", json={"agent_url": "ftp://x"}).status_code == 400


def test_delete_agent_keeps_device(admin):
    r = admin.post("/api/v1/agents", json={"name": "weg"}).json()
    did = send(r["token"]).json()["device_id"]
    assert admin.delete(f"/api/v1/agents/{r['id']}").status_code == 200
    assert admin.get(f"/api/v1/devices/{did}").status_code == 200
    assert admin.get(f"/api/v1/devices/{did}/agent").json() == {"agent": None}
    assert send(r["token"]).status_code == 401
    log = admin.get("/api/v1/audit?category=agenten").json()["entries"]
    assert {e["action"] for e in log} == {"agent_created", "agent_deleted"}


def test_scripts_download():
    c = TestClient(app)
    for name in ("itdoku-agent.ps1", "itdoku-agent.py"):
        r = c.get("/agent/" + name)
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        assert "itd_" in r.text and "Bearer" in r.text
    assert c.get("/agent/../app/db.py").status_code == 404
    assert c.get("/agent/config.py").status_code == 404
    ps = (ROOT / "app/agent/itdoku-agent.ps1").read_bytes()
    assert ps.startswith(b"\xef\xbb\xbf")  # BOM: Windows PowerShell 5.1 liest sonst Umlaute falsch


def test_python_agent_collects_and_sanitizes():
    out = subprocess.run([sys.executable, str(ROOT / "app/agent/itdoku-agent.py"), "--print"], stdout=subprocess.PIPE, timeout=600, check=True)
    rep = agents.sanitize(json.loads(out.stdout))
    assert rep["platform"] in ("linux", "macos") and rep["hostname"] and rep["os"]["name"]
    assert rep["hardware"]["ram_mb"] and rep["disks"]


def test_sanitize_limits():
    raw = {"hostname": "x" * 500, "software": [{"name": f"p{i}", "version": "1"} for i in range(6000)],
           "disks": [{"mount": "/", "total_gb": "abc"}, {"mount": "/", "total_gb": 10, "free_gb": 50}],
           "hardware": {"cores": -3, "ram_mb": "1e40"}, "network": {"interfaces": [{"name": "eth0", "mac": "zz", "ipv4": ["300.1.1.1", "10.0.0.1"]}]},
           "services": [{"name": "a", "state": "weird", "start": "boot"}], "updates": {"pending": "7"}, "platform": "amiga"}
    rep = agents.sanitize(raw)
    assert len(rep["hostname"]) == 100 and len(rep["software"]) == agents.LIMITS["software"]
    assert rep["disks"] == [{"mount": "/", "fs": "", "label": "", "total_gb": 10.0, "free_gb": 10.0}]
    assert rep["hardware"]["cores"] is None and rep["hardware"]["ram_mb"] is None
    assert rep["network"]["interfaces"] == [{"name": "eth0", "mac": "", "ipv4": ["10.0.0.1"], "ipv6": []}]
    assert rep["services"][0]["state"] == "other" and rep["services"][0]["start"] == ""
    assert rep["updates"]["pending"] == 7 and rep["platform"] == ""


def test_placeholder_names_get_hostname(admin):
    from app.doku import is_placeholder_name
    assert is_placeholder_name("192.168.90.4") and is_placeholder_name("DC:A6:32:DC:81:CB") and is_placeholder_name("2a01::1")
    assert not is_placeholder_name("raspberrypi") and not is_placeholder_name("NAS 192.168.1.5")
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    net = admin.post("/api/v1/networks", json={"name": "LAN", "cidr": "192.168.10.0/24"}).json()
    d = admin.post("/api/v1/devices", json={"name": "192.168.10.5", "type_id": types["Sonstiges"]}).json()
    ip = admin.post("/api/v1/ips", json={"ip": "192.168.10.5", "network_id": net["id"], "device_id": d["id"]}).json()
    # Netzwerk-Scan: Hostname übernehmen benennt das Gerät mit
    assert admin.post("/api/v1/scan/fill", json={"items": [{"ip_id": ip["id"], "hostname": "printer.local"}]}).json()["updated"] == 1
    assert admin.get(f"/api/v1/devices/{d['id']}").json()["name"] == "printer"
    # Agent: Gerät, das nur „IP“ heißt, bekommt den Rechnernamen; echte Namen bleiben
    d2 = admin.post("/api/v1/devices", json={"name": "10.0.0.7", "type_id": types["PC"], "serial": "8XK2L93"}).json()
    send(admin.post("/api/v1/agents", json={"name": "a"}).json()["token"])
    assert admin.get(f"/api/v1/devices/{d2['id']}").json()["name"] == "PRAXIS-DC"
    admin.patch(f"/api/v1/devices/{d2['id']}", json={"name": "Server Praxis"})
    send(admin.get("/api/v1/agents").json() and admin.post(f"/api/v1/agents/{admin.get('/api/v1/agents').json()['agents'][0]['id']}/token").json()["token"])
    assert admin.get(f"/api/v1/devices/{d2['id']}").json()["name"] == "Server Praxis"


def test_selfbuilt_pc_and_fast_startup(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    d = admin.post("/api/v1/devices", json={"name": "TIMSPC", "type_id": types["PC"], "manufacturer": "To Be Filled By O.E.M."}).json()
    rep = copy.deepcopy(REPORT)
    rep.update({"hostname": "TIMSPC", "boot_time": "2026-11-02T15:04:00Z", "power_on_time": "2026-11-06T17:10:00Z", "fast_startup": True})
    rep["hardware"].update({"manufacturer": "To Be Filled By O.E.M.", "model": "To Be Filled By O.E.M.", "serial": "To Be Filled By O.E.M.",
                            "board_manufacturer": "ASRock", "board_product": "B550 Pro4", "chassis": "desktop"})
    rep["os"] = {"name": "Windows 11 Pro", "version": "24H2"}
    tok = admin.post("/api/v1/agents", json={"name": "timspc"}).json()["token"]
    assert send(tok, rep).json()["device_id"] == d["id"]
    dev = admin.get(f"/api/v1/devices/{d['id']}").json()
    assert (dev["manufacturer"], dev["model"], dev["serial"]) == ("ASRock", "B550 Pro4", "")
    p = admin.get(f"/api/v1/devices/{d['id']}/agent").json()["report"]
    assert p["power_on_time"] == "2026-11-06T17:10:00+00:00" and p["fast_startup"] is True
    assert agents._hw_text("To Be Filled By O.E.M. B550 Pro4") == "B550 Pro4" and agents._hw_text("System Product Name") == ""


def test_request_report_and_contact(admin):
    r = admin.post("/api/v1/agents", json={"name": "srv"}).json()
    send(r["token"])
    c = TestClient(app)
    cfg = c.get("/api/agent/v1/config", headers={"Authorization": "Bearer " + r["token"]}).json()
    assert cfg["report_due"] is False
    assert admin.post(f"/api/v1/agents/{r['id']}/request-report").status_code == 200
    a = admin.get("/api/v1/agents").json()["agents"][0]
    assert a["report_requested"] is True and a["last_contact_at"]
    assert c.get("/api/agent/v1/config", headers={"Authorization": "Bearer " + r["token"]}).json()["report_due"] is True
    send(r["token"])
    assert admin.get("/api/v1/agents").json()["agents"][0]["report_requested"] is False
    # „beendet“ (oneshot, Bedingung nicht erfüllt) zählt nicht als Problem
    rep = copy.deepcopy(REPORT)
    rep["services"] = [{"name": "e2scrub_reap", "state": "idle", "start": "auto"}, {"name": "nginx", "state": "failed", "start": "auto"}]
    send(r["token"], rep)
    did = admin.get("/api/v1/agents").json()["agents"][0]["device_id"]
    assert admin.get(f"/api/v1/devices/{did}/agent").json()["agent"]["problems"]["services_stopped"] == ["nginx"]


def test_agent_fingerprint_ignores_small_disk_changes():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ag", str(ROOT / "app/agent/itdoku-agent.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    a = copy.deepcopy(REPORT)
    b = copy.deepcopy(REPORT)
    b["disks"][1]["free_gb"] = 1501  # kleine Schwankung
    assert m.fingerprint(a) == m.fingerprint(b)
    b["updates"]["pending"] = 0  # Updates eingespielt → sofort melden
    assert m.fingerprint(a) != m.fingerprint(b)
