"""Tresor 0.3: Krypto, Einrichten, Entsperren, Auto-Sperre, Einladung, Notfall-Schlüssel, Zugangsdaten, Lizenzschlüssel."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import vault, vault_crypto as vc
from app.config import settings
from app.main import app

from .fresh import fresh_db

PW = os.environ["ITD_ADMIN_PASSWORD"]
VPW = "tresor-passwort-1"


# --- Krypto -------------------------------------------------------------------

def test_aes_vectors():
    w = vc.expand_key(bytes(range(32)))
    assert vc.encrypt_block(w, bytes.fromhex("00112233445566778899aabbccddeeff")).hex() == "8ea2b7ca516745bfeafc49904b496089"
    k = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
    iv = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")
    pt = bytes.fromhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51")
    assert vc.aes_ctr(k, iv, pt).hex() == "601ec313775789a5b7a7f504bbf3d228f443e3ca4d62b59aca84e990cacaf5c5"


def test_encrypt_roundtrip_tamper_and_binding():
    key = vc.new_key()
    tok = vc.encrypt_text(key, "Gëhéim 🔐" * 50, "cred:1:password")
    assert vc.decrypt_text(key, tok, "cred:1:password") == "Gëhéim 🔐" * 50
    assert vc.encrypt_text(key, "x", "a") != vc.encrypt_text(key, "x", "a")  # zufällige Nonce
    with pytest.raises(vc.CryptoError):
        vc.decrypt_text(key, tok, "cred:2:password")  # anderes Feld
    with pytest.raises(vc.CryptoError):
        vc.decrypt_text(vc.new_key(), tok, "cred:1:password")
    raw = bytearray(__import__("base64").b64decode(tok))
    raw[20] ^= 1
    with pytest.raises(vc.CryptoError):
        vc.decrypt_text(key, __import__("base64").b64encode(bytes(raw)).decode(), "cred:1:password")


def test_totp_and_codes():
    info = vc.parse_otp("GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ")
    assert vc.totp(info, 59)["code"] == "287082" and vc.totp(info, 1111111109)["code"] == "081804"
    u = vc.parse_otp("otpauth://totp/Microsoft:admin%40x.de?secret=JBSWY3DPEHPK3PXP&issuer=Microsoft&digits=8&period=60")
    assert u["digits"] == 8 and u["period"] == 60 and u["label"] == "Microsoft:admin@x.de"
    for bad in ("", "nicht base32!", "otpauth://hotp/x?secret=JBSWY3DP", "otpauth://totp/x?secret=JBSWY3DP&digits=12"):
        with pytest.raises(vc.CryptoError):
            vc.parse_otp(bad)
    rk = vc.new_recovery_key()
    assert len(rk.replace("-", "")) == 52 and vc.normalize_code(rk.lower().replace("-", " ")) == rk.replace("-", "")
    assert vc.normalize_code("ab0-1-8") == "ABOIB"


# --- API ------------------------------------------------------------------------

@pytest.fixture()
def admin(tmp_path):
    vault.close_all()
    with fresh_db(tmp_path):
        with TestClient(app) as c:
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": PW}).status_code == 200
            yield c


def login(username, password):
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", json={"username": username, "password": password}).status_code == 200
    return c


def setup_vault(c):
    r = c.post("/api/v1/vault/setup", json={"password": VPW})
    assert r.status_code == 200
    return r.json()["recovery_key"]


def test_setup_unlock_lock(admin):
    s = admin.get("/api/v1/vault/status").json()
    assert s == {**s, "initialized": False, "member": False, "unlocked": False, "can_use": True, "timeout_min": 15}
    assert admin.post("/api/v1/vault/setup", json={"password": "kurz"}).status_code == 400
    rk = setup_vault(admin)
    assert admin.post("/api/v1/vault/setup", json={"password": VPW}).status_code == 409
    s = admin.get("/api/v1/vault/status").json()
    assert s["initialized"] and s["member"] and s["unlocked"] and 890 < s["remaining"] <= 900
    admin.post("/api/v1/vault/lock")
    assert not admin.get("/api/v1/vault/status").json()["unlocked"]
    assert admin.post("/api/v1/vault/unlock", json={"password": "falsch-falsch"}).status_code == 401
    assert admin.post("/api/v1/vault/unlock", json={"password": VPW}).status_code == 200
    assert admin.get("/api/v1/vault/status").json()["unlocked"]
    # Abmelden sperrt
    admin.post("/api/v1/auth/logout")
    admin.post("/api/v1/auth/login", json={"username": "admin", "password": PW})
    assert not admin.get("/api/v1/vault/status").json()["unlocked"]
    assert rk.count("-") == 12
    log = admin.get("/api/v1/audit?category=tresor").json()["entries"]
    assert {"vault_setup", "vault_failed"} <= {e["action"] for e in log}


def test_unlock_rate_limit(admin):
    setup_vault(admin)
    for _ in range(5):
        assert admin.post("/api/v1/vault/unlock", json={"password": "falsch-falsch"}).status_code == 401
    assert admin.post("/api/v1/vault/unlock", json={"password": VPW}).status_code == 429
    from app.dsm_auth import clear_failures
    clear_failures(f"vault|{admin.get('/api/v1/me').json()['id']}")


def test_auto_lock(admin, monkeypatch):
    setup_vault(admin)
    base = time.monotonic()
    monkeypatch.setattr(vault.time, "monotonic", lambda: base + 899)
    assert admin.get("/api/v1/vault/status").json()["unlocked"]
    admin.get("/api/v1/me")  # Aktivität verlängert
    monkeypatch.setattr(vault.time, "monotonic", lambda: base + 899 + 600)
    assert admin.get("/api/v1/vault/status").json()["unlocked"]  # 600 s nach letzter Aktivität: noch offen
    monkeypatch.setattr(vault.time, "monotonic", lambda: base + 899 + 901)
    assert not admin.get("/api/v1/vault/status").json()["unlocked"]
    assert admin.patch("/api/v1/vault/settings", json={"timeout_min": 2}).status_code == 422
    assert admin.patch("/api/v1/vault/settings", json={"timeout_min": 30}).json()["timeout_min"] == 30


def test_credentials_encrypted_and_revealed(admin):
    dev_type = admin.get("/api/v1/device-types").json()[0]["id"]
    dev = admin.post("/api/v1/devices", json={"name": "Router", "type_id": dev_type}).json()
    body = {"title": "FRITZ!Box", "username": "admin", "url": "http://192.168.10.1", "owner_type": "device", "owner_id": dev["id"],
            "password": "Sup3r-Geheim!42", "notes": "Wiederherstellungscode XYZ-7Q4K-PLM2", "totp": "JBSWY3DPEHPK3PXP"}
    assert admin.post("/api/v1/credentials", json=body).status_code == 423  # Tresor nicht eingerichtet/offen
    setup_vault(admin)
    c = admin.post("/api/v1/credentials", json=body).json()
    assert c["has_password"] and c["has_notes"] and c["has_totp"] and c["owner_name"] == "Router"
    assert "password" not in c and "password_enc" not in c
    # Klartext steht nirgends in der Datenbankdatei
    admin.get("/api/v1/vault/status")
    raw = open(settings.db_path, "rb").read() + (open(str(settings.db_path) + "-wal", "rb").read()
                                                  if os.path.exists(str(settings.db_path) + "-wal") else b"")
    assert b"Sup3r-Geheim" not in raw and b"Wiederherstellungscode" not in raw and b"XYZ-7Q4K" not in raw and b"JBSWY3DP" not in raw
    r = admin.post(f"/api/v1/credentials/{c['id']}/reveal", json={"field": "password", "purpose": "copy"})
    assert r.json() == {"value": "Sup3r-Geheim!42"}
    code = admin.post(f"/api/v1/credentials/{c['id']}/reveal", json={"field": "totp"}).json()
    assert code["code"] == vc.totp(vc.parse_otp("JBSWY3DPEHPK3PXP"))["code"] and code["period"] == 30
    log = admin.get("/api/v1/audit?category=tresor").json()["entries"]
    assert any(e["action"] == "secret_copied" and "FRITZ!Box – Passwort kopiert" in e["text"] for e in log)
    # ändern: neues Passwort, Notiz entfernen
    c = admin.patch(f"/api/v1/credentials/{c['id']}", json={"password": "neu-neu-neu", "notes": ""}).json()
    assert c["has_password"] and not c["has_notes"]
    assert "Passwort gesetzt; Notiz entfernt" in c["history"][0]["text"]
    assert admin.patch(f"/api/v1/credentials/{c['id']}", json={"totp": "kaputt!"}).status_code == 400
    # gesperrt: Liste geht, Geheimnisse nicht
    admin.post("/api/v1/vault/lock")
    assert admin.get(f"/api/v1/credentials?owner_type=device&owner_id={dev['id']}").json()[0]["title"] == "FRITZ!Box"
    assert admin.post(f"/api/v1/credentials/{c['id']}/reveal", json={"field": "password"}).status_code == 423
    assert admin.patch(f"/api/v1/credentials/{c['id']}", json={"password": "x"}).status_code == 423
    assert admin.patch(f"/api/v1/credentials/{c['id']}", json={"title": "FRITZ!Box 7590"}).status_code == 200  # ohne Geheimnis ok
    assert admin.get("/api/v1/credentials/counts").json()["device"] == 1
    assert admin.get("/api/v1/search?q=fritz").json()["credentials"][0]["title"] == "FRITZ!Box 7590"


def test_reader_never_sees_credentials(admin):
    setup_vault(admin)
    admin.post("/api/v1/credentials", json={"title": "NAS-Admin", "password": "x" * 12})
    admin.post("/api/v1/users", json={"username": "leser", "display_name": "Leser", "password": "leser-pass1"})
    r = login("leser", "leser-pass1")
    assert r.get("/api/v1/credentials").status_code == 403
    assert r.get("/api/v1/search?q=NAS").json()["credentials"] == []
    assert all(x["kind"] != "credential" for x in r.get("/api/v1/overview").json()["recent"])
    assert r.post("/api/v1/vault/unlock", json={"password": VPW}).status_code == 403
    assert r.get("/api/v1/vault/status").json()["can_use"] is False


def test_invite_join_remove(admin):
    setup_vault(admin)
    cid = admin.post("/api/v1/credentials", json={"title": "M365", "password": "m365-pass"}).json()["id"]
    anna = admin.post("/api/v1/users", json={"username": "anna", "display_name": "Anna", "password": "anna-pass1", "is_admin": True}).json()
    lisa = admin.post("/api/v1/users", json={"username": "lisa", "display_name": "Lisa", "password": "lisa-pass1"}).json()
    assert admin.post("/api/v1/vault/invite", json={"user_id": lisa["id"]}).status_code == 400  # kein Vollzugriff
    admin.post("/api/v1/vault/lock")
    assert admin.post("/api/v1/vault/invite", json={"user_id": anna["id"]}).status_code == 423
    admin.post("/api/v1/vault/unlock", json={"password": VPW})
    inv = admin.post("/api/v1/vault/invite", json={"user_id": anna["id"]}).json()
    assert len(inv["code"]) == 19
    a = login("anna", "anna-pass1")
    st = a.get("/api/v1/vault/status").json()
    assert st["invited"] and not st["member"]
    assert a.post("/api/v1/vault/unlock", json={"password": VPW}).status_code == 403
    assert a.post("/api/v1/vault/join", json={"code": "AAAA-BBBB-CCCC-DDDD", "password": "annas-tresor-1"}).status_code == 400
    assert a.post("/api/v1/vault/join", json={"code": inv["code"].lower().replace("-", " "), "password": "annas-tresor-1"}).status_code == 200
    assert a.post(f"/api/v1/credentials/{cid}/reveal", json={"field": "password"}).json()["value"] == "m365-pass"
    m = admin.get("/api/v1/vault/members").json()
    assert {x["name"] for x in m["members"]} == {"Administrator", "Anna"} and m["invites"] == []
    # Anna verliert Vollzugriff → Zugang weg, Sitzung zu
    admin.patch(f"/api/v1/users/{anna['id']}", json={"is_admin": False})
    assert {x["name"] for x in admin.get("/api/v1/vault/members").json()["members"]} == {"Administrator"}
    # letzter Zugang bleibt
    me = admin.get("/api/v1/me").json()["id"]
    assert admin.delete(f"/api/v1/vault/members/{me}").status_code == 400


def test_recovery_and_renew(admin):
    rk = setup_vault(admin)
    cid = admin.post("/api/v1/credentials", json={"title": "NAS", "password": "nas-pass"}).json()["id"]
    pdf = admin.post("/api/v1/vault/recovery-sheet", json={"recovery_key": rk})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert admin.post("/api/v1/vault/recovery-sheet", json={"recovery_key": "AAAA-BBBB"}).status_code == 400
    admin.post("/api/v1/vault/lock")
    assert admin.post("/api/v1/vault/recover", json={"recovery_key": rk.lower(), "new_password": "ganz-neues-pw-1"}).status_code == 200
    assert admin.post(f"/api/v1/credentials/{cid}/reveal", json={"field": "password"}).json()["value"] == "nas-pass"
    admin.post("/api/v1/vault/lock")
    assert admin.post("/api/v1/vault/unlock", json={"password": VPW}).status_code == 401
    assert admin.post("/api/v1/vault/unlock", json={"password": "ganz-neues-pw-1"}).status_code == 200
    new = admin.post("/api/v1/vault/recovery/renew").json()["recovery_key"]
    assert new != rk
    assert admin.post("/api/v1/vault/recover", json={"recovery_key": rk, "new_password": "noch-ein-pw-12"}).status_code == 400
    # Tresor-Passwort ändern
    assert admin.post("/api/v1/vault/password", json={"old_password": "falsch-falsch", "new_password": "x" * 12}).status_code == 400
    assert admin.post("/api/v1/vault/password", json={"old_password": "ganz-neues-pw-1", "new_password": "drittes-pw-123"}).status_code == 200
    from app.dsm_auth import clear_failures
    me = admin.get("/api/v1/me").json()["id"]
    for n in ("vault", "vault-recover"):
        clear_failures(f"{n}|{me}")


def test_license_key(admin):
    lic = admin.post("/api/v1/licenses", json={"name": "Windows 11 Pro"}).json()
    assert lic["has_key"] is False and "key_enc" not in lic
    assert admin.put(f"/api/v1/licenses/{lic['id']}/key", json={"key": "AAAAA-BBBBB"}).status_code == 423
    setup_vault(admin)
    assert admin.put(f"/api/v1/licenses/{lic['id']}/key", json={"key": "VK7JG-NPHTM-C97JM-9MPGT-3V66T"}).json() == {"has_key": True}
    assert admin.get("/api/v1/licenses").json()[0]["has_key"] is True
    assert admin.post(f"/api/v1/licenses/{lic['id']}/key/reveal", json={"purpose": "show"}).json()["value"] == "VK7JG-NPHTM-C97JM-9MPGT-3V66T"
    hist = [h["text"] for h in admin.get(f"/api/v1/licenses/{lic['id']}").json()["history"]]
    assert hist[:2] == ["Lizenzschlüssel angezeigt", "Lizenzschlüssel gesetzt"]
