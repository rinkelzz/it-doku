"""Verschlüsseln „an den Tresor“, ohne dass der Tresor offen ist (für Daten, die Agenten liefern).

Der Tresor hat ein X25519-Schlüsselpaar: Der öffentliche Schlüssel liegt offen in den Einstellungen, der private nur
mit dem Tresor-Schlüssel verschlüsselt. Ein Agent-Bericht mit Windows-Produktschlüssel wird beim Eingang sofort an den
öffentlichen Schlüssel versiegelt (einmaliges Schlüsselpaar → X25519 → HKDF-SHA256 → AES-256-CTR + HMAC wie im
Tresor). Lesen kann ihn erst, wer den Tresor entsperrt hat. X25519 nach RFC 7748, reines Python.
"""
import base64
import hashlib
import hmac
import secrets
import sqlite3
from typing import Optional, Tuple

from . import vault_crypto

P = 2 ** 255 - 19
A24 = 121665


def _clamp(k: bytes) -> int:
    b = bytearray(k)
    b[0] &= 248
    b[31] &= 127
    b[31] |= 64
    return int.from_bytes(bytes(b), "little")


def x25519(k: bytes, u: bytes) -> bytes:
    """Skalarmultiplikation auf Curve25519 (Montgomery-Leiter, RFC 7748 Abschnitt 5)."""
    scalar = _clamp(k)
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in range(254, -1, -1):
        bit = (scalar >> t) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a, b = (x2 + z2) % P, (x2 - z2) % P
        aa, bb = a * a % P, b * b % P
        e = (aa - bb) % P
        c, d = (x3 + z3) % P, (x3 - z3) % P
        da, cb = d * a % P, c * b % P
        x3 = (da + cb) ** 2 % P
        z3 = x1 * (da - cb) ** 2 % P
        x2 = aa * bb % P
        z2 = e * (aa + A24 * e) % P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, P - 2, P) % P).to_bytes(32, "little")


BASE = (9).to_bytes(32, "little")


def keypair() -> Tuple[bytes, bytes]:
    priv = secrets.token_bytes(32)
    return priv, x25519(priv, BASE)


def _hkdf(secret: bytes, info: bytes) -> bytes:
    prk = hmac.new(b"itdoku-seal-v1", secret, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def seal(pub: bytes, plaintext: str, aad: str) -> str:
    eph, eph_pub = keypair()
    shared = x25519(eph, pub)
    if shared == bytes(32):
        raise ValueError("ungültiger öffentlicher Schlüssel")
    key = _hkdf(shared, eph_pub + pub)
    return "x1:" + base64.b64encode(eph_pub).decode() + ":" + vault_crypto.encrypt_text(key, plaintext, aad)


def open_sealed(priv: bytes, token: str, aad: str) -> str:
    try:
        tag, eph_b64, ct = token.split(":", 2)
    except ValueError:
        raise ValueError("ungültiges Format")
    if tag != "x1":
        raise ValueError("unbekanntes Format")
    eph_pub = base64.b64decode(eph_b64)
    pub = x25519(priv, BASE)
    key = _hkdf(x25519(priv, eph_pub), eph_pub + pub)
    return vault_crypto.decrypt_text(key, ct, aad)


# --- Schlüsselpaar des Tresors ----------------------------------------------

def public_key(conn: sqlite3.Connection) -> Optional[bytes]:
    from .db import get_setting
    v = get_setting(conn, "vault_seal_pub")
    return bytes.fromhex(v) if v else None


def ensure_keys(conn: sqlite3.Connection, data_key: bytes) -> None:
    """Beim Entsperren: Schlüsselpaar anlegen, falls noch keines da ist."""
    from . import vault
    from .db import get_setting, set_setting
    if get_setting(conn, "vault_seal_pub"):
        return
    priv, pub = keypair()
    set_setting(conn, "vault_seal_priv", vault.seal(data_key, priv.hex(), "vault:seal-priv"))
    set_setting(conn, "vault_seal_pub", pub.hex())


def private_key(conn: sqlite3.Connection, data_key: bytes) -> Optional[bytes]:
    from . import vault
    from .db import get_setting
    v = get_setting(conn, "vault_seal_priv")
    return bytes.fromhex(vault.unseal(data_key, v, "vault:seal-priv")) if v else None
