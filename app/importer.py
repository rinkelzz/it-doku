"""CSV-Import für Geräte: Spalten zuordnen, prüfen (Vorschau), anlegen.

Liest beliebige CSV-Dateien (Excel-Export, Inventarliste): Trennzeichen ; , oder Tab, UTF-8 oder Windows-1252.
Dubletten werden über die Seriennummer erkannt und übersprungen. Unbekannte Typen und Standorte werden auf Wunsch
angelegt.
"""
import csv
import io
import ipaddress
import re
import sqlite3
from datetime import date
from typing import Dict, List, Optional

from fastapi import HTTPException

from .doku import DEVICE_STATUS, insert_row, log, network_for

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000

FIELDS = {  # Feld → (Anzeigename, Spaltennamen, die automatisch passen)
    "name": ("Name", ["name", "gerät", "geraet", "gerätename", "geraetename", "bezeichnung", "computer", "computername", "device", "gerätebezeichnung"]),
    "type": ("Typ", ["typ", "type", "art", "gerätetyp", "geraetetyp", "kategorie", "category", "geräteart"]),
    "site": ("Standort", ["standort", "site", "filiale", "location", "ort", "niederlassung"]),
    "room": ("Raum", ["raum", "zimmer", "room", "platz", "arbeitsplatz"]),
    "manufacturer": ("Hersteller", ["hersteller", "marke", "manufacturer", "make", "brand"]),
    "model": ("Modell", ["modell", "model", "typenbezeichnung", "produkt", "product"]),
    "serial": ("Seriennummer", ["seriennummer", "serial", "sn", "s n", "seriennr", "serien nr", "serial number", "serialnumber", "service tag"]),
    "inventory_no": ("Inventar-Nr.", ["inventar", "inventarnummer", "inventar nr", "inventarnr", "asset", "asset tag", "inventory"]),
    "os": ("Betriebssystem", ["betriebssystem", "os", "system", "operating system", "firmware"]),
    "used_by": ("Benutzt von", ["benutzer", "nutzer", "benutzt von", "user", "mitarbeiter", "zugeordnet", "besitzer", "owner"]),
    "purchased_on": ("Gekauft am", ["kaufdatum", "gekauft", "gekauft am", "anschaffung", "anschaffungsdatum", "purchase date", "kauf"]),
    "purchased_from": ("Gekauft bei", ["händler", "haendler", "lieferant", "gekauft bei", "bezugsquelle", "supplier", "shop"]),
    "warranty_until": ("Garantie bis", ["garantie", "garantie bis", "gewährleistung", "warranty", "garantieende", "warranty end"]),
    "status": ("Status", ["status", "zustand", "state"]),
    "ip": ("IP-Adresse", ["ip", "ip adresse", "ipv4", "ip address", "ipadresse", "adresse"]),
    "mac": ("MAC-Adresse", ["mac", "mac adresse", "mac address", "macadresse"]),
    "hostname": ("Hostname", ["hostname", "dns name", "rechnername", "host"]),
    "notes": ("Notizen", ["notiz", "notizen", "bemerkung", "bemerkungen", "kommentar", "notes", "comment", "beschreibung", "info"]),
}
STATUS_WORDS = {
    "active": ["aktiv", "active", "in betrieb", "im einsatz", "ok", "läuft", "ja", "1"],
    "stock": ["lager", "im lager", "stock", "reserve", "ersatz", "spare"],
    "retired": ["ausgemustert", "retired", "defekt", "entsorgt", "verkauft", "alt", "inaktiv", "nein", "0"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", (s or "").lower()).strip()


def decode(raw: bytes) -> str:
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "Die Datei ist zu groß (höchstens 2 MB)")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "Die Datei ist keine Textdatei (CSV)")


def parse(text: str) -> List[List[str]]:
    sample = text[:4096]
    counts = {d: sample.count(d) for d in (";", ",", "\t")}
    delim = max(counts, key=counts.get) if any(counts.values()) else ";"
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        raise HTTPException(400, "Die Datei ist leer")
    if len(rows) - 1 > MAX_ROWS:
        raise HTTPException(400, f"Zu viele Zeilen (höchstens {MAX_ROWS})")
    return rows


