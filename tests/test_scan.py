"""0.5: Netzwerk-Scan (Netzwerkzugriffe durch Attrappen ersetzt)."""
import os
import struct
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import netscan
from app.db import connect
from app.main import app
from app.timeutil import now_utc, to_utc_str

from .fresh import fresh_db

PW = os.environ["ITD_ADMIN_PASSWORD"]

# Attrappe: was im Netz „antwortet“
NET = {
    "192.168.10.1": {"ports": [53, 80, 443], "mac": "3C:A6:2F:00:00:01", "name": "fritz"},       # Router (AVM)
    "192.168.10.5": {"ports": [5000, 5001, 445], "mac": "00:11:32:C4:55:01", "name": "praxis-nas"},
    "192.168.10.21": {"ports": [], "mac": "8C:04:BA:3E:11:F2", "name": "EMPFANG-PC", "refused": True},  # Firewall: nur RST
    "192.168.10.52": {"ports": [80, 9100], "mac": "A0:D3:C1:4F:2A:1C", "name": ""},             # neuer Drucker
    "192.168.10.148": {"ports": [], "mac": "F2:11:7B:90:3C:AA", "name": "", "arp_only": True},  # Handy, nur ARP
}


@pytest.fixture()
def fake(monkeypatch):
    def probe(ip, port, timeout):
        h = NET.get(ip)
        if not h or h.get("arp_only"):
            return None
        if port in h["ports"]:
            return "open"
        return "closed" if h.get("refused") or h["ports"] else None
    monkeypatch.setattr(netscan, "probe", probe)
    monkeypatch.setattr(netscan, "read_arp", lambda: {ip: h["mac"] for ip, h in NET.items()})
    monkeypatch.setattr(netscan, "dns_name", lambda ip: NET.get(ip, {}).get("name", ""))
    monkeypatch.setattr(netscan, "netbios_name", lambda ip, timeout=0.8: "")


@pytest.fixture()
def admin(tmp_path):
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def setup_net(c):
    net = c.post("/api/v1/networks", json={"name": "Praxis-LAN", "cidr": "192.168.10.0/24", "gateway": "192.168.10.1", "scan": True}).json()
    types = {t["name"]: t["id"] for t in c.get("/api/v1/device-types").json()}
    c.post("/api/v1/devices", json={"name": "Router", "type_id": types["Router / Firewall"], "ip": "192.168.10.1"})
    nas = c.post("/api/v1/devices", json={"name": "NAS", "type_id": types["NAS / Server"], "ip": "192.168.10.5"}).json()
    c.patch(f"/api/v1/ips/{nas['ip_list'][0]['id']}", json={"mac": "00:11:32:00:00:99"})  # andere MAC in der Doku
    c.post("/api/v1/devices", json={"name": "Empfang-PC", "type_id": types["PC"], "ip": "192.168.10.21"})
    old = c.post("/api/v1/devices", json={"name": "Ersatz-Laptop", "type_id": types["Laptop"], "ip": "192.168.10.40"}).json()
    return net, types, old


def test_network_scan_flag_rules(admin):
    assert admin.post("/api/v1/networks", json={"name": "Groß", "cidr": "10.0.0.0/16", "scan": True}).status_code == 400
    assert admin.post("/api/v1/networks", json={"name": "v6", "cidr": "fd00::/64", "scan": True}).status_code == 400
    n = admin.post("/api/v1/networks", json={"name": "ok", "cidr": "10.1.0.0/22", "scan": True}).json()
    assert n["scan"] is True
    assert admin.patch(f"/api/v1/networks/{n['id']}", json={"cidr": "10.0.0.0/8"}).status_code == 200  # Größe ändern …
    assert admin.post("/api/v1/scan/start").status_code == 400  # … dann wird es nicht mehr gescannt


