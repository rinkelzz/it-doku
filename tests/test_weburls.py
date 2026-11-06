"""0.7: Web-Adressen an Geräten, automatisch aus Scan-Ports, anklickbarer Hostname in der IP-Liste."""
import os

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.dsm_auth import _fails
from app.main import app
from app.weburl import auto_url

from .fresh import fresh_db

PW = os.environ["ITD_ADMIN_PASSWORD"]


@pytest.fixture()
def admin(tmp_path):
    _fails.clear()
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def test_auto_url():
    assert auto_url("192.168.90.30", "vault.kunde.de", "22,80,443") == "https://vault.kunde.de"
    assert auto_url("192.168.90.30", "vaultwarden", "80") == "http://192.168.90.30"
    assert auto_url("192.168.90.31", "pve", "22,8006") == "https://192.168.90.31:8006"
    assert auto_url("192.168.90.32", "", "8080") == "http://192.168.90.32:8080"
    assert auto_url("192.168.90.33", "drucker", "9100,515") == ""


def test_urls_crud_and_lists(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    net = admin.post("/api/v1/networks", json={"name": "Home", "cidr": "192.168.90.0/24"}).json()
    d = admin.post("/api/v1/devices", json={"name": "Vaultwarden", "type_id": types["NAS / Server"]}).json()
    admin.post("/api/v1/ips", json={"ip": "192.168.90.30", "network_id": net["id"], "device_id": d["id"], "hostname": "vaultwarden"})
    pve = admin.post("/api/v1/devices", json={"name": "Proxmox", "type_id": types["NAS / Server"]}).json()
    admin.post("/api/v1/ips", json={"ip": "192.168.90.31", "network_id": net["id"], "device_id": pve["id"], "hostname": "pve.home.lan"})
    # Scan hat Web-Ports gefunden
    conn = connect()
    run = conn.execute("INSERT INTO scan_runs(trigger, started_at, finished_at) VALUES ('manual', '2026-11-06T10:00:00+00:00', "
                       "'2026-11-06T10:01:00+00:00')").lastrowid
    conn.executemany("INSERT INTO scan_hosts(run_id, network_id, ip, ports) VALUES (?, ?, ?, ?)",
                     [(run, net["id"], "192.168.90.30", "22,80"), (run, net["id"], "192.168.90.31", "22,8006")])

    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x", "https://", "http://a b"):
        assert admin.post(f"/api/v1/devices/{d['id']}/urls", json={"url": bad}).status_code == 400, bad
    r = admin.post(f"/api/v1/devices/{d['id']}/urls", json={"label": "Vaultwarden", "url": "vault.kunde.de"})
    assert r.status_code == 201 and r.json()["url"] == "https://vault.kunde.de"
    u2 = admin.post(f"/api/v1/devices/{d['id']}/urls", json={"label": "Admin", "url": "https://vault.kunde.de/admin"}).json()

    det = admin.get(f"/api/v1/devices/{d['id']}").json()
    assert [u["label"] for u in det["urls"]] == ["Vaultwarden", "Admin"]
    assert det["url_suggestions"] == ["http://192.168.90.30"]
    assert any("Web-Adresse hinzugefügt" in h["text"] for h in det["history"])
    assert admin.get(f"/api/v1/devices/{pve['id']}").json()["url_suggestions"] == ["https://pve.home.lan:8006", "https://pve.home.lan"]

    ips = {i["ip"]: i for i in admin.get(f"/api/v1/ips?network_id={net['id']}").json()}
    assert ips["192.168.90.30"]["urls"][0]["url"] == "https://vault.kunde.de" and ips["192.168.90.30"]["web_auto"] == ""
    assert ips["192.168.90.31"]["urls"] == [] and ips["192.168.90.31"]["web_auto"] == "https://pve.home.lan:8006"
    devs = {x["name"]: x for x in admin.get("/api/v1/devices").json()}
    assert len(devs["Vaultwarden"]["urls"]) == 2 and devs["Proxmox"]["urls"] == []
    assert [x["name"] for x in admin.get("/api/v1/devices?q=kunde.de").json()] == ["Vaultwarden"]

    assert admin.patch(f"/api/v1/device-urls/{u2['id']}", json={"label": "Admin-Panel", "url": "https://vault.kunde.de/admin/"}).status_code == 200
    assert admin.patch(f"/api/v1/device-urls/{u2['id']}", json={"url": "javascript:x"}).status_code == 400
    assert admin.delete(f"/api/v1/device-urls/{u2['id']}").status_code == 200
    assert admin.delete(f"/api/v1/device-urls/{u2['id']}").status_code == 404
    assert [u["label"] for u in admin.get(f"/api/v1/devices/{d['id']}").json()["urls"]] == ["Vaultwarden"]
    # Gerät gelöscht → Web-Adressen weg
    admin.delete(f"/api/v1/devices/{d['id']}")
    assert conn.execute("SELECT COUNT(*) FROM device_urls").fetchone()[0] == 0


def test_reader_sees_but_cannot_change(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    d = admin.post("/api/v1/devices", json={"name": "NAS", "type_id": types["NAS / Server"]}).json()
    u = admin.post(f"/api/v1/devices/{d['id']}/urls", json={"url": "https://nas.kunde.de:5001"}).json()
    admin.post("/api/v1/users", json={"username": "leser", "display_name": "Leser", "password": "leser-passwort-1", "is_admin": False})
    with TestClient(app) as r:
        r.post("/api/v1/auth/login", json={"username": "leser", "password": "leser-passwort-1"})
        assert r.get(f"/api/v1/devices/{d['id']}").json()["urls"][0]["url"] == "https://nas.kunde.de:5001"
        assert r.post(f"/api/v1/devices/{d['id']}/urls", json={"url": "https://x.de"}).status_code == 403
        assert r.delete(f"/api/v1/device-urls/{u['id']}").status_code == 403
