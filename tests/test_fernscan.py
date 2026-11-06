"""0.8: Agent scannt ein entferntes Netz (Standort ohne VPN) und liefert das Ergebnis an die IT-Dokumentation."""
import os

import pytest
from fastapi.testclient import TestClient

from app import netscan
from app.db import connect
from app.dsm_auth import _fails
from app.main import app

from .fresh import fresh_db

PW = os.environ["ITD_ADMIN_PASSWORD"]


@pytest.fixture()
def admin(tmp_path):
    _fails.clear()
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def bearer(t):
    return {"Authorization": "Bearer " + t}


def test_remote_scan_flow(admin):
    ag = admin.post("/api/v1/agents", json={"name": "filial-nas", "platform": "linux"}).json()
    other = admin.post("/api/v1/agents", json={"name": "anderer"}).json()
    local = admin.post("/api/v1/networks", json={"name": "Praxis-LAN", "cidr": "192.168.10.0/24", "scan": True}).json()
    remote = admin.post("/api/v1/networks", json={"name": "Filial-LAN", "cidr": "192.168.50.0/24", "scan": True,
                                                  "scan_agent_id": ag["id"]}).json()
    assert remote["scan_agent_name"] == "filial-nas" and remote["scan_requested"]
    assert admin.post("/api/v1/networks", json={"name": "x", "cidr": "10.0.0.0/24", "scan_agent_id": 999}).status_code == 404
    # Die NAS scannt nur ihr eigenes Netz
    assert [n["id"] for n, _ in netscan.targets(connect())] == [local["id"]]

    c = TestClient(app)
    assert c.get("/api/agent/v1/config", headers=bearer("itd_falsch")).status_code == 401
    cfg = c.get("/api/agent/v1/config", headers=bearer(ag["token"])).json()
    assert cfg["report_due"] is True and cfg["scan"] == [{"network_id": remote["id"], "name": "Filial-LAN", "cidr": "192.168.50.0/24"}]
    assert 8006 in cfg["ports"] and cfg["max_hosts"] == 1022
    assert c.get("/api/agent/v1/config", headers=bearer(other["token"])).json()["scan"] == []

    payload = {"started_at": "2026-11-06T13:00:00Z", "networks": [
        {"network_id": remote["id"], "hosts": [
            {"ip": "192.168.50.1", "mac": "3c:a6:2f:00:12:7f", "hostname": "fritz.box", "ports": [80, 443, 53]},
            {"ip": "192.168.50.20", "mac": "8c-04-ba-3e-11-f2", "hostname": "FILIALE-PC", "ports": [445, 3389]},
            {"ip": "192.168.50.20", "mac": "", "hostname": "doppelt", "ports": []},
            {"ip": "10.9.9.9", "hostname": "nicht im Netz"},
            {"ip": "kaputt"}]},
        {"network_id": local["id"], "hosts": [{"ip": "192.168.10.99"}]}]}  # fremdes Netz → ignoriert
    assert c.post("/api/agent/v1/scan", json=payload, headers=bearer(other["token"])).status_code == 400
    r = c.post("/api/agent/v1/scan", json=payload, headers=bearer(ag["token"]))
    assert r.status_code == 200 and r.json()["hosts_up"] == 2
    conn = connect()
    run = conn.execute("SELECT * FROM scan_runs WHERE id = ?", (r.json()["run_id"],)).fetchone()
    assert run["agent_id"] == ag["id"] and run["trigger"] == "agent" and run["networks"] == "Filial-LAN" and run["addresses"] == 254
    assert {h["ip"]: h["mac"] for h in conn.execute("SELECT ip, mac FROM scan_hosts")} == \
        {"192.168.50.1": "3C:A6:2F:00:12:7F", "192.168.50.20": "8C:04:BA:3E:11:F2"}
    # angefordert erledigt, nicht gleich wieder fällig
    assert c.get("/api/agent/v1/config", headers=bearer(ag["token"])).json()["scan"] == []

    res = admin.get("/api/v1/scan").json()
    new = {n["ip"]: n for n in res["new"]}
    assert set(new) == {"192.168.50.1", "192.168.50.20"} and new["192.168.50.1"]["vendor"] == "AVM"
    assert new["192.168.50.20"]["network_name"] == "Filial-LAN"
    nets = {n["name"]: n for n in res["networks"]}
    assert nets["Filial-LAN"]["agent"] == "filial-nas" and nets["Filial-LAN"]["last_scan"] and nets["Praxis-LAN"]["agent"] is None
    # übernehmen wie bei einem lokalen Scan
    assert admin.post("/api/v1/scan/adopt", json={"items": [{"ip": "192.168.50.20", "network_id": remote["id"], "name": "FILIALE-PC",
                                                             "type_id": new["192.168.50.20"]["type_id"], "mac": "8C:04:BA:3E:11:F2"}]}).status_code == 200
    assert [n["ip"] for n in admin.get("/api/v1/scan").json()["new"]] == ["192.168.50.1"]

    # „Jetzt scannen“: lokales Netz läuft sofort, das entfernte wird angefordert
    netscan.start_background = lambda trigger, uid: None
    r = admin.post("/api/v1/scan/start").json()
    assert r["local"] is True and r["requested"] == ["Filial-LAN"]
    assert c.get("/api/agent/v1/config", headers=bearer(ag["token"])).json()["scan"][0]["network_id"] == remote["id"]

    # Agent gelöscht → Netz wird nicht stillschweigend von der NAS aus gescannt
    admin.delete(f"/api/v1/agents/{ag['id']}")
    n = conn.execute("SELECT scan, scan_agent_id FROM networks WHERE id = ?", (remote["id"],)).fetchone()
    assert n["scan"] == 0 and n["scan_agent_id"] is None
    log = admin.get("/api/v1/audit?category=einstellungen").json()["entries"] + admin.get("/api/v1/audit").json()["entries"]
    assert any("Agent „filial-nas“" in str(e) for e in log)


