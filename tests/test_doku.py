"""Stammdaten 0.2: Standorte, Gerätetypen, Geräte, Netze, IP-Adressen, Lizenzen, Kontakte, Anhänge, Suche, Übersicht."""
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.timeutil import today_local

from .fresh import fresh_db

PW = os.environ["ITD_ADMIN_PASSWORD"]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
PDF = b"%PDF-1.4\n%test\n"


@pytest.fixture()
def admin(tmp_path):
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


@pytest.fixture()
def reader(admin):
    admin.post("/api/v1/users", json={"username": "leser", "display_name": "Leser", "password": "leser-pass1"})
    with TestClient(app) as c:
        assert c.post("/api/v1/auth/login", json={"username": "leser", "password": "leser-pass1"}).status_code == 200
        yield c


def type_id(c, name="PC"):
    return [t for t in c.get("/api/v1/device-types").json() if t["name"] == name][0]["id"]


def day(n):
    return (today_local() + timedelta(days=n)).isoformat()


def test_seeded_site_and_types(admin):
    sites = admin.get("/api/v1/sites").json()
    assert [s["name"] for s in sites] == ["Hauptstandort"]
    names = [t["name"] for t in admin.get("/api/v1/device-types").json()]
    assert names[:3] == ["PC", "Laptop", "NAS / Server"] and "Sonstiges" in names


