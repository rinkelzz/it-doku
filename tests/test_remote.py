"""0.10: Fernwartung – TeamViewer/AnyDesk/RustDesk/andere Kennungen am Gerät, von Hand und vom Agent."""
import copy
import importlib.util
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import remote
from app.dsm_auth import _fails
from app.main import app

from .fresh import fresh_db
from .test_agents import REPORT, send

PW = os.environ["ITD_ADMIN_PASSWORD"]
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def admin(tmp_path):
    _fails.clear()
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def test_ids_and_links():
    assert remote.clean_id("teamviewer", "1 234 567 890") == "1234567890"
    assert remote.clean_id("teamviewer", "12-345") == ""
    assert remote.clean_id("anydesk", "praxis-pc@ad") == "praxis-pc@ad"
    assert remote.clean_id("anydesk", "javascript:alert(1)") == ""
    assert remote.pretty("teamviewer", "1234567890") == "1 234 567 890" and remote.pretty("anydesk", "123456789") == "123 456 789"
    assert remote.connect_url("teamviewer", "1234567890") == "https://start.teamviewer.com/1234567890"
    assert remote.connect_url("anydesk", "123456789") == "anydesk:123456789"
    assert remote.connect_url("rustdesk", "987654321") == "rustdesk://987654321"
    assert remote.connect_url("other", "x") == "" and remote.connect_url("teamviewer", "abc") == ""


