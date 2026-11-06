"""Agenten: Schlüssel, Bericht prüfen/bereinigen, Gerät zuordnen oder anlegen, stille Agenten.

Ein Agent läuft auf einem Server/PC (Windows, Linux, macOS) und schickt einmal täglich und beim Start einen Bericht
per HTTPS an /api/agent/v1/report – mit eigenem Schlüssel (Authorization: Bearer itd_…). Gespeichert wird nur der
SHA-256 des Schlüssels. Der Bericht wird auf bekannte Felder und Größen beschnitten, bevor er in die Datenbank kommt.
"""
import hashlib
import ipaddress
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from .db import get_setting
from .doku import insert_row, is_placeholder_name, log, network_for
from .timeutil import now_utc, now_utc_str, parse_utc, to_utc_str

TOKEN_PREFIX = "itd_"
MAX_BODY = 4 * 1024 * 1024
PLATFORMS = {"windows": "Windows", "linux": "Linux", "macos": "macOS"}
LIMITS = {"software": 5000, "services": 2000, "disks": 64, "interfaces": 64, "updates": 300}

# Seriennummern, die Hersteller als Platzhalter eintragen – damit darf nicht abgeglichen werden
_BAD_SERIALS = {"", "0", "none", "n/a", "na", "default string", "to be filled by o.e.m.", "system serial number",
                "not specified", "not applicable", "unknown", "0123456789", "123456789", "chassis serial number"}
# Platzhalter bei Hersteller/Modell (v. a. selbst gebaute PCs: das BIOS lässt die Felder auf „To Be Filled By O.E.M.“)
_BAD_HW = _BAD_SERIALS | {"system manufacturer", "system product name", "system version", "o.e.m.", "oem", "to be filled by oem",
                          "default string default string", "type1productconfigid", "x.x"}


def placeholder_hw(text: str) -> bool:
    return (text or "").strip().lower().rstrip(".") in {x.rstrip(".") for x in _BAD_HW}


def _hw_text(v: Any, n: int = 100) -> str:
    """Platzhalter-Teile entfernen: „To Be Filled By O.E.M. B550 Pro4“ → „B550 Pro4“."""
    text = _s(v, n)
    for bad in ("To Be Filled By O.E.M.", "To be filled by O.E.M.", "System Product Name", "System manufacturer", "Default string"):
        text = re.sub(re.escape(bad), "", text, flags=re.I).strip()
    return "" if placeholder_hw(text) else re.sub(r"\s{2,}", " ", text)


# --- Schlüssel --------------------------------------------------------------

def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hint(token: str) -> str:
    return "…" + token[-4:]


def find_by_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    if not token.startswith(TOKEN_PREFIX) or len(token) > 100:
        return None
    return conn.execute("SELECT * FROM agents WHERE token_hash = ?", (token_hash(token),)).fetchone()


# --- Bericht bereinigen ------------------------------------------------------

def _s(v: Any, n: int = 200) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "ja" if v else "nein"
    text = str(v).replace("\x00", "").strip()
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text[:n]


def _num(v: Any, lo: float = 0, hi: float = 1e9) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f < lo or f > hi:
        return None
    return round(f, 2)


def _int(v: Any, lo: int = 0, hi: int = 10 ** 9) -> Optional[int]:
    f = _num(v, lo, hi)
    return int(f) if f is not None else None