def test_scan_results_and_actions(admin, fake):
    net, types, old = setup_net(admin)
    conn = connect()
    try:
        rid = netscan.scan(conn, "manual", 1)
        run = conn.execute("SELECT * FROM scan_runs WHERE id = ?", (rid,)).fetchone()
        assert run["addresses"] == 254 and run["hosts_up"] == 5
        # Laptop „lange nicht gesehen“: letzter Kontakt vor 40 Tagen
        conn.execute("UPDATE ip_addresses SET last_seen = ? WHERE ip = '192.168.10.40'", (to_utc_str(now_utc() - timedelta(days=40)),))
    finally:
        conn.close()
    r = admin.get("/api/v1/scan").json()
    new = {h["ip"]: h for h in r["new"]}
    assert set(new) == {"192.168.10.52", "192.168.10.148"}
    assert new["192.168.10.52"]["type_name"] == "Drucker" and new["192.168.10.52"]["vendor"] == "HP"
    assert new["192.168.10.148"]["vendor"] == "zufällige MAC" and new["192.168.10.148"]["type_name"] == "Smartphone / Tablet"
    assert [m["device_name"] for m in r["mismatch"]] == ["NAS"]
    fill = {f["ip"]: f for f in r["fill"]}
    assert fill["192.168.10.21"]["mac"] == "8C:04:BA:3E:11:F2" and fill["192.168.10.21"]["hostname"] == "EMPFANG-PC"
    assert fill["192.168.10.1"]["hostname"] == "fritz"
    assert [s["device_name"] for s in r["stale"]] == ["Ersatz-Laptop"]
    ips = {i["ip"]: i for i in admin.get(f"/api/v1/ips?network_id={net['id']}").json()}
    assert ips["192.168.10.21"]["last_seen"] and not ips["192.168.10.40"]["last_seen"].startswith(now_utc().date().isoformat())
    # übernehmen
    h = new["192.168.10.52"]
    assert admin.post("/api/v1/scan/adopt", json={"items": [{"ip": h["ip"], "network_id": h["network_id"], "name": "Drucker Flur",
                                                             "type_id": h["type_id"], "mac": h["mac"]}]}).json() == {"created": 1}
    assert admin.post("/api/v1/scan/fill", json={"items": [{"ip_id": f["ip_id"], "mac": f["mac"] or None, "hostname": f["hostname"] or None}
                                                           for f in r["fill"]]}).json()["updated"] == len(r["fill"])
    admin.post("/api/v1/scan/ignore", json={"keys": ["new:mac:F2:11:7B:90:3C:AA", f"mac:{r['mismatch'][0]['ip_id']}:{r['mismatch'][0]['mac_now']}"]})
    r2 = admin.get("/api/v1/scan").json()
    assert r2["new"] == [] and r2["fill"] == [] and r2["mismatch"] == []
    dev = [d for d in admin.get("/api/v1/devices").json() if d["name"] == "Drucker Flur"][0]
    assert dev["type_name"] == "Drucker" and dev["ips"] == "192.168.10.52"
    assert "Netzwerk-Scan" in admin.get(f"/api/v1/devices/{dev['id']}").json()["history"][0]["text"]
    assert admin.post("/api/v1/scan/ignore", json={"keys": ["quatsch"]}).status_code == 400
    assert admin.get("/api/v1/overview").json()["scan_new"] == 0
    admin.delete("/api/v1/scan/ignore")
    assert admin.get("/api/v1/overview").json()["scan_new"] == 1


def test_scan_nightly_and_reader(admin, fake):
    setup_net(admin)
    conn = connect()
    try:
        from datetime import datetime
        from app.timeutil import today_local, tz
        t = today_local()
        assert netscan.run_due(conn, datetime(t.year, t.month, t.day, 2, 0, tzinfo=tz())) is None
        assert netscan.run_due(conn, datetime(t.year, t.month, t.day, 4, 0, tzinfo=tz()))
        assert netscan.run_due(conn, datetime(t.year, t.month, t.day, 5, 0, tzinfo=tz())) is None  # einmal pro Tag
    finally:
        conn.close()
    admin.post("/api/v1/users", json={"username": "leser", "display_name": "Leser", "password": "leser-pass1"})
    with TestClient(app) as r:
        r.post("/api/v1/auth/login", json={"username": "leser", "password": "leser-pass1"})
        assert r.get("/api/v1/scan").status_code == 403 and r.post("/api/v1/scan/start").status_code == 403
        assert r.get("/api/v1/overview").json()["scan_new"] == 0


def test_helpers():
    assert netscan.vendor("00:11:32:AA:BB:CC") == "Synology" and netscan.vendor("F2:00:00:00:00:00") == "zufällige MAC"
    assert netscan.guess_type([9100], "", False) == "Drucker"
    assert netscan.guess_type([3389], "", False) == "PC"
    assert netscan.guess_type([80], "", True) == "Router / Firewall"
    assert netscan.check_network("192.168.0.0/22") is None and netscan.check_network("192.168.0.0/21")
    # NetBIOS-Antwort auswerten
    import socket as so

    class FakeSock:
        def __init__(self, *a): pass
        def settimeout(self, t): pass
        def sendto(self, pkt, addr): self.tid = pkt[:2]
        def close(self): pass
        def recvfrom(self, n):
            names = b"WORKGROUP      \x00" + struct.pack(">H", 0x8400) + b"EMPFANG-PC     \x00" + struct.pack(">H", 0x0400)
            return self.tid + b"\x84\x00" + b"\x00" * 8 + b"\x20" + b"A" * 32 + b"\x00" + b"\x00\x21\x00\x01" + b"\x00" * 4 + b"\x00\x41" + b"\x02" + names, None
    orig = so.socket
    so.socket = FakeSock
    try:
        assert netscan.netbios_name("192.168.10.21") == "EMPFANG-PC"
    finally:
        so.socket = orig