def test_manual_crud_search_merge(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    d = admin.post("/api/v1/devices", json={"name": "Empfang", "type_id": types["PC"]}).json()
    url = f"/api/v1/devices/{d['id']}/remote"
    assert admin.post(url, json={"tool": "teamviewer", "remote_id": "abc"}).status_code == 400
    assert admin.post(url, json={"tool": "other", "remote_id": "x"}).status_code == 400  # Name fehlt
    assert admin.post(url, json={"tool": "bla", "remote_id": "1"}).status_code == 400
    tv = admin.post(url, json={"tool": "teamviewer", "remote_id": "1 234 567 890", "note": "unbeaufsichtigt"}).json()
    assert tv["remote_id"] == "1234567890" and tv["display"] == "1 234 567 890" and tv["url"].startswith("https://start.teamviewer.com/")
    assert admin.post(url, json={"tool": "teamviewer", "remote_id": "1234567890"}).status_code == 409
    rdp = admin.post(url, json={"tool": "other", "label": "RDP", "remote_id": "empfang.praxis.local"}).json()
    assert rdp["tool_label"] == "RDP" and rdp["url"] == ""
    det = admin.get(f"/api/v1/devices/{d['id']}").json()
    assert [r["tool"] for r in det["remote"]] == ["teamviewer", "other"]
    assert any("Fernwartung hinzugefügt" in h["text"] for h in det["history"])
    # Suche über die Kennung – auch mit Leerzeichen
    assert [x["name"] for x in admin.get("/api/v1/devices?q=234 567").json()] == ["Empfang"]
    assert [x["name"] for x in admin.get("/api/v1/search?q=1234567890").json()["devices"]] == ["Empfang"]
    assert admin.patch(f"/api/v1/device-remote/{rdp['id']}", json={"tool": "anydesk", "remote_id": "987654321"}).status_code == 200
    assert admin.get(f"/api/v1/devices/{d['id']}").json()["remote"][0]["tool"] == "anydesk"
    # Zusammenführen nimmt Einträge mit
    d2 = admin.post("/api/v1/devices", json={"name": "Empfang alt", "type_id": types["PC"]}).json()
    admin.post(f"/api/v1/devices/{d2['id']}/remote", json={"tool": "rustdesk", "remote_id": "555666777"})
    admin.post(f"/api/v1/devices/{d2['id']}/remote", json={"tool": "teamviewer", "remote_id": "1234567890"})
    admin.post(f"/api/v1/devices/{d['id']}/merge", json={"other_id": d2["id"]})
    assert sorted(r["tool"] for r in admin.get(f"/api/v1/devices/{d['id']}").json()["remote"]) == ["anydesk", "rustdesk", "teamviewer"]
    assert admin.delete(f"/api/v1/device-remote/{tv['id']}").status_code == 200


def test_agent_sync(admin):
    tok = admin.post("/api/v1/agents", json={"name": "pc"}).json()["token"]
    rep = copy.deepcopy(REPORT)
    rep["remote_tools"] = [{"tool": "teamviewer", "id": "1234567890", "version": "15.59"},
                           {"tool": "anydesk", "id": "987654321", "note": "Alias: praxis@ad"},
                           {"tool": "anydesk", "id": "987654321"}, {"tool": "evil", "id": "1"}, {"tool": "rustdesk", "id": "x;rm"}]
    did = send(tok, rep).json()["device_id"]
    admin.post(f"/api/v1/devices/{did}/remote", json={"tool": "other", "label": "RDP", "remote_id": "srv01"})
    r = admin.get(f"/api/v1/devices/{did}").json()["remote"]
    assert sorted((x["tool"], x["source"]) for x in r) == [("anydesk", "agent"), ("other", "manual"), ("teamviewer", "agent")]
    # Agent-Eintrag: Kennung nicht änderbar, Hinweis schon
    tv = [x for x in r if x["tool"] == "teamviewer"][0]
    admin.patch(f"/api/v1/device-remote/{tv['id']}", json={"tool": "teamviewer", "remote_id": "999999999", "note": "Hinweis"})
    tv = [x for x in admin.get(f"/api/v1/devices/{did}").json()["remote"] if x["tool"] == "teamviewer"][0]
    assert tv["remote_id"] == "1234567890" and tv["note"] == "Hinweis" and tv["version"] == "15.59"
    # AnyDesk deinstalliert → Agent-Eintrag weg, manueller bleibt
    rep["remote_tools"] = [{"tool": "teamviewer", "id": "1234567890", "version": "15.60"}]
    send(tok, rep)
    r = admin.get(f"/api/v1/devices/{did}").json()["remote"]
    assert sorted(x["tool"] for x in r) == ["other", "teamviewer"]
    # älterer Agent ohne Feld → nichts entfernen
    old = copy.deepcopy(REPORT)
    send(tok, old)
    assert len(admin.get(f"/api/v1/devices/{did}").json()["remote"]) == 2
    hist = str(admin.get(f"/api/v1/devices/{did}").json()["history"])
    assert "Fernwartung vom Agent: AnyDesk 987 654 321" in hist and "nicht mehr installiert" in hist


def test_reader_sees_ids_but_cannot_change(admin):
    types = {t["name"]: t["id"] for t in admin.get("/api/v1/device-types").json()}
    d = admin.post("/api/v1/devices", json={"name": "PC", "type_id": types["PC"]}).json()
    rid = admin.post(f"/api/v1/devices/{d['id']}/remote", json={"tool": "anydesk", "remote_id": "123456789"}).json()["id"]
    admin.post("/api/v1/users", json={"username": "leser", "display_name": "Leser", "password": "leser-passwort-1", "is_admin": False})
    with TestClient(app) as r:
        r.post("/api/v1/auth/login", json={"username": "leser", "password": "leser-passwort-1"})
        assert r.get(f"/api/v1/devices/{d['id']}").json()["remote"][0]["remote_id"] == "123456789"
        assert r.post(f"/api/v1/devices/{d['id']}/remote", json={"tool": "anydesk", "remote_id": "111222333"}).status_code == 403
        assert r.delete(f"/api/v1/device-remote/{rid}").status_code == 403


def test_python_agent_reads_ids(monkeypatch):
    spec = importlib.util.spec_from_file_location("ag_rem", str(ROOT / "app/agent/itdoku-agent.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    files = {"/etc/teamviewer/global.conf": "[int32] ClientID = 1234567890\n",
             "/etc/anydesk/system.conf": "ad.anynet.id=987654321\nad.anynet.alias=praxis@ad\n",
             "/root/.config/rustdesk/RustDesk.toml": "enc_id = ''\nid = '555666777'\npassword = 'geheim'\n",
             "/root/.config/rustdesk/RustDesk2.toml": "[options]\ncustom-rendezvous-server = 'rd.example.de'\n"}
    import glob as g
    monkeypatch.setattr(m, "IS_MAC", False)
    monkeypatch.setattr(m, "read", lambda p: files.get(p, ""))
    monkeypatch.setattr(g, "glob", lambda pat: [pat] if pat in files else [])
    monkeypatch.setattr(m, "which", lambda n: None)
    got = m.remote_tools()
    assert got == [{"tool": "teamviewer", "id": "1234567890"},
                   {"tool": "anydesk", "id": "987654321", "note": "Alias: praxis@ad"},
                   {"tool": "rustdesk", "id": "555666777", "note": "Server: rd.example.de"}]
    assert "geheim" not in str(got)
