"""Windows-Lizenz aus dem Agent-Bericht: Produktschlüssel entschlüsseln, als Lizenz am Gerät führen, Schlüssel nur
versiegelt (an den Tresor) speichern.

Woher der Schlüssel kommt:
- **OEM-Schlüssel aus der Firmware** (OA3xOriginalProductKey) – bei Fertig-PCs/Notebooks; mit ihm aktiviert sich eine
  Neuinstallation derselben Edition auf demselben Gerät von selbst.
- **Installierter Schlüssel** aus DigitalProductId (Registry) – bei gekauften Einzellizenzen (Retail) der echte
  Schlüssel. Bei digitalen Lizenzen (z. B. kostenloses Upgrade von Windows 10) steht dort nur ein allgemeiner
  Schlüssel; den erkennen wir und speichern ihn nicht – dort hängt die Lizenz an der Hardware bzw. am Microsoft-Konto.
"""
import base64
import hashlib
import re
import sqlite3
from typing import Any, Dict, Optional

CHARS = "BCDFGHJKMPQRTVWXY2346789"
KEY_RE = re.compile(r"^[BCDFGHJKMNPQRTVWXY2346789]{5}(-[BCDFGHJKMNPQRTVWXY2346789]{5}){4}$")

# Allgemeine Schlüssel (Installation/Upgrade/KMS-Client) – keine echte Lizenz
GENERIC = {
    "YTMG3-N6DKC-DKB77-7M9GH-8HVX7", "VK7JG-NPHTM-C97JM-9MPGT-3V66T", "BT79Q-G7N6G-PGBYW-4YWX6-6F4BT",
    "2B87N-8KFHP-DKV6R-Y2C8J-PKCKT", "YNMGQ-8RYV3-4PGQ3-C8XTP-7CFBY", "XGVPP-NMH47-7TTHJ-W3FW7-8HV2C",
    "DXG7C-N36C4-C4HTG-X4T3X-2YV77", "8PTT6-RNW4C-6V7J2-C2D3X-MHBPB", "84NGF-MHBT6-FXBX8-QWJK7-DRR8H",
    "W269N-WFGWX-YVC9B-4J6C9-T83GX", "MH37W-N47XK-V7XM9-C7227-GCQG9", "NW6C2-QMPVW-D7KKK-3GKT6-VCFB2",
    "2WH4N-8QGBV-H22JP-CT43Q-MDWWJ", "NPPR9-FWDCX-D2C8J-H872K-2YT43", "DPH2V-TTNVB-4X9Q3-TJR4H-KHJW4",
    "TX9XD-98N7V-6WMQ6-BX7FG-H8Q99", "3KHY7-WNT83-DGQKR-F7HPR-844BM", "7HNRX-D7KGG-3K4RQ-4WPJ4-YTDFH",
    "PVMJN-6DFY6-9CCP6-7BKTT-D3WVR", "NRG8B-VKK3Q-CXVCJ-9G2XF-6Q84J", "9FNHH-K3HBT-3W4TD-6383H-6XYWF",
}


