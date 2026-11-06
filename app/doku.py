"""Gemeinsame Hilfen für die Dokumentation: Prüfen, Änderungen beschreiben, protokollieren, Fristen."""
import ipaddress
import sqlite3
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException

from .db import audit
from .timeutil import now_utc_str, today_local

# Art der Einträge → (Tabelle, Anzeigename, Symbol)
KINDS = {
    "device": ("devices", "Gerät", "🖥️"),
    "license": ("licenses", "Lizenz", "🔑"),
    "contact": ("contacts", "Kontakt", "👤"),
    "site": ("sites", "Standort", "📍"),
    "network": ("networks", "Netz", "🌐"),
    "ip": ("ip_addresses", "IP-Adresse", "🔢"),
    "type": ("device_types", "Gerätetyp", "🏷️"),
    "credential": ("credentials", "Zugang", "🔐"),
}

DEVICE_STATUS = {"active": "aktiv", "stock": "im Lager", "retired": "ausgemustert"}
IP_KINDS = {"static": "fest", "reservation": "DHCP-Reservierung", "dhcp": "DHCP"}
LICENSE_KINDS = {"software": "Software", "subscription": "Abo", "maintenance": "Wartungsvertrag",
                 "domain": "Domain", "certificate": "Zertifikat", "other": "Sonstiges"}
DUE_DAYS = 90  # „Bald fällig“: so viele Tage im Voraus

# Doku-Aktionen im Änderungsprotokoll (Bereich „Dokumentation“)
DOC_ACTIONS = {
    "doc_created": "Angelegt",
    "doc_updated": "Geändert",
    "doc_deleted": "Gelöscht",
    "file_added": "Anhang hinzugefügt",
    "file_deleted": "Anhang gelöscht",
}


def clean(value: Optional[str]) -> str:
    return (value or "").strip()


def get_or_404(conn: sqlite3.Connection, kind: str, item_id: int) -> sqlite3.Row:
    table, label, _ = KINDS[kind]
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"{label} nicht gefunden")
    return row


def log(conn: sqlite3.Connection, user, action: str, kind: str, item_id: int, name: str, text: str = "") -> None:
    """Protokolliert eine Änderung an einem Doku-Eintrag. Ziel „device:5“, Details „Name – Änderungen“."""
    audit(conn, user["id"] if user else None, action, f"{kind}:{item_id}", name + (" – " + text if text else ""))


def _show(value: Any) -> str:
    if value is None or value == "":
        return "–"
    if isinstance(value, bool):
        return "ja" if value else "nein"
    if isinstance(value, (date,)):
        value = value.isoformat()
    s = str(value)
    if len(s) == 10 and s[4] == "-" and s[7] == "-":  # Datum
        return f"{s[8:10]}.{s[5:7]}.{s[:4]}"
    return s if len(s) <= 60 else s[:57] + "…"


def diff(old: sqlite3.Row, new: Dict[str, Any], labels: Dict[str, str], hidden: Iterable[str] = ("notes",)) -> str:
    """Beschreibt Änderungen lesbar: „Raum: Empfang → Büro; Notizen geändert“."""
    parts = []
    for key, value in new.items():
        if key not in labels:
            continue
        before = old[key]
        if isinstance(value, bool):
            before = bool(before)
        if isinstance(value, date):
            value = value.isoformat()
        if (before if before is not None else "") == (value if value is not None else ""):
            continue
        if key in hidden:
            parts.append(f"{labels[key]} geändert")
        else:
            parts.append(f"{labels[key]}: {_show(before)} → {_show(value)}")
    return "; ".join(parts)


def update_row(conn: sqlite3.Connection, table: str, item_id: int, values: Dict[str, Any]) -> None:
    if not values:
        return
    values = {k: (v.isoformat() if isinstance(v, date) else int(v) if isinstance(v, bool) else v) for k, v in values.items()}
    cols = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE {table} SET {cols}, updated_at = ? WHERE id = ?", list(values.values()) + [now_utc_str(), item_id])


