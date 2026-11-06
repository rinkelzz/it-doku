"""Tresor: einrichten, entsperren, sperren, Passwort ändern, Notfall-Schlüssel, Einladungen, Zugang entziehen."""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import vault
from .. import vault_crypto as vc
from ..db import audit, get_db, get_setting, set_setting
from ..dsm_auth import clear_failures, note_failure, too_many_attempts
from ..security import admin_user, current_user
from ..timeutil import local_iso, now_utc_str

router = APIRouter(prefix="/api/v1/vault", tags=["Tresor"])


def _sid(request: Request) -> Optional[str]:
    return getattr(request.state, "vault_sid", None)


def _open(request, conn, user, key) -> None:
    vault.open_session(_sid(request), user["id"], key, vault.timeout_s(conn))


def _limit(name: str) -> None:
    if too_many_attempts(name):
        raise HTTPException(429, "Zu viele Fehlversuche – bitte in 15 Minuten erneut versuchen")


def _failed(conn, user, name: str, what: str) -> None:
    note_failure(name)
    audit(conn, user["id"], "vault_failed", f"user:{user['id']}", what)


@router.get("/status")
def status(request: Request, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    inv = conn.execute("SELECT expires_at FROM vault_keys WHERE kind = 'invite' AND user_id = ? AND expires_at > ?",
                       (user["id"], now_utc_str())).fetchone()
    unlocked = bool(vault.get_key(_sid(request), user["id"]))
    return {"initialized": vault.initialized(conn), "can_use": bool(user["is_admin"]),
            "member": vault.is_member(conn, user["id"]), "invited": bool(inv) and bool(user["is_admin"]),
            "invite_expires": local_iso(inv[0]) if inv else None,
            "unlocked": unlocked, "remaining": vault.remaining(_sid(request)) if unlocked else 0,
            "timeout_min": vault.timeout_s(conn) // 60}


class PasswordIn(BaseModel):
    password: str = Field(..., max_length=256)


@router.post("/setup")
def setup(data: PasswordIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Tresor einrichten. Gibt den Notfall-Schlüssel EINMALIG zurück."""
    if vault.initialized(conn):
        raise HTTPException(409, "Der Tresor ist schon eingerichtet")
    vault.check_password(data.password)
    key = vc.new_key()
    recovery = vc.new_recovery_key()
    vault.store(conn, "user", admin["id"], data.password, key, admin["id"])
    vault.store(conn, "recovery", None, recovery, key, admin["id"])
    _open(request, conn, admin, key)
    audit(conn, admin["id"], "vault_setup", f"user:{admin['id']}", "Tresor eingerichtet, Notfall-Schlüssel erzeugt")
    return {"recovery_key": recovery}


@router.post("/unlock")
def unlock(data: PasswordIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    name = f"vault|{admin['id']}"
    _limit(name)
    if not vault.is_member(conn, admin["id"]):
        raise HTTPException(403, "Du hast noch keinen Zugang zum Tresor – bitte von jemandem mit Zugang freischalten lassen")
    key = vault.unwrap(conn, "user", admin["id"], data.password)
    if not key:
        _failed(conn, admin, name, "Tresor-Passwort falsch")
        raise HTTPException(401, "Tresor-Passwort falsch")
    clear_failures(name)
    _open(request, conn, admin, key)
    return {"ok": True, "remaining": vault.remaining(_sid(request))}


@router.post("/lock")
def lock(request: Request, user=Depends(current_user)):
    vault.close(_sid(request))
    return {"ok": True}


class ChangeIn(BaseModel):
    old_password: str = Field(..., max_length=256)
    new_password: str = Field(..., max_length=256)


@router.post("/password")
def change_password(data: ChangeIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    name = f"vault|{admin['id']}"
    _limit(name)
    key = vault.unwrap(conn, "user", admin["id"], data.old_password)
    if not key:
        _failed(conn, admin, name, "Tresor-Passwort ändern: altes Passwort falsch")
        raise HTTPException(400, "Das bisherige Tresor-Passwort stimmt nicht")
    vault.store(conn, "user", admin["id"], vault.check_password(data.new_password), key, admin["id"])
    _open(request, conn, admin, key)
    audit(conn, admin["id"], "vault_password", f"user:{admin['id']}", "eigenes Tresor-Passwort geändert")
    return {"ok": True}


class RecoverIn(BaseModel):
    recovery_key: str = Field(..., max_length=200)
    new_password: str = Field(..., max_length=256)


@router.post("/recover")
def recover(data: RecoverIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Mit dem Notfall-Schlüssel ein neues eigenes Tresor-Passwort setzen (auch ohne bisherigen Zugang)."""
    name = f"vault-recover|{admin['id']}"
    _limit(name)
    vault.check_password(data.new_password)
    key = vault.unwrap(conn, "recovery", None, data.recovery_key)
    if not key:
        _failed(conn, admin, name, "Notfall-Schlüssel falsch")
        raise HTTPException(400, "Der Notfall-Schlüssel stimmt nicht")
    clear_failures(name)
    vault.store(conn, "user", admin["id"], data.new_password, key, admin["id"])
    conn.execute("DELETE FROM vault_keys WHERE kind = 'invite' AND user_id = ?", (admin["id"],))
    _open(request, conn, admin, key)
    audit(conn, admin["id"], "vault_recovery_used", f"user:{admin['id']}", "Notfall-Schlüssel benutzt, neues Tresor-Passwort gesetzt")
    return {"ok": True}


class KeyIn(BaseModel):
    recovery_key: str = Field(..., max_length=200)


def recovery_pdf(conn, recovery: str) -> bytes:
    from ..logo import fit_box, pdf_image
    from ..pdf import PDF, fit
    from ..timeutil import today_local
    company = get_setting(conn, "company_name") or ""
    p = PDF(title="Notfall-Schlüssel IT-Dokumentation")
    x, w = 56, 595.28 - 112
    y = 70
    img = pdf_image(conn)
    if img:
        iw, ih = fit_box(img["width"], img["height"], 140, 46)
        p.image(595.28 - 56 - iw, y - 30, iw, ih, img)
    p.text(x, y, "Notfall-Schlüssel", 22, bold=True)
    p.text(x, y + 22, fit(f"IT-Dokumentation{' · ' + company if company else ''}", w - 150, 11), 11, color=(0.35, 0.35, 0.35))
    y += 64
    p.rect(x, y, w, 70, fill=(0.99, 0.95, 0.85))
    groups = recovery.split("-")
    p.text(595.28 / 2, y + 30, "-".join(groups[:7]) + "-", 15, bold=True, align="center")
    p.text(595.28 / 2, y + 52, "-".join(groups[7:]), 15, bold=True, align="center")
    y += 100
    lines = [
        ("Wofür ist das?", True),
        ("Mit diesem Schlüssel lässt sich ein neues Tresor-Passwort setzen, wenn alle Tresor-Passwörter vergessen", False),
        ("sind. Ohne Tresor-Passwort und ohne diesen Schlüssel sind die gespeicherten Zugangsdaten verloren.", False),
        ("", False),
        ("So wird er benutzt", True),
        ("1. In der IT-Dokumentation mit einem Benutzer mit Vollzugriff anmelden.", False),
        ("2. „Tresor entsperren“ → „Passwort vergessen?“ wählen.", False),
        ("3. Diesen Schlüssel eingeben (Bindestriche egal) und ein neues Tresor-Passwort festlegen.", False),
        ("", False),
        ("Aufbewahren", True),
        ("Ausgedruckt an einem sicheren Ort (z. B. Tresor oder Bankschließfach), nicht am Rechner und nicht als Foto.", False),
        ("Wird ein neuer Notfall-Schlüssel erzeugt, ist dieser hier ungültig – dann bitte vernichten.", False),
    ]
    for text, bold in lines:
        if text:
            p.text(x, y, text, 11 if bold else 10, bold=bold)
        y += 18 if bold else 15
    y += 30
    p.line(x, y, x + w, y)
    p.text(x, y + 16, f"Erstellt am {today_local().strftime('%d.%m.%Y')}", 9, color=(0.4, 0.4, 0.4))
    p.text(x + 220, y + 16, "Verwahrt von: ______________________________", 9, color=(0.4, 0.4, 0.4))
    return p.output()


@router.post("/recovery-sheet")
def recovery_sheet(data: KeyIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """PDF-Blatt zum Ausdrucken. Der Schlüssel wird nur geprüft, nicht gespeichert."""
    name = f"vault-recover|{admin['id']}"
    _limit(name)
    if not vault.unwrap(conn, "recovery", None, data.recovery_key, mark_used=False):
        _failed(conn, admin, name, "Notfall-Schlüssel falsch (PDF)")
        raise HTTPException(400, "Der Notfall-Schlüssel stimmt nicht")
    clear_failures(name)
    key = vc.normalize_code(data.recovery_key)
    pretty = "-".join(key[i:i + 4] for i in range(0, len(key), 4))
    return Response(recovery_pdf(conn, pretty), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="notfall-schluessel.pdf"', "Cache-Control": "no-store"})


@router.post("/recovery/renew")
def renew_recovery(request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    key = vault.require_key(request, admin)
    recovery = vc.new_recovery_key()
    vault.store(conn, "recovery", None, recovery, key, admin["id"])
    audit(conn, admin["id"], "vault_recovery_renewed", f"user:{admin['id']}", "neuer Notfall-Schlüssel, alter ungültig")
    return {"recovery_key": recovery}


@router.get("/members")
def members(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT k.kind, k.user_id, k.created_at, k.last_used_at, k.expires_at, u.display_name, u.username, c.display_name AS by_name "
        "FROM vault_keys k LEFT JOIN users u ON u.id = k.user_id LEFT JOIN users c ON c.id = k.created_by ORDER BY k.kind, u.display_name")
    out = {"members": [], "invites": [], "recovery": None}
    for r in rows:
        item = {"user_id": r["user_id"], "name": r["display_name"], "username": r["username"], "since": local_iso(r["created_at"]),
                "last_used": local_iso(r["last_used_at"]), "expires": local_iso(r["expires_at"]), "by": r["by_name"],
                "expired": bool(r["expires_at"] and r["expires_at"] < now_utc_str())}
        if r["kind"] == "user":
            out["members"].append(item)
        elif r["kind"] == "invite":
            out["invites"].append(item)
        else:
            out["recovery"] = item
    taken = {m["user_id"] for m in out["members"]} | {i["user_id"] for i in out["invites"] if not i["expired"]}
    out["candidates"] = [{"id": r["id"], "name": r["display_name"]} for r in conn.execute(
        "SELECT id, display_name FROM users WHERE active = 1 AND is_admin = 1 ORDER BY display_name") if r["id"] not in taken]
    out["counts"] = {
        "credentials": conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0],
        "totp": conn.execute("SELECT COUNT(*) FROM credentials WHERE totp_enc IS NOT NULL").fetchone()[0],
        "license_keys": conn.execute("SELECT COUNT(*) FROM licenses WHERE key_enc IS NOT NULL").fetchone()[0],
    }
    return out


class InviteIn(BaseModel):
    user_id: int


@router.post("/invite")
def invite(data: InviteIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Einladungscode für einen Benutzer mit Vollzugriff (7 Tage gültig). Er legt damit sein eigenes Tresor-Passwort fest."""
    key = vault.require_key(request, admin)
    target = conn.execute("SELECT * FROM users WHERE id = ?", (data.user_id,)).fetchone()
    if not target or not target["active"]:
        raise HTTPException(404, "Benutzer nicht gefunden oder deaktiviert")
    if not target["is_admin"]:
        raise HTTPException(400, "Den Tresor gibt es nur für Benutzer mit Vollzugriff – bitte erst unter Benutzer umstellen")
    if vault.is_member(conn, target["id"]):
        raise HTTPException(409, f"{target['display_name']} hat schon Zugang zum Tresor")
    code = vc.new_invite_code()
    expires = vault.invite_expiry()
    vault.store(conn, "invite", target["id"], code, key, admin["id"], expires_at=expires)
    audit(conn, admin["id"], "vault_invited", f"user:{target['id']}", "Einladung zum Tresor (7 Tage gültig)")
    return {"code": code, "expires": local_iso(expires), "name": target["display_name"]}


@router.delete("/invite/{user_id}")
def revoke_invite(user_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    n = conn.execute("DELETE FROM vault_keys WHERE kind = 'invite' AND user_id = ?", (user_id,)).rowcount
    if n:
        audit(conn, admin["id"], "vault_invite_revoked", f"user:{user_id}", "Einladung zurückgezogen")
    return {"ok": True}


class JoinIn(BaseModel):
    code: str = Field(..., max_length=60)
    password: str = Field(..., max_length=256)


@router.post("/join")
def join(data: JoinIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    name = f"vault-join|{admin['id']}"
    _limit(name)
    vault.check_password(data.password)
    key = vault.unwrap(conn, "invite", admin["id"], data.code)
    if not key:
        _failed(conn, admin, name, "Einladungscode falsch oder abgelaufen")
        raise HTTPException(400, "Der Einladungscode stimmt nicht oder ist abgelaufen")
    clear_failures(name)
    vault.store(conn, "user", admin["id"], data.password, key, admin["id"])
    conn.execute("DELETE FROM vault_keys WHERE kind = 'invite' AND user_id = ?", (admin["id"],))
    _open(request, conn, admin, key)
    audit(conn, admin["id"], "vault_joined", f"user:{admin['id']}", "Einladung angenommen, eigenes Tresor-Passwort festgelegt")
    return {"ok": True}


@router.delete("/members/{user_id}")
def remove_member(user_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    if vault.is_member(conn, user_id) and vault.member_count(conn) <= 1:
        raise HTTPException(400, "Das ist der letzte Zugang zum Tresor – erst jemand anderen freischalten")
    if vault.remove_user(conn, user_id):
        audit(conn, admin["id"], "vault_access_removed", f"user:{user_id}", "Zugang zum Tresor entzogen")
    return {"ok": True}


class SettingsIn(BaseModel):
    timeout_min: int = Field(..., ge=5, le=60)


@router.patch("/settings")
def vault_settings(data: SettingsIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    set_setting(conn, "vault_timeout_min", str(data.timeout_min))
    vault.set_timeout_all(data.timeout_min * 60)
    audit(conn, admin["id"], "vault_settings", "settings", f"Automatisch sperren nach {data.timeout_min} Minuten")
    return {"timeout_min": data.timeout_min}