def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str) and v.strip().lower() in ("true", "1", "ja", "yes"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("false", "0", "nein", "no"):
        return False
    return None


def _ip(v: Any) -> str:
    try:
        return str(ipaddress.ip_address(str(v).split("%")[0].strip()))
    except ValueError:
        return ""


def _ips(v: Any, n: int = 32) -> List[str]:
    if not isinstance(v, list):
        v = [v] if v else []
    out = []
    for x in v[:n]:
        ip = _ip(x)
        if ip and ip not in out:
            out.append(ip)
    return out


def _mac(v: Any) -> str:
    hexes = re.sub(r"[^0-9a-fA-F]", "", str(v or ""))
    if len(hexes) != 12 or hexes in ("000000000000",):
        return ""
    return ":".join(hexes[i:i + 2] for i in range(0, 12, 2)).upper()


def _date(v: Any) -> str:
    """ISO-Datum/Zeit → „YYYY-MM-DD“ oder UTC-Zeitstempel wie überall in der App; sonst leer."""
    text = _s(v, 40)
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text
    try:
        dt = datetime.fromisoformat(re.sub(r"\.\d+", "", text.replace("Z", "+00:00")))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return to_utc_str(dt)


def _list(v: Any, n: int) -> list:
    return v[:n] if isinstance(v, list) else []


def _dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def sanitize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Nur bekannte Felder mit begrenzter Länge übernehmen – alles andere fällt weg."""
    os_ = _dict(raw.get("os"))
    hw = _dict(raw.get("hardware"))
    net = _dict(raw.get("network"))
    upd = _dict(raw.get("updates"))
    platform = _s(raw.get("platform"), 20).lower()
    out: Dict[str, Any] = {
        "agent_version": _s(raw.get("agent_version"), 20),
        "platform": platform if platform in PLATFORMS else "",
        "hostname": _s(raw.get("hostname"), 100),
        "domain": _s(raw.get("domain"), 100),
        "boot_time": _date(raw.get("boot_time")),
        "power_on_time": _date(raw.get("power_on_time")),
        "fast_startup": _bool(raw.get("fast_startup")),
        "logged_in_user": _s(raw.get("logged_in_user"), 100),
        "os": {"name": _s(os_.get("name"), 120), "version": _s(os_.get("version"), 60), "build": _s(os_.get("build"), 60),
               "arch": _s(os_.get("arch"), 30), "kernel": _s(os_.get("kernel"), 80),
               "installed_on": _date(os_.get("installed_on"))},
        "hardware": {"manufacturer": _hw_text(hw.get("manufacturer")) or _hw_text(hw.get("board_manufacturer")),
                     "model": _hw_text(hw.get("model")) or _hw_text(hw.get("board_product")),
                     "serial": _s(hw.get("serial"), 100), "cpu": _s(hw.get("cpu"), 150),
                     "cores": _int(hw.get("cores"), 1, 4096), "ram_mb": _int(hw.get("ram_mb"), 1, 1 << 30),
                     "chassis": _s(hw.get("chassis"), 20).lower(), "virtual": _bool(hw.get("virtual")),
                     "bios": _s(hw.get("bios"), 100)},
        "disks": [],
        "network": {"interfaces": [], "gateway": _ips(net.get("gateway"), 8), "dns": _ips(net.get("dns"), 8)},
        "software": [],
        "updates": {"pending": _int(upd.get("pending"), 0, 100000), "security": _int(upd.get("security"), 0, 100000),
                    "last_installed": _date(upd.get("last_installed")), "reboot_required": _bool(upd.get("reboot_required")),
                    "items": [_s(x, 200) for x in _list(upd.get("items"), LIMITS["updates"]) if _s(x, 200)],
                    "error": _s(upd.get("error"), 200)},
        "services": [],
    }
    for d in _list(raw.get("disks"), LIMITS["disks"]):
        d = _dict(d)
        total = _num(d.get("total_gb"), 0, 1e7)
        if not total:
            continue
        free = _num(d.get("free_gb"), 0, 1e7)
        out["disks"].append({"mount": _s(d.get("mount"), 120), "fs": _s(d.get("fs"), 30), "label": _s(d.get("label"), 60),
                             "total_gb": total, "free_gb": min(free, total) if free is not None else None})
    for i in _list(net.get("interfaces"), LIMITS["interfaces"]):
        i = _dict(i)
        entry = {"name": _s(i.get("name"), 80), "mac": _mac(i.get("mac")), "ipv4": [], "ipv6": _ips(i.get("ipv6"), 16)}
        for ip in _ips(i.get("ipv4"), 16):
            if ipaddress.ip_address(ip).version == 4:
                entry["ipv4"].append(ip)
        entry["ipv6"] = [x for x in entry["ipv6"] if ipaddress.ip_address(x).version == 6 and not ipaddress.ip_address(x).is_link_local]
        if entry["ipv4"] or entry["ipv6"] or entry["mac"]:
            out["network"]["interfaces"].append(entry)
    seen = set()
    for p in _list(raw.get("software"), LIMITS["software"]):
        p = _dict(p)
        name = _s(p.get("name"), 150)
        if not name:
            continue
        key = (name.lower(), _s(p.get("version"), 80))
        if key in seen:
            continue
        seen.add(key)
        out["software"].append({"name": name, "version": key[1], "publisher": _s(p.get("publisher"), 100),
                                "installed_on": _date(p.get("installed_on"))})
    out["software"].sort(key=lambda x: x["name"].lower())
    for sv in _list(raw.get("services"), LIMITS["services"]):
        sv = _dict(sv)
        name = _s(sv.get("name"), 120)
        if not name:
            continue
        state = _s(sv.get("state"), 20).lower()
        start = _s(sv.get("start"), 20).lower()
        out["services"].append({"name": name, "display": _s(sv.get("display"), 150),
                                "state": state if state in ("running", "stopped", "failed") else "other",
                                "start": start if start in ("auto", "manual", "disabled") else ""})
    out["services"].sort(key=lambda x: x["name"].lower())
    return out


# --- Auswertung --------------------------------------------------------------

def problems(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Was in der Oberfläche auffallen soll: volle Laufwerke, gestoppte Autostart-Dienste, Updates, Neustart."""
    full = [d for d in rep.get("disks", []) if d.get("free_gb") is not None and d["total_gb"]
            and d["free_gb"] / d["total_gb"] < 0.15]
    stopped = [s["name"] for s in rep.get("services", []) if s["start"] == "auto" and s["state"] in ("stopped", "failed")]
    upd = rep.get("updates", {})
    return {"disks_full": len(full), "services_stopped": stopped[:50], "updates_pending": upd.get("pending") or 0,
            "reboot_required": bool(upd.get("reboot_required"))}


def stale_days(conn: sqlite3.Connection) -> int:
    try:
        return max(1, int(get_setting(conn, "agent_stale_days") or 3))
    except ValueError:
        return 3


def is_stale(last_report_at: Optional[str], days: int) -> bool:
    if not last_report_at:
        return False  # noch nie gemeldet = „wartet auf ersten Bericht“, nicht „still“
    try:
        last = parse_utc(last_report_at)
    except ValueError:
        return False
    return bool(last) and now_utc() - last > timedelta(days=days)


def stale_agents(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    days = stale_days(conn)
    return [dict(r) for r in conn.execute(
        "SELECT a.id, a.name, a.last_report_at, a.device_id, d.name AS device_name FROM agents a "
        "LEFT JOIN devices d ON d.id = a.device_id WHERE a.disabled = 0 AND a.last_report_at IS NOT NULL ORDER BY a.name")
        if is_stale(r["last_report_at"], days)]


# --- Gerät zuordnen / anlegen / ergänzen ------------------------------------

def _good_serial(serial: str) -> bool:
    return serial.strip().lower() not in _BAD_SERIALS and len(serial.strip()) >= 4


def _type_id(conn: sqlite3.Connection, rep: Dict[str, Any]) -> int:
    hw, os_name = rep["hardware"], rep["os"]["name"].lower()
    chassis = hw.get("chassis", "")
    if "server" in os_name or chassis in ("server", "vm") or hw.get("virtual"):
        wanted = ["NAS / Server", "Server"]
    elif chassis == "laptop":
        wanted = ["Laptop", "Notebook"]
    else:
        wanted = ["PC", "Computer"]
    for name in wanted + ["Sonstiges"]:
        r = conn.execute("SELECT id FROM device_types WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if r:
            return r["id"]
    r = conn.execute("SELECT id FROM device_types ORDER BY sort, id LIMIT 1").fetchone()
    if r:
        return r["id"]
    return insert_row(conn, "device_types", {"name": "Sonstiges", "icon": "📦", "sort": 99})


def os_label(rep: Dict[str, Any]) -> str:
    o = rep["os"]
    name = o["name"]
    if o["version"] and o["version"] not in name:
        name = f"{name} {o['version']}".strip()
    return name[:100]


def match_device(conn: sqlite3.Connection, rep: Dict[str, Any]) -> Optional[int]:
    """Bestehendes Gerät finden: zuerst über die Seriennummer, dann über den Rechnernamen (Name oder Hostname einer IP)."""
    taken = "AND d.id NOT IN (SELECT device_id FROM agents WHERE device_id IS NOT NULL)"
    serial = rep["hardware"]["serial"]
    if _good_serial(serial):
        r = conn.execute(f"SELECT d.id FROM devices d WHERE d.serial = ? COLLATE NOCASE {taken} ORDER BY d.id LIMIT 1",
                         (serial,)).fetchone()
        if r:
            return r["id"]
    host = rep["hostname"].split(".")[0]
    if host:
        r = conn.execute(f"SELECT d.id FROM devices d WHERE d.name = ? COLLATE NOCASE {taken} ORDER BY d.id LIMIT 1",
                         (host,)).fetchone()
        if r:
            return r["id"]
        r = conn.execute(f"SELECT d.id FROM ip_addresses i JOIN devices d ON d.id = i.device_id "
                         f"WHERE (i.hostname = ? COLLATE NOCASE OR i.hostname LIKE ? COLLATE NOCASE) {taken} "
                         f"ORDER BY d.id LIMIT 1", (host, host + ".%")).fetchone()
        if r:
            return r["id"]
    return None


def _site_for(conn: sqlite3.Connection, rep: Dict[str, Any]) -> Optional[int]:
    for i in rep["network"]["interfaces"]:
        for ip in i["ipv4"]:
            nid = network_for(conn, ip)
            if nid:
                r = conn.execute("SELECT site_id FROM networks WHERE id = ?", (nid,)).fetchone()
                if r and r["site_id"]:
                    return r["site_id"]
    sites = conn.execute("SELECT id FROM sites LIMIT 2").fetchall()
    return sites[0]["id"] if len(sites) == 1 else None


def create_device(conn: sqlite3.Connection, agent: sqlite3.Row, rep: Dict[str, Any]) -> int:
    hw = rep["hardware"]
    name = (rep["hostname"].split(".")[0] or agent["name"])[:100]
    did = insert_row(conn, "devices", {
        "name": name, "type_id": _type_id(conn, rep), "site_id": _site_for(conn, rep), "status": "active",
        "manufacturer": hw["manufacturer"][:100], "model": hw["model"][:100],
        "serial": hw["serial"][:100] if _good_serial(hw["serial"]) else "", "os": os_label(rep)})
    log(conn, None, "doc_created", "device", did, name, f"vom Agent „{agent['name']}“ angelegt")
    return did


def update_device(conn: sqlite3.Connection, device_id: int, agent: sqlite3.Row, rep: Dict[str, Any]) -> None:
    """Betriebssystem immer nachziehen; Hersteller, Modell, Seriennummer nur, wenn sie leer sind (Handarbeit bleibt)."""
    d = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not d:
        return
    hw = rep["hardware"]
    changes: Dict[str, Tuple[str, str]] = {}
    label = os_label(rep)
    host = rep["hostname"].split(".")[0][:100]
    if host and is_placeholder_name(d["name"]):
        changes["name"] = (d["name"], host)
    if label and d["os"] != label:
        changes["os"] = (d["os"], label)
    for col, val in (("manufacturer", hw["manufacturer"]), ("model", hw["model"]),
                     ("serial", hw["serial"] if _good_serial(hw["serial"]) else "")):
        if val and (not d[col] or placeholder_hw(d[col]) or "o.e.m" in d[col].lower()) and d[col] != val[:100]:
            changes[col] = (d[col], val[:100])
    if changes:
        sets = ", ".join(f"{k} = ?" for k in changes)
        conn.execute(f"UPDATE devices SET {sets}, updated_at = ? WHERE id = ?",
                     [v[1] for v in changes.values()] + [now_utc_str(), device_id])
        labels = {"name": "Name", "os": "Betriebssystem", "manufacturer": "Hersteller", "model": "Modell", "serial": "Seriennummer"}
        text = "; ".join(f"{labels[k]}: {o or '–'} → {n}" for k, (o, n) in changes.items())
        log(conn, None, "doc_updated", "device", device_id, changes.get("name", ("", d["name"]))[1], f"{text} (Agent)")
    _sync_ips(conn, d, rep)


def _sync_ips(conn: sqlite3.Connection, device: sqlite3.Row, rep: Dict[str, Any]) -> None:
    """IPv4-Adressen aus dokumentierten Netzen am Gerät eintragen bzw. „zuletzt gesehen“ setzen."""
    now = now_utc_str()
    host = rep["hostname"].split(".")[0]
    for i in rep["network"]["interfaces"]:
        for ip in i["ipv4"]:
            if ipaddress.ip_address(ip).is_loopback or ipaddress.ip_address(ip).is_link_local:
                continue
            nid = network_for(conn, ip)
            row = conn.execute("SELECT * FROM ip_addresses WHERE ip = ? AND network_id IS ?", (ip, nid)).fetchone()
            if row:
                if row["device_id"] == device["id"]:
                    conn.execute("UPDATE ip_addresses SET last_seen = ?, mac = CASE WHEN mac = '' THEN ? ELSE mac END "
                                 "WHERE id = ?", (now, i["mac"], row["id"]))
                continue  # gehört einem anderen Gerät – nichts überschreiben
            if not nid:
                continue  # nur Adressen aus dokumentierten Netzen übernehmen
            iid = insert_row(conn, "ip_addresses", {"ip": ip, "network_id": nid, "device_id": device["id"], "mac": i["mac"],
                                                    "hostname": host, "kind": "dhcp", "last_seen": now})
            log(conn, None, "doc_created", "ip", iid, ip, f"{device['name']} (Agent)")


def store_report(conn: sqlite3.Connection, agent: sqlite3.Row, rep: Dict[str, Any], client_ip: str) -> Dict[str, Any]:
    device_id = agent["device_id"]
    created = False
    if device_id is None:
        device_id = match_device(conn, rep)
        if device_id is None:
            device_id = create_device(conn, agent, rep)
            created = True
        else:
            d = conn.execute("SELECT name FROM devices WHERE id = ?", (device_id,)).fetchone()
            log(conn, None, "doc_updated", "device", device_id, d["name"], f"mit Agent „{agent['name']}“ verbunden")
    if not created:
        update_device(conn, device_id, agent, rep)
    else:
        d = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        _sync_ips(conn, d, rep)
    conn.execute(
        "UPDATE agents SET device_id = ?, platform = ?, last_report_at = ?, last_ip = ?, agent_version = ?, hostname = ?, "
        "os_name = ?, report = ? WHERE id = ?",
        (device_id, rep["platform"] or agent["platform"], now_utc_str(), client_ip[:60], rep["agent_version"], rep["hostname"],
         os_label(rep), json.dumps(rep, ensure_ascii=False, separators=(",", ":")), agent["id"]))
    return {"device_id": device_id, "created": created}


# --- Scan vor Ort (Agent als Scanner für entfernte Netze) ---------------------

DUE_HOURS = 20


def report_due(agent: sqlite3.Row) -> bool:
    if not agent["last_report_at"]:
        return True
    try:
        last = parse_utc(agent["last_report_at"])
    except ValueError:
        return True
    return not last or now_utc() - last > timedelta(hours=DUE_HOURS)


def scan_due(conn: sqlite3.Connection, agent: sqlite3.Row) -> List[Dict[str, Any]]:
    """Netze dieses Agenten, die jetzt dran sind: angefordert oder letzter Lauf älter als 20 Stunden."""
    from .netscan import check_network
    out = []
    limit = to_utc_str(now_utc() - timedelta(hours=DUE_HOURS))
    for n in conn.execute("SELECT * FROM networks WHERE scan = 1 AND scan_agent_id = ? AND cidr != ''", (agent["id"],)):
        if check_network(n["cidr"]):
            continue
        last = n["last_scan_at"]
        if n["scan_requested"] or not last or last < limit:
            out.append({"network_id": n["id"], "name": n["name"], "cidr": n["cidr"]})
    return out


def store_scan(conn: sqlite3.Connection, agent: sqlite3.Row, raw: Dict[str, Any]) -> int:
    from . import netscan
    nets, hosts, addresses = [], [], 0
    for entry in raw["networks"][:32]:
        entry = _dict(entry)
        nid = _int(entry.get("network_id"), 1)
        n = conn.execute("SELECT * FROM networks WHERE id = ? AND scan_agent_id = ?", (nid, agent["id"])).fetchone() if nid else None
        if not n:
            continue  # nicht (mehr) diesem Agenten zugeordnet
        try:
            net = ipaddress.ip_network(n["cidr"])
        except ValueError:
            continue
        nets.append(n)
        addresses += max(0, net.num_addresses - 2)
        seen = set()
        for h in _list(entry.get("hosts"), netscan.MAX_HOSTS + 2):
            h = _dict(h)
            ip = _ip(h.get("ip"))
            if not ip or ip in seen or ipaddress.ip_address(ip) not in net:
                continue
            seen.add(ip)
            ports = sorted({p for p in (_int(x, 1, 65535) for x in _list(h.get("ports"), 64)) if p})
            hosts.append({"network_id": n["id"], "ip": ip, "mac": _mac(h.get("mac")), "hostname": _s(h.get("hostname"), 100),
                          "ports": ports})
    if not nets:
        raise HTTPException(400, "Diesem Agenten ist kein Netz zum Scannen zugeordnet")
    cur = conn.execute("INSERT INTO scan_runs(trigger, started_at, networks, addresses, agent_id) VALUES ('agent', ?, ?, ?, ?)",
                       (_date(raw.get("started_at")) or now_utc_str(), ", ".join(n["name"] for n in nets), addresses, agent["id"]))
    run_id = cur.lastrowid
    netscan.store_hosts(conn, run_id, hosts, [n["id"] for n in nets])
    conn.execute(f"UPDATE networks SET scan_requested = 0 WHERE id IN ({','.join('?' * len(nets))})", [n["id"] for n in nets])
    netscan.prune_runs(conn)
    return run_id
