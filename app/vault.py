"""Tresor: Datenschlüssel, Schlüssel pro Benutzer, Notfall-Schlüssel, Einladungen und offene Tresore im Speicher.

Ein zufälliger Datenschlüssel verschlüsselt alle Geheimnisse. In der Datenbank liegt er nur verschlüsselt:
- einmal pro Benutzer mit Vollzugriff (Schlüssel aus dessen Tresor-Passwort, PBKDF2),
- einmal mit dem Notfall-Schlüssel (zum Ausdrucken),
- befristet mit einem Einladungscode, bis die eingeladene Person ihr eigenes Tresor-Passwort festlegt.

Geöffnet liegt der Datenschlüssel nur im Arbeitsspeicher, je Sitzung, und verfällt nach X Minuten ohne Aktivität,
beim Abmelden, Sperren und Neustart der App.
"""
import sqlite3
import threading
import time
from datetime import timedelta
from typing import Dict, Optional

from fastapi import HTTPException

from . import vault_crypto as vc
from .db import get_setting
from .timeutil import now_utc, now_utc_str, to_utc_str

LOCKED = 423  # HTTP „Locked“: Tresor gesperrt – die Oberfläche fragt dann nach dem Tresor-Passwort
INVITE_DAYS = 7
MIN_PASSWORD = 10

_open: Dict[str, Dict] = {}
_lock = threading.Lock()


# --- Offene Tresore im Speicher ------------------------------------------------

def timeout_s(conn: sqlite3.Connection) -> int:
    try:
        return max(1, min(240, int(get_setting(conn, "vault_timeout_min") or 15))) * 60
    except ValueError:
        return 900


def _alive(entry: Dict) -> bool:
    return time.monotonic() - entry["last"] < entry["timeout"]


def open_session(sid: str, user_id: int, key: bytes, timeout: int) -> None:
    with _lock:
        _open[sid] = {"key": key, "user_id": user_id, "last": time.monotonic(), "timeout": timeout}


def get_key(sid: Optional[str], user_id: int) -> Optional[bytes]:
    if not sid:
        return None
    with _lock:
        e = _open.get(sid)
        if not e:
            return None
        if e["user_id"] != user_id or not _alive(e):
            _open.pop(sid, None)
            return None
        return e["key"]


def touch(sid: Optional[str]) -> None:
    """Jede Anfrage dieser Sitzung zählt als Aktivität."""
    if not sid:
        return
    with _lock:
        e = _open.get(sid)
        if e:
            if _alive(e):
                e["last"] = time.monotonic()
            else:
                _open.pop(sid, None)


def remaining(sid: Optional[str]) -> int:
    with _lock:
        e = _open.get(sid or "")
        return max(0, int(e["timeout"] - (time.monotonic() - e["last"]))) if e and _alive(e) else 0


def close(sid: Optional[str]) -> None:
    with _lock:
        _open.pop(sid or "", None)


def close_user(user_id: int) -> None:
    with _lock:
        for sid in [s for s, e in _open.items() if e["user_id"] == user_id]:
            _open.pop(sid, None)


def close_all() -> None:
    with _lock:
        _open.clear()


def set_timeout_all(timeout: int) -> None:
    with _lock:
        for e in _open.values():
            e["timeout"] = timeout


def require_key(request, user) -> bytes:
    key = get_key(getattr(request.state, "vault_sid", None), user["id"])
    if not key:
        raise HTTPException(LOCKED, "Der Tresor ist gesperrt – bitte mit deinem Tresor-Passwort entsperren")
    return key


# --- Schlüssel in der Datenbank -------------------------------------------------

def initialized(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM vault_keys WHERE kind IN ('user', 'recovery') LIMIT 1").fetchone())


def _aad(kind: str, user_id: Optional[int]) -> str:
    return f"vault:{kind}:{user_id or 0}"


def _row(conn, kind: str, user_id: Optional[int] = None):
    if kind == "recovery":
        return conn.execute("SELECT * FROM vault_keys WHERE kind = 'recovery'").fetchone()
    return conn.execute("SELECT * FROM vault_keys WHERE kind = ? AND user_id = ?", (kind, user_id)).fetchone()


def store(conn, kind: str, user_id: Optional[int], secret: str, data_key: bytes, actor_id: Optional[int],
          expires_at: Optional[str] = None) -> None:
    """Datenschlüssel mit Passwort/Code verschlüsselt ablegen (ersetzt einen vorhandenen Eintrag gleicher Art)."""
    salt = vc.new_salt()
    iterations = vc.KDF_ITERATIONS if kind == "user" else max(1000, vc.KDF_ITERATIONS // 6)
    kek = vc.password_key(secret, salt, iterations) if kind == "user" else vc.code_key(secret, salt, iterations)
    wrapped = vc.encrypt(kek, data_key, _aad(kind, user_id).encode())
    if kind == "recovery":
        conn.execute("DELETE FROM vault_keys WHERE kind = 'recovery'")
    else:
        conn.execute("DELETE FROM vault_keys WHERE kind = ? AND user_id = ?", (kind, user_id))
    conn.execute("INSERT INTO vault_keys(kind, user_id, salt, iterations, wrapped, created_by, created_at, expires_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (kind, user_id, salt, iterations, wrapped, actor_id, now_utc_str(), expires_at))


def unwrap(conn, kind: str, user_id: Optional[int], secret: str, mark_used: bool = True) -> Optional[bytes]:
    r = _row(conn, kind, user_id)
    if not r:
        return None
    if r["expires_at"] and r["expires_at"] < now_utc_str():
        return None
    kek = vc.password_key(secret, r["salt"], r["iterations"]) if kind == "user" else vc.code_key(secret, r["salt"], r["iterations"])
    try:
        key = vc.decrypt(kek, r["wrapped"], _aad(kind, user_id).encode())
    except vc.CryptoError:
        return None
    if mark_used:
        conn.execute("UPDATE vault_keys SET last_used_at = ? WHERE id = ?", (now_utc_str(), r["id"]))
    return key


def check_password(pw: str) -> str:
    pw = pw or ""
    if len(pw) < MIN_PASSWORD:
        raise HTTPException(400, f"Das Tresor-Passwort muss mindestens {MIN_PASSWORD} Zeichen haben")
    if pw.lower() in ("passwort123", "password123", "1234567890", "qwertzuiop"):
        raise HTTPException(400, "Dieses Tresor-Passwort ist zu leicht zu erraten")
    return pw


def invite_expiry() -> str:
    return to_utc_str(now_utc() + timedelta(days=INVITE_DAYS))


def remove_user(conn, user_id: int) -> bool:
    """Zugang und Einladung eines Benutzers entfernen (z. B. bei Deaktivieren). True, wenn etwas entfernt wurde."""
    n = conn.execute("DELETE FROM vault_keys WHERE user_id = ? AND kind IN ('user', 'invite')", (user_id,)).rowcount
    close_user(user_id)
    return n > 0


def is_member(conn, user_id: int) -> bool:
    return bool(_row(conn, "user", user_id))


def member_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM vault_keys WHERE kind = 'user'").fetchone()[0]


# --- Felder verschlüsseln -------------------------------------------------------

def seal(key: bytes, value: Optional[str], aad: str) -> Optional[str]:
    return vc.encrypt_text(key, value, aad) if value else None


def unseal(key: bytes, token: Optional[str], aad: str) -> str:
    if not token:
        return ""
    try:
        return vc.decrypt_text(key, token, aad)
    except vc.CryptoError:
        raise HTTPException(500, "Eintrag lässt sich nicht entschlüsseln (Daten beschädigt oder aus anderem Tresor)")
