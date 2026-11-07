"""0.9: Windows-Produktschlüssel vom Agent (versiegelt an den Tresor) und Selbstupdate der Agenten."""
import base64
import copy
import hashlib
import importlib.util
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import seal, winlicense
from app.db import connect
from app.dsm_auth import _fails
from app.main import app

from .fresh import fresh_db
from .test_agents import REPORT, send

PW = os.environ["ITD_ADMIN_PASSWORD"]
VPW = "Tresor-Passwort-123!"
ROOT = Path(__file__).resolve().parent.parent


def encode_key(key: str) -> bytes:
    """Gegenstück zu decode_digital_product_id (nur für Tests): Schlüssel → DigitalProductId-Bytes."""
    k = key.replace("-", "")
    n = k.index("N")
    rest = k[:n] + k[n + 1:]
    digits = [n] + [winlicense.CHARS.index(c) for c in rest]
    v = 0
    for d in digits:
        v = v * 24 + d
    b = bytearray(v.to_bytes(15, "little"))
    b[14] |= 0x08
    return bytes(52) + bytes(b) + bytes(100)


KEY = "TQ4NB-HKVYY-29XG7-2FRJ8-RXBM8"  # Testschlüssel (kein echter)


@pytest.fixture()
def admin(tmp_path):
    _fails.clear()
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def test_x25519_rfc7748_and_seal():
    k = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
    u = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
    assert seal.x25519(k, u).hex() == "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"
    a = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    b = bytes.fromhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
    assert seal.x25519(a, seal.x25519(b, seal.BASE)).hex() == "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"
    priv, pub = seal.keypair()
    t = seal.seal(pub, "geheim", "license:1:key")
    assert "geheim" not in t and seal.open_sealed(priv, t, "license:1:key") == "geheim"
    with pytest.raises(Exception):
        seal.open_sealed(priv, t, "license:2:key")  # an die Lizenz gebunden
    with pytest.raises(Exception):
        seal.open_sealed(seal.keypair()[0], t, "license:1:key")


def test_decode_and_filters():
    assert winlicense.decode_digital_product_id(encode_key(KEY)) == KEY
    info = winlicense.sanitize({"edition": "Windows 11 Pro", "description": "Windows(R) Operating System, RETAIL channel",
                                "status": 1, "partial": "RXBM8", "dpid": base64.b64encode(encode_key(KEY)).decode()})
    assert info["key"] == KEY and info["channel"] == "Einzelhandel (Retail)" and info["status"] == "aktiviert"
    generic = "VK7JG-NPHTM-C97JM-9MPGT-3V66T"
    info = winlicense.sanitize({"edition": "Windows 11 Pro", "description": "OEM_DM channel", "status": 1, "partial": "3V66T",
                                "dpid": base64.b64encode(encode_key(generic)).decode()})
    assert info["key"] == "" and info["digital"] is True
    info = winlicense.sanitize({"edition": "x", "partial": "AAAAA", "dpid": base64.b64encode(encode_key(KEY)).decode(),
                                "oem_key": "kaputt"})
    assert info["key"] == ""  # passt nicht zum aktiven Teilschlüssel, OEM-Wert ungültig
    info = winlicense.sanitize({"edition": "Windows 11 Home", "oem_key": "tq4nb-hkvyy-29xg7-2frj8-rxbm8"})
    assert info["key"] == KEY and info["key_source"] == "der Firmware (OEM)"


