"""Doppelte Geräte zusammenführen (z. B. vom Netzwerk-Scan angelegt und vom Agent noch einmal)."""
import sqlite3
from typing import Dict, List

from fastapi import HTTPException

from .doku import log
from .timeutil import now_utc_str

FILL = ["site_id", "room", "manufacturer", "model", "serial", "inventory_no", "os", "used_by", "purchased_on",
        "purchased_from", "warranty_until"]


def candidates(conn: sqlite3.Connection, device_id: int) -> List[Dict]:
    """Mögliche Doppel: gleiche MAC, gleiche Seriennummer oder gleicher Name/Hostname."""
    d = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not d:
        return []
    found: Dict[int, str] = {}
    macs = [r[0] for r in conn.execute("SELECT DISTINCT UPPER(mac) FROM ip_addresses WHERE device_id = ? AND mac != ''", (device_id,))]
    for r in conn.execute("SELECT agents.report FROM agents WHERE device_id = ? AND report IS NOT NULL", (device_id,)):
        import json
        for i in json.loads(r[0]).get("network", {}).get("interfaces", []):
            if i.get("mac") and i["mac"].upper() not in macs:
                macs.append(i["mac"].upper())
    if macs:
        for r in conn.execute(f"SELECT DISTINCT device_id FROM ip_addresses WHERE UPPER(mac) IN ({','.join('?' * len(macs))}) "
                              "AND device_id IS NOT NULL AND device_id != ?", macs + [device_id]):
            found.setdefault(r[0], "gleiche MAC-Adresse")
    if d["serial"].strip():
        for r in conn.execute("SELECT id FROM devices WHERE serial = ? COLLATE NOCASE AND id != ?", (d["serial"], device_id)):
            found.setdefault(r[0], "gleiche Seriennummer")
    names = {d["name"].strip().lower()} | {r[0].split(".")[0].lower() for r in conn.execute(
        "SELECT hostname FROM ip_addresses WHERE device_id = ? AND hostname != ''", (device_id,))}
    names.discard("")
    for r in conn.execute("SELECT d.id, d.name, (SELECT GROUP_CONCAT(hostname) FROM ip_addresses WHERE device_id = d.id) AS hosts "
                          "FROM devices d WHERE d.id != ?", (device_id,)):
        other = {r["name"].strip().lower()} | {h.split(".")[0].lower() for h in (r["hosts"] or "").split(",") if h}
        if names & other:
            found.setdefault(r["id"], "gleicher Name")
    out = []
    for oid, why in found.items():
        o = conn.execute("SELECT d.id, d.name, t.icon FROM devices d JOIN device_types t ON t.id = d.type_id WHERE d.id = ?", (oid,)).fetchone()
        if o:
            out.append({"id": o["id"], "name": o["name"], "icon": o["icon"], "reason": why})
    return out


