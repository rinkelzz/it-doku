"""Verschlüsselung für den Tresor – nur Standardbibliothek, ohne native Erweiterungen.

- AES-256 (FIPS-197) in reinem Python, im CTR-Modus.
- Echtheit: HMAC-SHA-256 über Version, Nonce, Geheimtext und Zusatzdaten (Encrypt-then-MAC).
  Die Zusatzdaten (z. B. „cred:12:password“) binden einen Geheimtext an sein Feld – vertauschen fällt auf.
- Aus einem 32-Byte-Schlüssel werden getrennte Schlüssel für Verschlüsselung und HMAC abgeleitet.
- Passwörter → Schlüssel mit PBKDF2-HMAC-SHA-256 (hashlib, in C).

Format (Base64): 0x01 | Nonce (16) | Geheimtext | HMAC (32)
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from typing import Dict, Optional
from urllib.parse import parse_qs, unquote, urlsplit

VERSION = b"\x01"
KDF_ITERATIONS = int(os.environ.get("ITD_KDF_ITERATIONS", "600000"))


class CryptoError(ValueError):
    pass


# --- AES-256 ---------------------------------------------------------------------

def _make_sbox():
    sbox = [0] * 256
    p = q = 1
    while True:  # Erzeuger 3 über GF(2^8), Inverses über q
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) & 0xFF ^ ((q << 2) | (q >> 6)) & 0xFF ^ ((q << 3) | (q >> 5)) & 0xFF ^ ((q << 4) | (q >> 4)) & 0xFF
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


SBOX = _make_sbox()


def _xt(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


# T-Tabellen: SubBytes + ShiftRows + MixColumns in einem Schritt
_T0 = []
for _s in SBOX:
    _s2, _s3 = _xt(_s), _xt(_s) ^ _s
    _T0.append((_s2 << 24) | (_s << 16) | (_s << 8) | _s3)
_T1 = [((t >> 8) | (t << 24)) & 0xFFFFFFFF for t in _T0]
_T2 = [((t >> 8) | (t << 24)) & 0xFFFFFFFF for t in _T1]
_T3 = [((t >> 8) | (t << 24)) & 0xFFFFFFFF for t in _T2]
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40]


def expand_key(key: bytes):
    if len(key) != 32:
        raise CryptoError("AES-256 braucht 32 Byte Schlüssel")
    w = list(struct.unpack(">8I", key))
    for i in range(8, 60):
        t = w[i - 1]
        if i % 8 == 0:
            t = ((t << 8) | (t >> 24)) & 0xFFFFFFFF
            t = (SBOX[t >> 24] << 24) | (SBOX[(t >> 16) & 0xFF] << 16) | (SBOX[(t >> 8) & 0xFF] << 8) | SBOX[t & 0xFF]
            t ^= _RCON[i // 8 - 1] << 24
        elif i % 8 == 4:
            t = (SBOX[t >> 24] << 24) | (SBOX[(t >> 16) & 0xFF] << 16) | (SBOX[(t >> 8) & 0xFF] << 8) | SBOX[t & 0xFF]
        w.append(w[i - 8] ^ t)
    return w


def encrypt_block(w, block: bytes) -> bytes:
    s0, s1, s2, s3 = struct.unpack(">4I", block)
    s0 ^= w[0]; s1 ^= w[1]; s2 ^= w[2]; s3 ^= w[3]  # noqa: E702
    T0, T1, T2, T3 = _T0, _T1, _T2, _T3
    for r in range(1, 14):
        k = 4 * r
        t0 = T0[s0 >> 24] ^ T1[(s1 >> 16) & 255] ^ T2[(s2 >> 8) & 255] ^ T3[s3 & 255] ^ w[k]
        t1 = T0[s1 >> 24] ^ T1[(s2 >> 16) & 255] ^ T2[(s3 >> 8) & 255] ^ T3[s0 & 255] ^ w[k + 1]
        t2 = T0[s2 >> 24] ^ T1[(s3 >> 16) & 255] ^ T2[(s0 >> 8) & 255] ^ T3[s1 & 255] ^ w[k + 2]
        t3 = T0[s3 >> 24] ^ T1[(s0 >> 16) & 255] ^ T2[(s1 >> 8) & 255] ^ T3[s2 & 255] ^ w[k + 3]
        s0, s1, s2, s3 = t0, t1, t2, t3
    S = SBOX
    out = []
    for a, b, c, d, k in ((s0, s1, s2, s3, w[56]), (s1, s2, s3, s0, w[57]), (s2, s3, s0, s1, w[58]), (s3, s0, s1, s2, w[59])):
        out.append(((S[a >> 24] << 24) | (S[(b >> 16) & 255] << 16) | (S[(c >> 8) & 255] << 8) | S[d & 255]) ^ k)
    return struct.pack(">4I", *out)


def aes_ctr(key: bytes, nonce: bytes, data: bytes) -> bytes:
    w = expand_key(key)
    ctr = int.from_bytes(nonce, "big")
    out = bytearray()
    for i in range(0, len(data), 16):
        ks = encrypt_block(w, ((ctr + i // 16) & ((1 << 128) - 1)).to_bytes(16, "big"))
        chunk = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)


# --- Verschlüsseln mit Echtheitsprüfung -----------------------------------------

def _subkeys(key: bytes):
    return (hmac.new(key, b"itdoku-enc", hashlib.sha256).digest(), hmac.new(key, b"itdoku-mac", hashlib.sha256).digest())


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> str:
    ek, mk = _subkeys(key)
    nonce = secrets.token_bytes(16)
    ct = aes_ctr(ek, nonce, plaintext)
    tag = hmac.new(mk, VERSION + nonce + ct + b"|" + aad, hashlib.sha256).digest()
    return base64.b64encode(VERSION + nonce + ct + tag).decode()


def decrypt(key: bytes, token: str, aad: bytes = b"") -> bytes:
    try:
        raw = base64.b64decode(token.encode(), validate=True)
    except (ValueError, TypeError):
        raise CryptoError("Ungültige Daten")
    if len(raw) < 1 + 16 + 32 or raw[:1] != VERSION:
        raise CryptoError("Ungültige Daten")
    ek, mk = _subkeys(key)
    nonce, ct, tag = raw[1:17], raw[17:-32], raw[-32:]
    if not hmac.compare_digest(tag, hmac.new(mk, VERSION + nonce + ct + b"|" + aad, hashlib.sha256).digest()):
        raise CryptoError("Schlüssel falsch oder Daten verändert")
    return aes_ctr(ek, nonce, ct)


def encrypt_text(key: bytes, text: str, aad: str) -> str:
    return encrypt(key, text.encode("utf-8"), aad.encode())


def decrypt_text(key: bytes, token: str, aad: str) -> str:
    return decrypt(key, token, aad.encode()).decode("utf-8")


# --- Schlüssel aus Passwörtern und Codes -----------------------------------------

def new_key() -> bytes:
    return secrets.token_bytes(32)


def new_salt() -> str:
    return secrets.token_hex(16)


def password_key(password: str, salt: str, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations, 32)


_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def _group(s: str, n: int = 4) -> str:
    return "-".join(s[i:i + n] for i in range(0, len(s), n))


def new_recovery_key() -> str:
    """256 Bit als Base32 in Vierergruppen: K7QF-2MXA-…"""
    return _group(base64.b32encode(secrets.token_bytes(32)).decode().rstrip("="))


def new_invite_code() -> str:
    """80 Bit, gut am Telefon durchzugeben: ABCD-EFGH-JKMN-PQRS"""
    return _group(base64.b32encode(secrets.token_bytes(10)).decode())


def normalize_code(code: str) -> str:
    """Bindestriche/Leerzeichen weg, Großbuchstaben, verwechselbare Ziffern (0→O, 1→I, 8→B)."""
    s = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    return s.translate(str.maketrans({"0": "O", "1": "I", "8": "B"}))


def code_key(code: str, salt: str, iterations: int) -> bytes:
    """Schlüssel aus Notfall-Schlüssel oder Einladungscode (normalisiert)."""
    return password_key(normalize_code(code), salt, iterations)


# --- TOTP (RFC 6238) ----------------------------------------------------------------

ALGOS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}


def parse_otp(value: str) -> Dict:
    """Base32-Geheimnis oder otpauth://totp/…-Link → {secret, digits, period, algorithm, label}."""
    value = (value or "").strip()
    info = {"digits": 6, "period": 30, "algorithm": "SHA1", "label": ""}
    if value.lower().startswith("otpauth://"):
        u = urlsplit(value)
        if u.netloc.lower() != "totp":
            raise CryptoError("Nur zeitbasierte Codes (TOTP) werden unterstützt")
        q = {k.lower(): v[0] for k, v in parse_qs(u.query).items()}
        info["label"] = unquote(u.path.lstrip("/"))[:100]
        secret = q.get("secret", "")
        try:
            info["digits"] = int(q.get("digits", 6))
            info["period"] = int(q.get("period", 30))
        except ValueError:
            raise CryptoError("Ungültiger otpauth-Link")
        info["algorithm"] = q.get("algorithm", "SHA1").upper()
    else:
        secret = value
    secret = "".join(secret.split()).replace("-", "").upper().rstrip("=")
    if not secret or any(c not in _B32 for c in secret):
        raise CryptoError("Das 2FA-Geheimnis muss ein Base32-Code (A–Z, 2–7) oder ein otpauth-Link sein")
    try:
        base64.b32decode(secret + "=" * (-len(secret) % 8))
    except ValueError:
        raise CryptoError("Das 2FA-Geheimnis ist kein gültiger Base32-Code")
    if info["digits"] not in (6, 7, 8) or not 10 <= info["period"] <= 120 or info["algorithm"] not in ALGOS:
        raise CryptoError("Nicht unterstützte 2FA-Einstellungen")
    info["secret"] = secret
    return info


def totp(info: Dict, at: Optional[float] = None) -> Dict:
    at = time.time() if at is None else at
    key = base64.b32decode(info["secret"] + "=" * (-len(info["secret"]) % 8))
    counter = int(at // info["period"])
    mac = hmac.new(key, struct.pack(">Q", counter), ALGOS[info["algorithm"]]).digest()
    off = mac[-1] & 0x0F
    num = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** info["digits"])
    return {"code": str(num).zfill(info["digits"]), "remaining": int(info["period"] - at % info["period"]), "period": info["period"]}