def decode_digital_product_id(data: bytes) -> str:
    """Produktschlüssel aus HKLM\\…\\CurrentVersion\\DigitalProductId (Windows 8 und neuer)."""
    if len(data) < 67:
        return ""
    key = bytearray(data[52:67])
    is_win8 = (key[14] // 6) & 1
    key[14] = (key[14] & 0xF7) | ((is_win8 & 2) * 4)
    out, last = "", 0
    for _ in range(25):
        cur = 0
        for j in range(14, -1, -1):
            cur = cur * 256 + key[j]
            key[j] = cur // 24
            cur %= 24
        out = CHARS[cur] + out
        last = cur
    if is_win8:
        rest = out[1:]
        out = rest[:last] + "N" + rest[last:]
    return "-".join(out[i:i + 5] for i in range(0, 25, 5))


def clean_key(v: Any) -> str:
    k = re.sub(r"\s", "", str(v or "")).upper()
    return k if KEY_RE.match(k) else ""


def _channel(desc: str) -> str:
    d = (desc or "").upper()
    for marker, label in (("OEM", "OEM"), ("RETAIL", "Einzelhandel (Retail)"), ("VOLUME_MAK", "Volumen (MAK)"),
                          ("VOLUME_KMSCLIENT", "Volumen (KMS)"), ("VOLUME", "Volumen")):
        if marker in d:
            return label
    return ""


STATUS = {0: "nicht lizenziert", 1: "aktiviert", 2: "Kulanzzeit (OOB)", 3: "Kulanzzeit (OOT)", 4: "nicht echt",
          5: "Benachrichtigung", 6: "erweiterte Kulanzzeit"}


def sanitize(raw: Any) -> Optional[Dict[str, Any]]:
    """Was vom Agent kommt → geprüfte Felder; der Schlüssel bleibt hier noch im Klartext und wird sofort versiegelt."""
    if not isinstance(raw, dict):
        return None
    out = {"edition": str(raw.get("edition") or "")[:100], "channel": _channel(str(raw.get("description") or "")),
           "status": STATUS.get(raw.get("status") if isinstance(raw.get("status"), int) else -1, ""),
           "partial": re.sub(r"[^A-Z0-9]", "", str(raw.get("partial") or "").upper())[:5]}
    installed = ""
    if raw.get("dpid"):
        try:
            installed = decode_digital_product_id(base64.b64decode(str(raw["dpid"]))[:4096])
        except (ValueError, TypeError):
            installed = ""
    oem = clean_key(raw.get("oem_key"))
    installed = clean_key(installed)
    if installed in GENERIC or (out["partial"] and installed and not installed.endswith(out["partial"])):
        installed = ""  # allgemeiner oder nicht zum aktiven Schlüssel passender Wert
    if oem in GENERIC:
        oem = ""
    out["key"] = installed or oem
    out["key_source"] = "der Installation" if installed else ("der Firmware (OEM)" if oem else "")
    out["checked"] = bool(raw.get("dpid") or raw.get("oem_key"))  # Schlüssel wurde überhaupt mitgeschickt
    out["digital"] = out["checked"] and not out["key"]
    return out if (out["edition"] or out["partial"] or out["key"]) else None


def fingerprint(key: str) -> str:
    return hashlib.sha256(("itdoku-winkey:" + key).encode()).hexdigest()[:24]


def store(conn: sqlite3.Connection, agent_id: int, device: sqlite3.Row, info: Dict[str, Any]) -> bool:
    """Lizenz „Windows … – <Gerät>“ anlegen/aktualisieren, mit dem Gerät verknüpfen, Schlüssel versiegeln."""
    from . import seal
    from .doku import insert_row, log
    from .timeutil import now_utc_str
    ref = f"agent:{agent_id}:windows"
    lic = conn.execute("SELECT * FROM licenses WHERE agent_ref = ?", (ref,)).fetchone()
    edition = re.sub(r"^Windows\(R\),?\s*", "Windows ", info["edition"]).replace(" edition", "").strip()
    name = f"{edition or 'Windows'} ({device['name']})"[:120]
    notes = "Vom Agent gemeldet. " + " · ".join(x for x in (
        f"Kanal: {info['channel']}" if info["channel"] else "", f"Status: {info['status']}" if info["status"] else "",
        f"Teilschlüssel …{info['partial']}" if info["partial"] else "",
        f"Schlüssel aus {info['key_source']}" if info["key_source"] else
        ("Digitale Lizenz – kein eigener Schlüssel; die Aktivierung hängt an der Hardware bzw. am Microsoft-Konto"
         if info.get("digital") else ""))
        if x)
    term = "OEM" if info["channel"] == "OEM" else ("Kauf" if info["channel"].startswith("Einzel") else info["channel"][:40])
    if not lic:
        lid = insert_row(conn, "licenses", {"kind": "software", "name": name, "vendor": "Microsoft", "term": term,
                                            "seats": 1, "notes": notes, "agent_ref": ref})
        log(conn, None, "doc_created", "license", lid, name, "vom Agent angelegt")
        lic = conn.execute("SELECT * FROM licenses WHERE id = ?", (lid,)).fetchone()
    else:
        if lic["notes"].startswith("Vom Agent gemeldet.") and lic["notes"] != notes:
            conn.execute("UPDATE licenses SET notes = ?, updated_at = ? WHERE id = ?", (notes, now_utc_str(), lic["id"]))
    conn.execute("INSERT OR IGNORE INTO license_devices(license_id, device_id) VALUES (?, ?)", (lic["id"], device["id"]))
    key = info.get("key") or ""
    if key:
        fp = fingerprint(key)
        pub = seal.public_key(conn)
        if pub and fp != (lic["key_fp"] or ""):
            conn.execute("UPDATE licenses SET key_sealed = ?, key_enc = NULL, key_fp = ?, updated_at = ? WHERE id = ?",
                         (seal.seal(pub, key, f"license:{lic['id']}:key"), fp, now_utc_str(), lic["id"]))
            log(conn, None, "doc_updated", "license", lic["id"], lic["name"],
                f"Produktschlüssel vom Agent übernommen ({info['key_source']}, verschlüsselt)")
    row = conn.execute("SELECT key_enc, key_sealed FROM licenses WHERE id = ?", (lic["id"],)).fetchone()
    return bool(row["key_enc"] or row["key_sealed"])