def merge(conn: sqlite3.Connection, user, keep_id: int, other_id: int) -> Dict:
    """`other` in `keep` aufgehen lassen: leere Felder füllen, IPs, Lizenzen, Verbindungen, Zugangsdaten, Anhänge,
    Web-Adressen und Agent übernehmen, `other` löschen. Alles in einer Transaktion."""
    if keep_id == other_id:
        raise HTTPException(400, "Ein Gerät kann nicht mit sich selbst zusammengeführt werden")
    keep = conn.execute("SELECT * FROM devices WHERE id = ?", (keep_id,)).fetchone()
    other = conn.execute("SELECT * FROM devices WHERE id = ?", (other_id,)).fetchone()
    if not keep or not other:
        raise HTTPException(404, "Gerät nicht gefunden")
    agents = conn.execute("SELECT id, device_id FROM agents WHERE device_id IN (?, ?)", (keep_id, other_id)).fetchall()
    if len(agents) > 1:
        raise HTTPException(409, "Beide Geräte haben einen Agenten – einen davon zuerst unter Verwaltung → Agenten löschen")
    conn.execute("BEGIN")
    try:
        filled = []
        for col in FILL:
            if (keep[col] in (None, "")) and other[col] not in (None, ""):
                conn.execute(f"UPDATE devices SET {col} = ? WHERE id = ?", (other[col], keep_id))
                filled.append(col)
        if other["notes"].strip() and other["notes"].strip() not in keep["notes"]:
            notes = (keep["notes"].rstrip() + "\n\n" if keep["notes"].strip() else "") + other["notes"].strip()
            conn.execute("UPDATE devices SET notes = ? WHERE id = ?", (notes, keep_id))
        moved = {}
        moved["IP-Adressen"] = conn.execute("UPDATE ip_addresses SET device_id = ? WHERE device_id = ?", (keep_id, other_id)).rowcount
        for lid, in conn.execute("SELECT license_id FROM license_devices WHERE device_id = ?", (other_id,)).fetchall():
            conn.execute("INSERT OR IGNORE INTO license_devices(license_id, device_id) VALUES (?, ?)", (lid, keep_id))
        conn.execute("DELETE FROM license_devices WHERE device_id = ?", (other_id,))
        for ln in conn.execute("SELECT * FROM device_links WHERE a_id = ? OR b_id = ?", (other_id, other_id)).fetchall():
            a = keep_id if ln["a_id"] == other_id else ln["a_id"]
            b = keep_id if ln["b_id"] == other_id else ln["b_id"]
            conn.execute("DELETE FROM device_links WHERE id = ?", (ln["id"],))
            if a != b and not conn.execute("SELECT 1 FROM device_links WHERE (a_id = ? AND b_id = ?) OR (a_id = ? AND b_id = ?)",
                                           (a, b, b, a)).fetchone():
                conn.execute("INSERT INTO device_links(a_id, b_id, note) VALUES (?, ?, ?)", (a, b, ln["note"]))
        moved["Zugangsdaten"] = conn.execute("UPDATE credentials SET owner_id = ? WHERE owner_type = 'device' AND owner_id = ?",
                                             (keep_id, other_id)).rowcount
        moved["Anhänge"] = conn.execute("UPDATE attachments SET owner_id = ? WHERE owner_type = 'device' AND owner_id = ?",
                                        (keep_id, other_id)).rowcount
        for u in conn.execute("SELECT * FROM device_urls WHERE device_id = ?", (other_id,)).fetchall():
            if conn.execute("SELECT 1 FROM device_urls WHERE device_id = ? AND url = ?", (keep_id, u["url"])).fetchone():
                conn.execute("DELETE FROM device_urls WHERE id = ?", (u["id"],))
            else:
                conn.execute("UPDATE device_urls SET device_id = ?, sort = sort + 100 WHERE id = ?", (keep_id, u["id"]))
        moved["Agent"] = conn.execute("UPDATE agents SET device_id = ? WHERE device_id = ?", (keep_id, other_id)).rowcount
        conn.execute("UPDATE devices SET updated_at = ? WHERE id = ?", (now_utc_str(), keep_id))
        conn.execute("DELETE FROM devices WHERE id = ?", (other_id,))
        one = {"IP-Adressen": "IP-Adresse", "Zugangsdaten": "Zugangsdaten", "Anhänge": "Anhang"}
        what = ", ".join("Agent" if k == "Agent" else f"{v} {one[k] if v == 1 else k}" for k, v in moved.items() if v)
        log(conn, user, "doc_updated", "device", keep_id, keep["name"],
            f"zusammengeführt mit „{other['name']}“ (#{other_id})" + (f" – übernommen: {what}" if what else "") +
            (f"; ergänzt: {', '.join(filled)}" if filled else ""))
        log(conn, user, "doc_deleted", "device", other_id, other["name"], f"in „{keep['name']}“ (#{keep_id}) zusammengeführt")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"ok": True, "id": keep_id, "filled": filled, "moved": moved}
