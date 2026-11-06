"""0.8.2: doppelte Geräte – Agent findet Scan-Gerät über die MAC, Zusammenführen."""
import copy
import os

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.dsm_auth import _fails
from app.main import app

from .fresh import fresh_db
from .test_agents import REPORT, send

PW = os.environ["ITD_ADMIN_PASSWORD"]


@pytest.fixture()
def admin(tmp_path):
    _fails.clear()
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def test_agent_matches_scan_device_by_mac(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    net = admin.post("/api/v1/networks", json={"name": "Home", "cidr": "192.168.90.0/24"}).json()
    # vom Scan angelegt: Name = IP, MAC an der IP, kein Hostname
    d = admin.post("/api/v1/devices", json={"name": "192.168.90.40", "type_id": types["Sonstiges"]}).json()
    admin.post("/api/v1/ips", json={"ip": "192.168.90.40", "network_id": net["id"], "device_id": d["id"], "mac": "a4:bb:6d:01:02:03"})
    rep = copy.deepcopy(REPORT)
    rep["hardware"]["serial"] = ""
    rep["hostname"] = "TIMSPC"
    rep["network"]["interfaces"][0]["ipv4"] = ["192.168.90.40"]
    tok = admin.post("/api/v1/agents", json={"name": "timspc"}).json()["token"]
    assert send(tok, rep).json() == {"ok": True, "device_id": d["id"], "created": False}
    assert admin.get(f"/api/v1/devices/{d['id']}").json()["name"] == "TIMSPC"  # Platzhalter-Name ersetzt
    assert len(admin.get("/api/v1/devices").json()) == 1


def test_merge(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    net = admin.post("/api/v1/networks", json={"name": "Home", "cidr": "192.168.90.0/24"}).json()
    keep = admin.post("/api/v1/devices", json={"name": "TIMSPC", "type_id": types["PC"], "notes": "Arbeitsplatz"}).json()
    dup = admin.post("/api/v1/devices", json={"name": "timspc", "type_id": types["Sonstiges"], "serial": "ABC123", "room": "Büro",
                                              "notes": "vom Scan"}).json()
    third = admin.post("/api/v1/devices", json={"name": "Drucker", "type_id": types["Drucker"]}).json()
    admin.post("/api/v1/ips", json={"ip": "192.168.90.40", "network_id": net["id"], "device_id": dup["id"], "mac": "AA:BB:CC:DD:EE:01"})
    admin.post("/api/v1/ips", json={"ip": "192.168.90.41", "network_id": net["id"], "device_id": keep["id"], "mac": "aa:bb:cc:dd:ee:01"})
    admin.post(f"/api/v1/devices/{dup['id']}/links", json={"device_id": third["id"], "note": "USB"})
    admin.post(f"/api/v1/devices/{dup['id']}/links", json={"device_id": keep["id"]})
    admin.post(f"/api/v1/devices/{dup['id']}/urls", json={"url": "https://timspc.lan"})
    lic = admin.post("/api/v1/licenses", json={"name": "Office", "kind": "software"}).json()
    r = admin.put(f"/api/v1/licenses/{lic['id']}/devices", json={"device_ids": [dup["id"], keep["id"]]})
    assert r.status_code in (200, 404, 405)

    dups = admin.get(f"/api/v1/devices/{keep['id']}/duplicates").json()
    assert [x["id"] for x in dups] == [dup["id"]] and dups[0]["reason"] == "gleiche MAC-Adresse"
    assert admin.post(f"/api/v1/devices/{keep['id']}/merge", json={"other_id": keep["id"]}).status_code == 400

    res = admin.post(f"/api/v1/devices/{keep['id']}/merge", json={"other_id": dup["id"]}).json()
    assert res["ok"] and set(res["filled"]) == {"serial", "room"}
    assert admin.get(f"/api/v1/devices/{dup['id']}").status_code == 404
    d = admin.get(f"/api/v1/devices/{keep['id']}").json()
    assert d["serial"] == "ABC123" and d["name"] == "TIMSPC" and d["type_id"] == types["PC"]
    assert d["notes"] == "Arbeitsplatz\n\nvom Scan"
    assert sorted(i["ip"] for i in d["ip_list"]) == ["192.168.90.40", "192.168.90.41"]
    assert [u["url"] for u in d["urls"]] == ["https://timspc.lan"]
    conn = connect()
    links = conn.execute("SELECT a_id, b_id, note FROM device_links").fetchall()
    assert [tuple(x) for x in links] == [(keep["id"], third["id"], "USB")]  # Selbst-Verbindung entfällt
    assert any("zusammengeführt" in h["text"] for h in d["history"])
    assert admin.get(f"/api/v1/devices/{keep['id']}/duplicates").json() == []


def test_merge_refuses_two_agents(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    a = admin.post("/api/v1/devices", json={"name": "A", "type_id": types["PC"]}).json()
    b = admin.post("/api/v1/devices", json={"name": "B", "type_id": types["PC"]}).json()
    admin.post("/api/v1/agents", json={"name": "a", "device_id": a["id"]})
    admin.post("/api/v1/agents", json={"name": "b", "device_id": b["id"]})
    assert admin.post(f"/api/v1/devices/{a['id']}/merge", json={"other_id": b["id"]}).status_code == 409
    assert admin.get(f"/api/v1/devices/{b['id']}").status_code == 200