def guess_mapping(headers: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    normed = [_norm(h) for h in headers]
    for field, (_, words) in FIELDS.items():   # 1. exakte Treffer
        for i, h in enumerate(normed):
            if h in words and i not in out.values():
                out[field] = i
                break
    for field, (_, words) in FIELDS.items():   # 2. enthält (z. B. „Seriennummer (S/N)“)
        if field in out:
            continue
        for i, h in enumerate(normed):
            if i not in out.values() and any(len(w) > 3 and w in h for w in words):
                out[field] = i
                break
    return out


def parse_date(s: str) -> Optional[str]:
    s = s.strip()
    if not s:
        return None
    for pat, order in ((r"^(\d{4})-(\d{1,2})-(\d{1,2})", "ymd"), (r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", "dmy"),
                       (r"^(\d{1,2})\.(\d{1,2})\.(\d{2})$", "dmy2"), (r"^(\d{1,2})/(\d{1,2})/(\d{4})$", "dmy"),
                       (r"^(\d{1,2})[./](\d{4})$", "my")):
        m = re.match(pat, s)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        try:
            if order == "ymd":
                return date(g[0], g[1], g[2]).isoformat()
            if order == "dmy":
                return date(g[2], g[1], g[0]).isoformat()
            if order == "dmy2":
                return date(2000 + g[2], g[1], g[0]).isoformat()
            if order == "my":  # Monat/Jahr → Monatsende
                nxt = date(g[1] + (g[0] == 12), g[0] % 12 + 1, 1)
                return date.fromordinal(nxt.toordinal() - 1).isoformat()
        except ValueError:
            return "!"
    return "!"


def _status(s: str) -> Optional[str]:
    n = _norm(s)
    if not n:
        return "active"
    for key, words in STATUS_WORDS.items():
        if n in words or n == key:
            return key
    return None


def check(conn: sqlite3.Connection, rows: List[List[str]], mapping: Dict[str, int], create_types: bool, create_sites: bool,
          default_site_id: Optional[int]) -> List[Dict]:
    types = {r["name"].lower(): r["id"] for r in conn.execute("SELECT id, name FROM device_types")}
    other = next((tid for name, tid in types.items() if name == "sonstiges"), None)
    sites = {r["name"].lower(): r["id"] for r in conn.execute("SELECT id, name FROM sites")}
    if default_site_id is None and len(sites) == 1:
        default_site_id = next(iter(sites.values()))
    serials = {r[0].lower() for r in conn.execute("SELECT serial FROM devices WHERE serial != ''")}
    taken_ips = {(r[0], r[1]) for r in conn.execute("SELECT ip, network_id FROM ip_addresses")}
    seen_serials, seen_ips = set(), set()
    out = []
    for line, row in enumerate(rows[1:], start=2):
        v = {f: (row[i].strip() if i < len(row) else "") for f, i in mapping.items() if i is not None and i >= 0}
        errors, warnings = [], []
        values: Dict = {}
        name = v.get("name") or v.get("hostname") or ""
        if not name:
            errors.append("Name fehlt")
        values["name"] = name[:100]
        tname = v.get("type", "")
        if tname and tname.lower() in types:
            values["type_id"] = types[tname.lower()]
        elif tname and create_types:
            values["new_type"] = tname[:40]
            warnings.append(f"Typ „{tname}“ wird angelegt")
        else:
            values["type_id"] = other
            if tname:
                warnings.append(f"Typ „{tname}“ unbekannt → Sonstiges")
        sname = v.get("site", "")
        if sname and sname.lower() in sites:
            values["site_id"] = sites[sname.lower()]
        elif sname and create_sites:
            values["new_site"] = sname[:100]
            warnings.append(f"Standort „{sname}“ wird angelegt")
        else:
            values["site_id"] = default_site_id
            if sname:
                warnings.append(f"Standort „{sname}“ unbekannt → Standard")
        for f in ("room", "manufacturer", "model", "serial", "inventory_no", "os", "used_by", "purchased_from"):
            if v.get(f):
                values[f] = v[f][:200]
        if v.get("notes"):
            values["notes"] = v["notes"][:10000]
        for f, label in (("purchased_on", "Kaufdatum"), ("warranty_until", "Garantie")):
            if v.get(f):
                d = parse_date(v[f])
                if d == "!":
                    warnings.append(f"{label} „{v[f]}“ nicht erkannt – bleibt leer")
                elif d:
                    values[f] = d
        st = _status(v.get("status", ""))
        if st is None:
            warnings.append(f"Status „{v['status']}“ unbekannt → aktiv")
            st = "active"
        values["status"] = st
        if v.get("ip"):
            try:
                ip = str(ipaddress.ip_address(v["ip"]))
                net = network_for(conn, ip)
                if (ip, net) in taken_ips or (ip, net) in seen_ips:
                    warnings.append(f"IP {ip} ist schon vergeben – wird nicht übernommen")
                else:
                    values["ip"] = {"ip": ip, "network_id": net, "mac": v.get("mac", "").upper().replace("-", ":")[:40],
                                    "hostname": v.get("hostname", "")[:100]}
                    seen_ips.add((ip, net))
            except ValueError:
                warnings.append(f"IP „{v['ip']}“ ungültig – wird nicht übernommen")
        action = "error" if errors else "create"
        serial = (values.get("serial") or "").lower()
        if action == "create" and serial:
            if serial in serials:
                action, reason = "skip", "Seriennummer schon vorhanden"
                warnings.insert(0, reason)
            elif serial in seen_serials:
                action = "skip"
                warnings.insert(0, "Seriennummer doppelt in der Datei")
            seen_serials.add(serial)
        out.append({"line": line, "action": action, "errors": errors, "warnings": warnings, "values": values,
                    "show": {f: v.get(f, "") for f in ("name", "type", "site", "serial", "ip")}})
    return out


def run(conn: sqlite3.Connection, user, checked: List[Dict]) -> Dict:
    created_types: Dict[str, int] = {}
    created_sites: Dict[str, int] = {}
    names: Dict[str, str] = {}
    n = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for r in checked:
            if r["action"] != "create":
                continue
            v = dict(r["values"])
            ip = v.pop("ip", None)
            nt = v.pop("new_type", None)
            if nt:
                key = nt.lower()
                if key not in created_types:
                    sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM device_types").fetchone()[0]
                    created_types[key] = conn.execute("INSERT INTO device_types(name, icon, sort) VALUES (?, '📦', ?)", (nt, sort)).lastrowid
                    names["t:" + key] = nt
                v["type_id"] = created_types[key]
            ns = v.pop("new_site", None)
            if ns:
                key = ns.lower()
                if key not in created_sites:
                    created_sites[key] = insert_row(conn, "sites", {"name": ns})
                    names["s:" + key] = ns
                v["site_id"] = created_sites[key]
            did = insert_row(conn, "devices", v)
            log(conn, user, "doc_created", "device", did, v["name"], "per CSV-Import")
            if ip:
                ip["device_id"] = did
                insert_row(conn, "ip_addresses", ip)
            n += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"created": n, "skipped": sum(1 for r in checked if r["action"] == "skip"),
            "errors": sum(1 for r in checked if r["action"] == "error"),
            "new_types": [names["t:" + k] for k in created_types], "new_sites": [names["s:" + k] for k in created_sites]}
