"""Zugangsdaten im Tresor und Lizenzschlüssel.

Titel, Benutzername, Adresse und Zuordnung sind lesbar (Liste, Suche). Passwort, Notiz und 2FA-Geheimnis liegen
verschlüsselt in der Datenbank und werden nur bei offenem Tresor ent- oder verschlüsselt. Nur Vollzugriff.
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import vault
from .. import vault_crypto as vc
from ..db import audit, get_db
from ..doku import KINDS, delete_attachments, diff, get_or_404, history, insert_row, log, strip_strings, update_row
from ..security import admin_user
from ..timeutil import now_utc_str, parse_utc, today_local

router = APIRouter(prefix="/api/v1", tags=["Zugangsdaten"])

OWNER_TYPES = ("device", "license", "site", "contact")
SECRETS = {"password": "Passwort", "notes": "Notiz", "totp": "2FA-Geheimnis"}
OLD_DAYS = 365


class CredentialIn(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=150)
    username: Optional[str] = Field(None, max_length=200)
    url: Optional[str] = Field(None, max_length=500)
    owner_type: Optional[str] = Field(None, description="device, license, site, contact oder leer (allgemein)")
    owner_id: Optional[int] = None
    password: Optional[str] = Field(None, max_length=1000, description="leer = entfernen, weglassen = unverändert")
    notes: Optional[str] = Field(None, max_length=20000)
    totp: Optional[str] = Field(None, max_length=1000, description="Base32-Geheimnis oder otpauth://totp/…")


LABELS = {"title": "Titel", "username": "Benutzername", "url": "Adresse", "owner": "Gehört zu"}


def _owner_name(conn, owner_type, owner_id):
    if not owner_type or not owner_id:
        return None, None
    r = conn.execute(f"SELECT * FROM {KINDS[owner_type][0]} WHERE id = ?", (owner_id,)).fetchone()
    if not r:
        return None, None
    icon = KINDS[owner_type][2]
    if owner_type == "device":
        t = conn.execute("SELECT icon FROM device_types WHERE id = ?", (r["type_id"],)).fetchone()
        icon = t[0] if t else icon
    return r["name"], icon


def _out(conn, r) -> dict:
    name, icon = _owner_name(conn, r["owner_type"], r["owner_id"])
    changed = r["password_changed_at"]
    age = (today_local() - parse_utc(changed).date()).days if changed else None
    return {"id": r["id"], "title": r["title"], "username": r["username"], "url": r["url"],
            "owner_type": r["owner_type"] if name else None, "owner_id": r["owner_id"] if name else None,
            "owner_name": name, "owner_icon": icon or "🔐",
            "has_password": bool(r["password_enc"]), "has_notes": bool(r["notes_enc"]), "has_totp": bool(r["totp_enc"]),
            "password_changed_at": changed, "password_age_days": age, "old": age is not None and age >= OLD_DAYS}


def _check_owner(conn, values: dict) -> None:
    if "owner_type" in values or "owner_id" in values:
        ot, oid = values.get("owner_type") or None, values.get("owner_id") or None
        if ot and ot not in OWNER_TYPES:
            raise HTTPException(400, "Zuordnung muss device, license, site oder contact sein")
        if bool(ot) != bool(oid):
            raise HTTPException(400, "Zuordnung unvollständig")
        if ot:
            get_or_404(conn, ot, oid)
        values["owner_type"], values["owner_id"] = ot, oid


@router.get("/credentials")
def list_credentials(owner_type: Optional[str] = None, owner_id: Optional[int] = None,
                     filter: Optional[str] = Query(None, description="device, license, site, general, totp, old"),
                     q: Optional[str] = Query(None, max_length=100),
                     admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    sql, args = "SELECT * FROM credentials WHERE 1 = 1", []
    if owner_type and owner_id:
        sql += " AND owner_type = ? AND owner_id = ?"
        args += [owner_type, owner_id]
    if filter in ("device", "license", "site", "contact"):
        sql += " AND owner_type = ?"
        args.append(filter)
    elif filter == "general":
        sql += " AND owner_type IS NULL"
    elif filter == "totp":
        sql += " AND totp_enc IS NOT NULL"
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (title LIKE ? OR username LIKE ? OR url LIKE ?)"
        args += [like] * 3
    rows = [_out(conn, r) for r in conn.execute(sql + " ORDER BY title COLLATE NOCASE", args)]
    if filter == "old":
        rows = [r for r in rows if r["old"]]
    return rows


@router.get("/credentials/counts")
def counts(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = [_out(conn, r) for r in conn.execute("SELECT * FROM credentials")]
    out = {"all": len(rows), "general": sum(1 for r in rows if not r["owner_type"]),
           "totp": sum(1 for r in rows if r["has_totp"]), "old": sum(1 for r in rows if r["old"])}
    for t in OWNER_TYPES:
        out[t] = sum(1 for r in rows if r["owner_type"] == t)
    return out


@router.get("/credentials/{cred_id}")
def get_credential(cred_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    out = _out(conn, get_or_404(conn, "credential", cred_id))
    out["history"] = history(conn, "credential", cred_id)
    return out


def _seal_secrets(conn, key: bytes, cred_id: int, values: dict) -> str:
    """Geheime Felder verschlüsseln und speichern. Liefert eine Beschreibung für den Verlauf."""
    parts = []
    for field, label in SECRETS.items():
        if field not in values:
            continue
        value = values[field] or ""
        if field == "totp" and value:
            info = vc.parse_otp(value)
            value = f"otpauth://totp/x?secret={info['secret']}&digits={info['digits']}&period={info['period']}&algorithm={info['algorithm']}"
        token = vault.seal(key, value, f"cred:{cred_id}:{field}")
        conn.execute(f"UPDATE credentials SET {field}_enc = ? WHERE id = ?", (token, cred_id))
        if field == "password":
            conn.execute("UPDATE credentials SET password_changed_at = ? WHERE id = ?", (now_utc_str() if value else None, cred_id))
        parts.append(f"{label} {'gesetzt' if value else 'entfernt'}")
    return "; ".join(parts)


@router.post("/credentials", status_code=201)
def create_credential(data: CredentialIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    values = data.model_dump(exclude_unset=True)
    secrets_ = {k: values.pop(k) for k in list(values) if k in SECRETS}
    values = strip_strings(values)
    if not values.get("title"):
        raise HTTPException(400, "Bitte einen Titel angeben")
    key = vault.require_key(request, admin)  # neue Zugänge nur bei offenem Tresor
    if secrets_.get("totp"):
        try:
            vc.parse_otp(secrets_["totp"])
        except vc.CryptoError as e:
            raise HTTPException(400, str(e))
    _check_owner(conn, values)
    values["created_by"] = admin["id"]
    cid = insert_row(conn, "credentials", values)
    _seal_secrets(conn, key, cid, {k: v for k, v in secrets_.items() if v})
    log(conn, admin, "doc_created", "credential", cid, values["title"])
    return get_credential(cid, admin, conn)


@router.patch("/credentials/{cred_id}")
def update_credential(cred_id: int, data: CredentialIn, request: Request, admin=Depends(admin_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "credential", cred_id)
    values = data.model_dump(exclude_unset=True)
    secrets_ = {k: values.pop(k) for k in list(values) if k in SECRETS}
    values = strip_strings(values)
    if "title" in values and not values["title"]:
        raise HTTPException(400, "Der Titel darf nicht leer sein")
    key = vault.require_key(request, admin) if secrets_ else None
    if secrets_.get("totp"):
        try:
            vc.parse_otp(secrets_["totp"])
        except vc.CryptoError as e:
            raise HTTPException(400, str(e))
    _check_owner(conn, values)
    o, v = dict(old), dict(values)
    if "owner_type" in values or "owner_id" in values:
        o["owner"] = _owner_name(conn, old["owner_type"], old["owner_id"])[0] or "allgemein"
        v["owner"] = _owner_name(conn, values.get("owner_type"), values.get("owner_id"))[0] or "allgemein"
        v.pop("owner_type", None)
        v.pop("owner_id", None)
    text = diff(o, v, LABELS)
    update_row(conn, "credentials", cred_id, values)
    if key:
        stext = _seal_secrets(conn, key, cred_id, secrets_)
        text = "; ".join(x for x in (text, stext) if x)
        conn.execute("UPDATE credentials SET updated_at = ? WHERE id = ?", (now_utc_str(), cred_id))
    if text:
        log(conn, admin, "doc_updated", "credential", cred_id, values.get("title") or old["title"], text)
    return get_credential(cred_id, admin, conn)


@router.delete("/credentials/{cred_id}")
def delete_credential(cred_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "credential", cred_id)
    conn.execute("DELETE FROM credentials WHERE id = ?", (cred_id,))
    delete_attachments(conn, "credential", cred_id)
    log(conn, admin, "doc_deleted", "credential", cred_id, old["title"])
    return {"ok": True}


class RevealIn(BaseModel):
    field: str = Field(..., description="password, notes oder totp")
    purpose: str = Field("show", description="show (anzeigen) oder copy (kopieren)")


@router.post("/credentials/{cred_id}/reveal")
def reveal(cred_id: int, data: RevealIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Ein Geheimnis entschlüsseln (bei offenem Tresor). Jeder Abruf wird protokolliert; bei 2FA kommt der aktuelle Code."""
    if data.field not in SECRETS:
        raise HTTPException(400, "Feld muss password, notes oder totp sein")
    r = get_or_404(conn, "credential", cred_id)
    key = vault.require_key(request, admin)
    value = vault.unseal(key, r[f"{data.field}_enc"], f"cred:{cred_id}:{data.field}")
    if not value:
        raise HTTPException(404, f"{SECRETS[data.field]} ist nicht hinterlegt")
    what = {"password": "Passwort", "notes": "Notiz", "totp": "2FA-Code"}[data.field]
    action = "secret_copied" if data.purpose == "copy" else "secret_shown"
    audit(conn, admin["id"], action, f"credential:{cred_id}", f"{r['title']} – {what} {'kopiert' if data.purpose == 'copy' else 'angezeigt'}")
    if data.field == "totp":
        return vc.totp(vc.parse_otp(value))
    return {"value": value}