def test_assign_agent_to_existing_network(admin):
    ag = admin.post("/api/v1/agents", json={"name": "scanner"}).json()
    n = admin.post("/api/v1/networks", json={"name": "Filiale", "cidr": "192.168.60.0/24", "scan": True}).json()
    assert not n["scan_requested"]
    n = admin.patch(f"/api/v1/networks/{n['id']}", json={"scan_agent_id": ag["id"]}).json()
    assert n["scan_requested"] and n["scan_agent_name"] == "scanner"
    hist = admin.get(f"/api/v1/history/network/{n['id']}")
    if hist.status_code == 200:
        assert "Agent „scanner“" in str(hist.json())
    n = admin.patch(f"/api/v1/networks/{n['id']}", json={"scan_agent_id": None}).json()
    assert n["scan_agent_name"] is None


def test_agent_synology_collectors(monkeypatch, tmp_path):
    """DSM-Werte aus den Synology-Dateien (ohne echte NAS nachgestellt)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("itdoku_agent", str(os.path.join(os.path.dirname(__file__), "..", "app", "agent", "itdoku-agent.py")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = {
        "/etc.defaults/VERSION": 'majorversion="7"\nminorversion="2"\nproductversion="7.2.2"\nbuildnumber="72806"\nsmallfixnumber="3"\n',
        "/etc.defaults/synoinfo.conf": 'upnpmodelname="DS920+"\n',
        "/proc/sys/kernel/syno_hw_version": "DS920+",
        "/proc/sys/kernel/syno_serial": "2150PDN123456",
        "/var/packages/HyperBackup/INFO": 'package="HyperBackup"\nversion="4.1.0-3718"\nmaintainer="Synology Inc."\ndisplayname="Hyper Backup"\n',
        "/var/packages/itdoku/INFO": 'package="itdoku"\nversion="0.8.0-0001"\ndisplayname="IT-Dokumentation"\nmaintainer="rinkelzz"\n',
    }
    real_read, real_listdir = mod.read, os.listdir
    monkeypatch.setattr(mod, "read", lambda p: files[p].strip() if p in files else real_read(p))
    monkeypatch.setattr(mod.os, "listdir", lambda p: ["HyperBackup", "itdoku"] if p == "/var/packages" else real_listdir(p))
    assert mod.syno_os()["name"] == "DSM 7.2.2-72806 Update 3"
    hw = mod.syno_hw()
    assert (hw["manufacturer"], hw["model"], hw["serial"], hw["chassis"]) == ("Synology", "DS920+", "2150PDN123456", "server")
    assert [p["name"] for p in mod.syno_software()] == ["Hyper Backup", "IT-Dokumentation"]
    assert mod.syno_updates()["pending"] is None