def insert_row(conn: sqlite3.Connection, table: str, values: Dict[str, Any]) -> int:
    values = {k: (v.isoformat() if isinstance(v, date) else int(v) if isinstance(v, bool) else v) for k, v in values.items()}
    values["created_at"] = now_utc_str()
    cols = ", ".join(values)
    cur = conn.execute(f"INSERT INTO {table}({cols}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    return cur.lastrowid


def strip_strings(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in values.items()}


def history(conn: sqlite3.Connection, kind: str, item_id: int, limit: int = 30) -> List[Dict]:
    """Verlauf eines Eintrags aus dem Änderungsprotokoll."""
    from .timeutil import local_iso
    rows = conn.execute(
        "SELECT a.ts, a.action, a.details, u.display_name AS actor FROM audit_log a "
        "LEFT JOIN users u ON u.id = a.actor_id WHERE a.target = ? ORDER BY a.id DESC LIMIT ?",
        (f"{kind}:{item_id}", limit)).fetchall()
    out = []
    for r in rows:
        text = r["details"] or ""
        text = text.split(" – ", 1)[1] if " – " in text else ""
        out.append({"ts_local": local_iso(r["ts"]), "actor": r["actor"] or "System",
                    "label": "" if r["action"].startswith(("file_", "secret_")) else DOC_ACTIONS.get(r["action"], r["action"]),
                    "text": text})
    return out


def delete_attachments(conn: sqlite3.Connection, kind: str, item_id: int) -> None:
    conn.execute("DELETE FROM attachments WHERE owner_type = ? AND owner_id = ?", (kind, item_id))


def attachments(conn: sqlite3.Connection, kind: str, item_id: int, role: str = "file") -> List[Dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, name, mime, size, created_at FROM attachments WHERE owner_type = ? AND owner_id = ? AND role = ? "
        "ORDER BY id", (kind, item_id, role))]


# --- IP-Adressen -------------------------------------------------------------

def parse_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        raise HTTPException(400, f"„{value}“ ist keine gültige IP-Adresse")


def parse_net(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError:
        raise HTTPException(400, f"„{value}“ ist kein gültiges Netz (z. B. 192.168.10.0/24)")


def ip_key(ip: str) -> Tuple[int, int]:
    try:
        a = ipaddress.ip_address(ip)
        return (a.version, int(a))
    except ValueError:
        return (9, 0)


def network_for(conn: sqlite3.Connection, ip: str) -> Optional[int]:
    """Passendes Netz für eine IP (das kleinste, das sie enthält)."""
    addr = ipaddress.ip_address(ip)
    best = None
    for r in conn.execute("SELECT id, cidr FROM networks WHERE cidr != ''"):
        try:
            net = ipaddress.ip_network(r["cidr"])
        except ValueError:
            continue
        if addr in net and (best is None or net.prefixlen > best[1]):
            best = (r["id"], net.prefixlen)
    return best[0] if best else None


# --- Fristen -----------------------------------------------------------------

def days_until(d: Optional[str]) -> Optional[int]:
    if not d:
        return None
    try:
        return (date.fromisoformat(d) - today_local()).days
    except ValueError:
        return None


def due_items(conn: sqlite3.Connection, site_id: Optional[int] = None, days: int = DUE_DAYS) -> List[Dict]:
    """Abgelaufene und bald ablaufende Lizenzen sowie bald endende Garantien aktiver Geräte."""
    limit = (today_local() + timedelta(days=days)).isoformat()
    out = []
    for r in conn.execute("SELECT * FROM licenses WHERE expires_on IS NOT NULL AND expires_on <= ? ORDER BY expires_on",
                          (limit,)):
        what = "Lizenz" if r["kind"] in ("software", "subscription") else LICENSE_KINDS.get(r["kind"], "Lizenz")
        out.append({"kind": "license", "id": r["id"], "name": r["name"], "what": what,
                    "info": r["term"], "date": r["expires_on"], "days": days_until(r["expires_on"])})
    sql = ("SELECT d.*, t.icon FROM devices d JOIN device_types t ON t.id = d.type_id WHERE d.status = 'active' "
           "AND d.warranty_until IS NOT NULL AND d.warranty_until >= ? AND d.warranty_until <= ?")
    args: list = [today_local().isoformat(), limit]
    if site_id:
        sql += " AND d.site_id = ?"
        args.append(site_id)
    for r in conn.execute(sql, args):
        out.append({"kind": "device", "id": r["id"], "name": r["name"], "what": "Garantie", "icon": r["icon"],
                    "info": " ".join(x for x in (r["manufacturer"], r["model"]) if x), "date": r["warranty_until"],
                    "days": days_until(r["warranty_until"])})
    out.sort(key=lambda x: x["date"])
    return out