# --- Lizenzschlüssel ------------------------------------------------------------

class LicenseKeyIn(BaseModel):
    key: str = Field("", max_length=5000, description="leer = entfernen")


@router.put("/licenses/{license_id}/key")
def set_license_key(license_id: int, data: LicenseKeyIn, request: Request, admin=Depends(admin_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    lic = get_or_404(conn, "license", license_id)
    key = vault.require_key(request, admin)
    value = data.key.strip()
    conn.execute("UPDATE licenses SET key_enc = ?, key_sealed = NULL, key_fp = ?, updated_at = ? WHERE id = ?",
                 (vault.seal(key, value, f"license:{license_id}:key"), _fp(value) if value else None, now_utc_str(), license_id))
    log(conn, admin, "doc_updated", "license", license_id, lic["name"], "Lizenzschlüssel " + ("gesetzt" if value else "entfernt"))
    return {"has_key": bool(value)}


def _fp(value: str) -> str:
    from ..winlicense import fingerprint
    return fingerprint(value.strip().upper())


class PurposeIn(BaseModel):
    purpose: str = Field("show", description="show (anzeigen) oder copy (kopieren)")


@router.post("/licenses/{license_id}/key/reveal")
def reveal_license_key(license_id: int, data: PurposeIn, request: Request, admin=Depends(admin_user),
                       conn: sqlite3.Connection = Depends(get_db)):
    lic = get_or_404(conn, "license", license_id)
    key = vault.require_key(request, admin)
    value = vault.unseal(key, lic["key_enc"], f"license:{license_id}:key") if lic["key_enc"] else ""
    if not value and lic["key_sealed"]:
        # vom Agent versiegelt → mit dem privaten Tresor-Schlüssel öffnen und gleich in die normale Form überführen
        from .. import seal
        priv = seal.private_key(conn, key)
        if priv:
            value = seal.open_sealed(priv, lic["key_sealed"], f"license:{license_id}:key")
            conn.execute("UPDATE licenses SET key_enc = ?, key_sealed = NULL WHERE id = ?",
                         (vault.seal(key, value, f"license:{license_id}:key"), license_id))
    if not value:
        raise HTTPException(404, "Kein Lizenzschlüssel hinterlegt")
    action = "secret_copied" if data.purpose == "copy" else "secret_shown"
    audit(conn, admin["id"], action, f"license:{license_id}",
          f"{lic['name']} – Lizenzschlüssel {'kopiert' if data.purpose == 'copy' else 'angezeigt'}")
    return {"value": value}