def test_reader_sees_but_cannot_change(admin, reader):
    admin.post("/api/v1/devices", json={"name": "Empfang-PC", "type_id": type_id(admin)})
    assert reader.get("/api/v1/devices").json()[0]["name"] == "Empfang-PC"
    assert reader.get("/api/v1/overview").status_code == 200
    for method, path, body in (("post", "/api/v1/devices", {"name": "x", "type_id": 1}),
                               ("post", "/api/v1/licenses", {"name": "x"}),
                               ("post", "/api/v1/contacts", {"name": "x"}),
                               ("post", "/api/v1/networks", {"name": "x"}),
                               ("post", "/api/v1/sites", {"name": "x"}),
                               ("post", "/api/v1/device-types", {"name": "x"}),
                               ("delete", "/api/v1/devices/1", None)):
        r = getattr(reader, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 403, path


def test_device_with_ip_network_and_history(admin):
    net = admin.post("/api/v1/networks", json={"name": "Praxis-LAN", "cidr": "192.168.10.7/24", "gateway": "192.168.10.1",
                                               "dhcp_from": "192.168.10.100", "dhcp_to": "192.168.10.199", "vlan": 1}).json()
    assert net["cidr"] == "192.168.10.0/24" and net["size"] == 254
    d = admin.post("/api/v1/devices", json={"name": "Empfang-PC", "type_id": type_id(admin), "ip": "192.168.10.21",
                                            "warranty_until": day(30), "serial": "7H2KQ93"}).json()
    assert d["site_name"] == "Hauptstandort"  # einziger Standort automatisch
    assert d["ip_list"][0]["ip"] == "192.168.10.21" and d["ip_list"][0]["network_id"] == net["id"]
    assert d["warranty_days"] == 30
    # doppelte IP im selben Netz
    r = admin.post("/api/v1/ips", json={"ip": "192.168.10.21"})
    assert r.status_code == 409 and "Empfang-PC" in r.json()["detail"]
    assert admin.post("/api/v1/ips", json={"ip": "999.1.1.1"}).status_code == 400
    # ändern → Verlauf
    d = admin.patch(f"/api/v1/devices/{d['id']}", json={"room": "Empfang", "status": "stock", "notes": "geheim"}).json()
    texts = [h["text"] for h in d["history"]]
    assert any("Raum: – → Empfang" in t and "Status: aktiv → im Lager" in t and "Notizen geändert" in t for t in texts)
    assert not any("geheim" in t for t in texts)
    # IP ändern erscheint im Verlauf des Geräts
    ip_id = d["ip_list"][0]["id"]
    admin.patch(f"/api/v1/ips/{ip_id}", json={"ip": "192.168.10.22"})
    hist = admin.get(f"/api/v1/devices/{d['id']}").json()["history"]
    assert "192.168.10.21 → 192.168.10.22" in hist[0]["text"]
    # freie IPs: ohne Gateway, DHCP-Bereich und belegte
    ips = admin.get(f"/api/v1/ips?network_id={net['id']}&free=1").json()
    free = {i["ip"] for i in ips if i.get("free")}
    assert "192.168.10.1" not in free and "192.168.10.150" not in free and "192.168.10.22" not in free
    assert "192.168.10.23" in free and "192.168.10.200" in free
    assert len(free) == 254 - 1 - 100 - 1


def test_device_list_filters_counts_and_retired(admin):
    pc, nas = type_id(admin), type_id(admin, "NAS / Server")
    admin.post("/api/v1/devices", json={"name": "A", "type_id": pc})
    admin.post("/api/v1/devices", json={"name": "B", "type_id": nas, "manufacturer": "Synology"})
    admin.post("/api/v1/devices", json={"name": "C", "type_id": pc, "status": "retired"})
    assert [d["name"] for d in admin.get("/api/v1/devices").json()] == ["A", "B"]
    assert [d["name"] for d in admin.get("/api/v1/devices?status=retired").json()] == ["C"]
    assert [d["name"] for d in admin.get("/api/v1/devices?q=synol").json()] == ["B"]
    counts = admin.get("/api/v1/devices/counts").json()
    assert counts["status"] == {"active": 2, "retired": 1} and counts["type"][str(pc)] == 1
    assert admin.post("/api/v1/devices", json={"name": "x"}).status_code == 400
    assert admin.post("/api/v1/devices", json={"name": "x", "type_id": pc, "status": "kaputt"}).status_code == 400
    assert "Synology" in admin.get("/api/v1/devices/suggest").json()["manufacturer"]


def test_device_types_rename_move_merge(admin):
    pc = type_id(admin)
    assert admin.post("/api/v1/device-types", json={"name": "pc"}).status_code == 409
    types = admin.post("/api/v1/device-types", json={"name": "Waage", "icon": "⚖️"}).json()
    waage = [t for t in types if t["name"] == "Waage"][0]
    assert types[-1]["name"] == "Waage"
    types = admin.post(f"/api/v1/device-types/{waage['id']}/move?up=true").json()
    assert types[-2]["name"] == "Waage"
    admin.post("/api/v1/devices", json={"name": "Waage 1", "type_id": waage["id"]})
    assert admin.delete(f"/api/v1/device-types/{waage['id']}").status_code == 409
    admin.delete(f"/api/v1/device-types/{waage['id']}?into={pc}")
    assert admin.get("/api/v1/devices").json()[0]["type_name"] == "PC"


def test_sites_and_networks(admin):
    s2 = admin.post("/api/v1/sites", json={"name": "Filiale", "isp_provider": "Telekom", "isp_public_ip": "203.0.113.17"}).json()
    assert s2["isp_provider"] == "Telekom"
    net = admin.post("/api/v1/networks", json={"name": "Filial-LAN", "cidr": "10.0.0.0/24", "site_id": s2["id"]}).json()
    assert admin.post("/api/v1/networks", json={"name": "x", "cidr": "kein netz"}).status_code == 400
    assert admin.delete(f"/api/v1/sites/{s2['id']}").status_code == 409
    admin.delete(f"/api/v1/networks/{net['id']}")
    assert admin.delete(f"/api/v1/sites/{s2['id']}").status_code == 200
    only = admin.get("/api/v1/sites").json()[0]
    assert admin.delete(f"/api/v1/sites/{only['id']}").status_code == 400
    # IPs ohne Netz werden beim Anlegen eines passenden Netzes zugeordnet
    ip = admin.post("/api/v1/ips", json={"ip": "172.16.0.5"}).json()
    assert ip["network_id"] is None
    n2 = admin.post("/api/v1/networks", json={"name": "Server", "cidr": "172.16.0.0/16"}).json()
    assert admin.get(f"/api/v1/ips?network_id={n2['id']}").json()[0]["ip"] == "172.16.0.5"
    assert admin.get("/api/v1/networks").json()[0]["used"] == 1


def test_links(admin):
    pc = type_id(admin)
    a = admin.post("/api/v1/devices", json={"name": "PC", "type_id": pc}).json()
    b = admin.post("/api/v1/devices", json={"name": "Switch", "type_id": type_id(admin, "Switch")}).json()
    d = admin.post(f"/api/v1/devices/{a['id']}/links", json={"device_id": b["id"], "note": "Port 7"}).json()
    assert d["links"][0]["name"] == "Switch" and d["links"][0]["note"] == "Port 7"
    other = admin.get(f"/api/v1/devices/{b['id']}").json()
    assert other["links"][0]["name"] == "PC"
    assert admin.post(f"/api/v1/devices/{b['id']}/links", json={"device_id": a["id"]}).status_code == 409
    assert admin.post(f"/api/v1/devices/{a['id']}/links", json={"device_id": a["id"]}).status_code == 400
    admin.delete(f"/api/v1/device-links/{d['links'][0]['id']}")
    assert admin.get(f"/api/v1/devices/{a['id']}").json()["links"] == []


def test_licenses_assign_and_due(admin):
    pc = type_id(admin)
    dev = admin.post("/api/v1/devices", json={"name": "PC 1", "type_id": pc}).json()
    lic = admin.post("/api/v1/licenses", json={"name": "ESET", "kind": "subscription", "seats": 12, "expires_on": day(-3)}).json()
    m365 = admin.post("/api/v1/licenses", json={"name": "M365", "seats": 8, "seats_used": 8, "expires_on": day(24)}).json()
    admin.post("/api/v1/licenses", json={"name": "Domain", "kind": "domain", "expires_on": day(400)})
    assert admin.post("/api/v1/licenses", json={"name": "x", "kind": "quatsch"}).status_code == 400
    lic = admin.post(f"/api/v1/licenses/{lic['id']}/devices", json={"device_id": dev["id"]}).json()
    assert lic["used"] == 1 and lic["devices"][0]["name"] == "PC 1"
    assert admin.post(f"/api/v1/licenses/{lic['id']}/devices", json={"device_id": dev["id"]}).status_code == 409
    assert m365["used"] == 8
    assert admin.get(f"/api/v1/devices/{dev['id']}").json()["licenses"][0]["name"] == "ESET"
    assert [l["name"] for l in admin.get("/api/v1/licenses?filter=expired").json()] == ["ESET"]
    assert [l["name"] for l in admin.get("/api/v1/licenses?filter=due").json()] == ["M365"]
    assert admin.get("/api/v1/licenses/counts").json() == {"all": 3, "due": 1, "expired": 1}
    upd = admin.patch(f"/api/v1/licenses/{m365['id']}", json={"kind": "maintenance"}).json()
    assert "Art: Software → Wartungsvertrag" in upd["history"][0]["text"]
    admin.delete(f"/api/v1/licenses/{lic['id']}/devices/{dev['id']}")
    assert admin.get(f"/api/v1/devices/{dev['id']}").json()["licenses"] == []


def test_overview(admin):
    pc = type_id(admin)
    admin.post("/api/v1/devices", json={"name": "NAS", "type_id": pc, "warranty_until": day(61)})
    admin.post("/api/v1/devices", json={"name": "Alt", "type_id": pc, "warranty_until": day(10), "status": "retired"})
    admin.post("/api/v1/devices", json={"name": "Abgelaufen", "type_id": pc, "warranty_until": day(-10)})
    admin.post("/api/v1/licenses", json={"name": "ESET", "expires_on": day(-3)})
    admin.post("/api/v1/contacts", json={"name": "Tim", "emergency": True, "external": True, "mobile": "0152 5230 2582"})
    admin.post("/api/v1/contacts", json={"name": "Lisa"})
    o = admin.get("/api/v1/overview").json()
    assert o["devices"] == 2 and o["contacts"] == 2 and o["contacts_external"] == 1
    assert [(d["name"], d["what"]) for d in o["due"]] == [("ESET", "Lizenz"), ("NAS", "Garantie")]
    assert o["licenses_due"] == 1
    assert [c["name"] for c in o["emergency"]] == ["Tim"]
    assert o["recent"][0]["name"] == "Lisa" and o["recent"][0]["kind"] == "contact" and o["recent"][0]["exists"]


def test_search(admin):
    pc = type_id(admin)
    admin.post("/api/v1/devices", json={"name": "Empfang-PC", "type_id": pc, "ip": "192.168.10.21", "serial": "7H2KQ93"})
    admin.post("/api/v1/contacts", json={"name": "Theorg-Support", "phone": "0800 1021 555"})
    admin.post("/api/v1/licenses", json={"name": "Theorg Arbeitsplätze", "vendor": "SOVDWAER"})
    r = admin.get("/api/v1/search?q=10.21").json()
    assert r["ips"][0]["device_name"] == "Empfang-PC"
    assert admin.get("/api/v1/search?q=7h2kq").json()["devices"][0]["name"] == "Empfang-PC"
    assert admin.get("/api/v1/search?q=1021555").json()["contacts"][0]["name"] == "Theorg-Support"
    r = admin.get("/api/v1/search?q=theorg").json()
    assert r["contacts"] and r["licenses"]


def test_contacts(admin):
    assert admin.post("/api/v1/contacts", json={"name": "x", "email": "kaputt"}).status_code == 400
    c = admin.post("/api/v1/contacts", json={"name": "Telekom", "external": True, "customer_no": "4711"}).json()
    assert c["external"] is True and c["emergency"] is False
    admin.post("/api/v1/contacts", json={"name": "Anna", "emergency": True})
    assert [x["name"] for x in admin.get("/api/v1/contacts").json()] == ["Anna", "Telekom"]
    assert [x["name"] for x in admin.get("/api/v1/contacts?filter=external").json()] == ["Telekom"]
    c = admin.patch(f"/api/v1/contacts/{c['id']}", json={"emergency": True}).json()
    assert "Notfall: nein → ja" in c["history"][0]["text"]


def test_attachments(admin, reader):
    pc = type_id(admin)
    dev = admin.post("/api/v1/devices", json={"name": "PC", "type_id": pc}).json()
    up = admin.post(f"/api/v1/attachments?owner_type=device&owner_id={dev['id']}&name=Rechnung", content=PDF)
    assert up.status_code == 201 and up.json()["name"] == "Rechnung.pdf"
    bad = admin.post(f"/api/v1/attachments?owner_type=device&owner_id={dev['id']}&name=x.svg", content=b"<svg onload=alert(1)>")
    assert bad.status_code == 400
    assert admin.post(f"/api/v1/attachments?owner_type=device&owner_id={dev['id']}&name=x.png",
                      content=PNG + b"\x00" * (10 * 1024 * 1024)).status_code == 413
    assert admin.post(f"/api/v1/attachments?owner_type=device&owner_id=999&name=x.png", content=PNG).status_code == 404
    assert admin.post(f"/api/v1/attachments?owner_type=device&owner_id={dev['id']}&role=diagram&name=x.png", content=PNG).status_code == 400
    assert reader.post(f"/api/v1/attachments?owner_type=device&owner_id={dev['id']}&name=x.png", content=PNG).status_code == 403
    files = admin.get(f"/api/v1/devices/{dev['id']}").json()["files"]
    assert files[0]["name"] == "Rechnung.pdf"
    r = reader.get(f"/api/v1/attachments/{files[0]['id']}?inline=1")
    assert r.content == PDF and r.headers["content-disposition"].startswith("attachment")  # PDF nie inline
    assert r.headers["x-content-type-options"] == "nosniff" and "sandbox" in r.headers["content-security-policy"]
    # Netzwerkplan: nur einer pro Standort, neuer ersetzt alten
    site = admin.get("/api/v1/sites").json()[0]
    for _ in range(2):
        assert admin.post(f"/api/v1/attachments?owner_type=site&owner_id={site['id']}&role=diagram&name=plan.png",
                          content=PNG).status_code == 201
    site = admin.get("/api/v1/sites").json()[0]
    assert site["diagram"]["name"] == "plan.png"
    img = admin.get(f"/api/v1/attachments/{site['diagram']['id']}?inline=1")
    assert img.headers["content-disposition"].startswith("inline") and img.headers["content-type"] == "image/png"
    # Gerät löschen → Anhänge weg
    admin.delete(f"/api/v1/devices/{dev['id']}")
    assert admin.get(f"/api/v1/attachments/{files[0]['id']}").status_code == 404


def test_csv_export_escapes_formulas(admin):
    admin.post("/api/v1/devices", json={"name": "=HYPERLINK(\"x\")", "type_id": type_id(admin)})
    r = admin.get("/api/v1/devices/export.csv")
    assert r.status_code == 200 and "'=HYPERLINK" in r.text
    log = admin.get("/api/v1/audit?category=doku").json()["entries"]
    assert log and log[0]["subject"] == "Gerät"