def test_windows_key_flow(admin):
    tok = admin.post("/api/v1/agents", json={"name": "timspc", "platform": "windows"}).json()["token"]
    c = TestClient(app)
    h = {"Authorization": "Bearer " + tok}
    assert c.get("/api/agent/v1/config", headers=h).json()["want_windows_key"] is False  # Tresor noch nie entsperrt
    rep = copy.deepcopy(REPORT)
    rep["windows_license"] = {"edition": "Windows 11 Pro", "description": "Windows(R) Operating System, RETAIL channel",
                              "status": 1, "partial": "RXBM8", "dpid": base64.b64encode(encode_key(KEY)).decode()}
    did = send(tok, rep).json()["device_id"]
    lic = connect().execute("SELECT * FROM licenses WHERE agent_ref IS NOT NULL").fetchone()
    assert lic and lic["key_sealed"] is None and lic["name"] == "Windows 11 Pro (PRAXIS-DC)"
    # Tresor einrichten → Schlüsselpaar → ab jetzt wird der Schlüssel angenommen und sofort versiegelt
    assert admin.post("/api/v1/vault/setup", json={"password": VPW}).status_code == 200
    assert c.get("/api/agent/v1/config", headers=h).json()["want_windows_key"] is True
    send(tok, rep)
    conn = connect()
    lic = conn.execute("SELECT * FROM licenses WHERE agent_ref IS NOT NULL").fetchone()
    assert lic["key_sealed"].startswith("x1:") and lic["key_enc"] is None
    raw = b"".join(bytes(str(tuple(r)), "utf-8") for t in ("licenses", "agents", "audit_log") for r in conn.execute(f"SELECT * FROM {t}"))
    assert KEY.encode() not in raw and KEY.replace("-", "").encode() not in raw  # nirgends im Klartext
    det = admin.get(f"/api/v1/devices/{did}/agent").json()["report"]
    assert "key" not in det["windows_license"] and det["windows_license"]["partial"] == "RXBM8"
    lics = admin.get("/api/v1/licenses").json()
    lj = [x for x in lics if x["id"] == lic["id"]][0]
    assert lj["has_key"] and lj["from_agent"] and "key_sealed" not in lj
    dev = admin.get(f"/api/v1/devices/{did}").json()
    assert any(x["id"] == lic["id"] for x in dev.get("licenses", [])) or \
        conn.execute("SELECT 1 FROM license_devices WHERE license_id = ? AND device_id = ?", (lic["id"], did)).fetchone()
    # anzeigen (Tresor offen) → Klartext, danach in normale Tresor-Form überführt
    r = admin.post(f"/api/v1/licenses/{lic['id']}/key/reveal", json={"purpose": "show"})
    assert r.status_code == 200 and r.json()["value"] == KEY
    lic = conn.execute("SELECT * FROM licenses WHERE id = ?", (lic["id"],)).fetchone()
    assert lic["key_enc"] and lic["key_sealed"] is None
    # gleicher Schlüssel nochmal → nichts ändert sich; Einstellung aus → kein Schlüssel mehr angefordert
    send(tok, rep)
    assert conn.execute("SELECT key_sealed FROM licenses WHERE id = ?", (lic["id"],)).fetchone()[0] is None
    admin.patch("/api/v1/agents-settings", json={"winkey": False})
    assert c.get("/api/agent/v1/config", headers=h).json()["want_windows_key"] is False


def test_update_info_in_config(admin):
    tok = admin.post("/api/v1/agents", json={"name": "srv"}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    cfg = TestClient(app).get("/api/agent/v1/config", headers=h).json()
    for name in ("itdoku-agent.py", "itdoku-agent.ps1"):
        info = cfg["update"][name]
        data = (ROOT / "app/agent" / name).read_bytes()
        assert info["sha256"] == hashlib.sha256(data).hexdigest() and info["version"] and info["path"] == "/agent/" + name
    assert admin.get("/api/v1/agents").json()["settings"]["latest"]["windows"] == cfg["update"]["itdoku-agent.ps1"]["version"]
    admin.patch("/api/v1/agents-settings", json={"autoupdate": False})
    assert "update" not in TestClient(app).get("/api/agent/v1/config", headers=h).json()


def test_python_agent_self_update(tmp_path, monkeypatch):
    installed = tmp_path / "itdoku-agent"
    shutil.copy(ROOT / "app/agent/itdoku-agent.py", installed)
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader("ag_upd", SourceFileLoader("ag_upd", str(installed)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "BIN", str(installed))
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    new = installed.read_bytes().replace(b'VERSION = "', b'VERSION = "9', 1)

    class H(BaseHTTPRequestHandler):
        body = new

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(H.body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    conf = {"url": f"http://127.0.0.1:{srv.server_port}", "token": "itd_x"}
    try:
        info = {"version": "9" + m.VERSION, "path": "/agent/itdoku-agent.py", "sha256": "0" * 64}
        assert m.self_update(conf, info, True) is False  # falsche Prüfsumme
        assert installed.read_bytes() != new
        assert m.self_update(conf, {**info, "version": "0.1"}, True) is False  # nicht neuer
        info["sha256"] = hashlib.sha256(new).hexdigest()
        assert m.self_update(conf, info, True) is True
        assert installed.read_bytes() == new
        monkeypatch.setattr(m, "BIN", str(tmp_path / "anderswo"))
        assert m.self_update(conf, info, True) is False  # nur die installierte Datei
    finally:
        srv.shutdown()
