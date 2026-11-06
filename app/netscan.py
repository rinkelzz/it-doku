"""Netzwerk-Scan ohne Root-Rechte und ohne externe Programme.

- Lebt eine Adresse? TCP-Verbindungsversuch auf gängige Ports: „offen“ und „abgelehnt“ (RST) heißen beide: da.
- MAC-Adressen aus der ARP-Tabelle der NAS (/proc/net/arp) – nur für Netze, in denen die NAS selbst hängt.
- Namen aus Reverse-DNS und NetBIOS (UDP 137, Windows/Samba).
- Hersteller grob aus dem MAC-Präfix, Gerätetyp geraten aus Ports und Hersteller.

Gescannt werden nur Netze mit Haken „scannen“ (IPv4, höchstens /22).
"""
import ipaddress
import random
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from .doku import is_placeholder_name
from .timeutil import now_utc, now_utc_str, to_utc_str

MAX_HOSTS = 1022           # /22
QUICK_PORTS = [445, 80, 443, 22, 3389, 9100, 5000, 8080]
ALL_PORTS = [21, 22, 23, 53, 80, 139, 443, 445, 515, 554, 631, 1883, 3389, 5000, 5001, 8006, 8080, 8123, 8443, 9100, 9443]
PORT_NAMES = {21: "FTP", 22: "SSH", 23: "Telnet", 53: "DNS", 80: "Web", 139: "NetBIOS", 443: "HTTPS", 445: "SMB",
              515: "LPD", 554: "RTSP", 631: "IPP", 1883: "MQTT", 3389: "RDP", 5000: "DSM", 5001: "DSM", 8006: "Proxmox", 8080: "Web", 8123: "Home Assistant", 9443: "HTTPS",
              8443: "HTTPS", 9100: "Drucker"}
THREADS = 128
KEEP_RUNS = 10

# MAC-Präfixe (OUI) häufiger Hersteller in Praxen und Büros – bewusst klein gehalten
OUI = {
    "00:11:32": "Synology", "00:04:0E": "AVM", "3C:A6:2F": "AVM", "7C:FF:4D": "AVM", "C8:0E:14": "AVM", "2C:91:AB": "AVM",
    "44:4E:6D": "AVM", "38:10:D5": "AVM", "E0:28:6D": "AVM", "98:9B:CB": "AVM", "30:05:5C": "Brother", "00:80:77": "Brother",
    "00:1B:A9": "Brother", "64:EB:8C": "Epson", "00:26:AB": "Epson", "3C:D9:2B": "HP", "A0:D3:C1": "HP", "00:14:22": "Dell",
    "F8:BC:12": "Dell", "18:66:DA": "Dell", "B8:CA:3A": "Dell", "00:0C:29": "VMware", "00:50:56": "VMware", "52:54:00": "QEMU/KVM",
    "00:15:5D": "Hyper-V", "08:00:27": "VirtualBox", "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi", "24:A4:3C": "Ubiquiti", "04:18:D6": "Ubiquiti", "78:8A:20": "Ubiquiti", "F0:9F:C2": "Ubiquiti",
    "74:83:C2": "Ubiquiti", "FC:EC:DA": "Ubiquiti", "24:5E:BE": "QNAP", "00:08:9B": "QNAP", "9C:3D:CF": "Netgear",
    "A0:40:A0": "Netgear", "20:E5:2A": "Netgear", "50:C7:BF": "TP-Link", "F4:F2:6D": "TP-Link", "98:DA:C4": "TP-Link",
    "00:04:13": "Snom", "80:5E:C0": "Yealink", "00:15:65": "Yealink", "00:A0:57": "Lancom",
}
VENDOR_TYPES = {"Synology": "NAS / Server", "QNAP": "NAS / Server", "Brother": "Drucker", "Epson": "Drucker",
                "Ubiquiti": "Access Point", "Snom": "Telefon / TK-Anlage", "Yealink": "Telefon / TK-Anlage",
                "VMware": "NAS / Server", "QEMU/KVM": "NAS / Server", "Hyper-V": "NAS / Server", "Lancom": "Router / Firewall"}

_state = {"running": False, "run_id": None, "phase": "", "done": 0, "total": 0, "started": None}
_lock = threading.Lock()


# --- Bausteine (in Tests ersetzbar) ------------------------------------------------

def probe(ip: str, port: int, timeout: float) -> Optional[str]:
    """'open', 'closed' (Gerät antwortet mit RST) oder None (keine Antwort)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        err = s.connect_ex((ip, port))
    except (socket.timeout, OSError):
        return None
    finally:
        s.close()
    if err == 0:
        return "open"
    if err in (111, 10061, 61):  # ECONNREFUSED (Linux, Windows, macOS)
        return "closed"
    return None


def read_arp() -> Dict[str, str]:
    """IP → MAC aus der ARP-Tabelle (nur vollständige Einträge)."""
    out = {}
    try:
        with open("/proc/net/arp", encoding="ascii", errors="replace") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "0x2" and parts[3] != "00:00:00:00:00:00":
                    out[parts[0]] = parts[3].upper()
    except OSError:
        pass
    return out


def dns_name(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError, UnicodeError):
        return ""
    if name == ip:
        return ""
    for suffix in (".fritz.box", ".local", ".lan", ".home", ".localdomain", ".box"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name[:100]


def netbios_name(ip: str, timeout: float = 0.8) -> str:
    """NetBIOS-Namensabfrage (NBSTAT) – liefert den Rechnernamen von Windows-PCs und Samba-Servern."""
    tid = random.randint(0, 0xFFFF)
    name = b"*" + b"\x00" * 15
    enc = b"".join(bytes([0x41 + (c >> 4), 0x41 + (c & 0x0F)]) for c in name)
    pkt = struct.pack(">HHHHHH", tid, 0, 1, 0, 0, 0) + b"\x20" + enc + b"\x00" + struct.pack(">HH", 0x21, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (ip, 137))
        data, _ = s.recvfrom(2048)
    except (socket.timeout, OSError):
        return ""
    finally:
        s.close()
    try:
        if struct.unpack(">H", data[:2])[0] != tid:
            return ""
        count = data[56]
        for i in range(count):
            off = 57 + i * 18
            raw, suffix, flags = data[off:off + 15], data[off + 15], struct.unpack(">H", data[off + 16:off + 18])[0]
            if suffix == 0x00 and not flags & 0x8000:
                return raw.decode("ascii", "replace").strip()[:100]
    except (IndexError, struct.error):
        return ""
    return ""


def vendor(mac: str) -> str:
    if not mac:
        return ""
    if int(mac[:2], 16) & 0x02:
        return "zufällige MAC"
    return OUI.get(mac[:8].upper(), "")


def guess_type(ports: List[int], vend: str, is_gateway: bool) -> str:
    p = set(ports)
    if is_gateway or vend == "AVM" and (53 in p or 80 in p):
        return "Router / Firewall"
    if vend in VENDOR_TYPES:
        return VENDOR_TYPES[vend]
    if p & {9100, 515, 631}:
        return "Drucker"
    if p & {5000, 5001}:
        return "NAS / Server"
    if 3389 in p or {139, 445} <= p:
        return "PC"
    if vend == "zufällige MAC":
        return "Smartphone / Tablet"
    if 554 in p:
        return "Sonstiges"
    if 22 in p and not p & {80, 443}:
        return "NAS / Server"
    if vend == "AVM":
        return "Access Point"
    return "Sonstiges"


# --- Ziel-Netze -------------------------------------------------------------------

def check_network(cidr: str) -> Optional[str]:
    """None = scanbar, sonst Begründung."""
    try:
        net = ipaddress.ip_network(cidr)
    except ValueError:
        return "Kein gültiges Netz eingetragen"
    if net.version != 4:
        return "Nur IPv4-Netze lassen sich scannen"
    if net.num_addresses - 2 > MAX_HOSTS:
        return "Das Netz ist zu groß zum Scannen (höchstens /22)"
    return None


def targets(conn, network_ids: Optional[List[int]] = None):
    rows = conn.execute("SELECT * FROM networks WHERE scan = 1 AND cidr != '' AND scan_agent_id IS NULL ORDER BY sort, id").fetchall()
    if network_ids:
        rows = [r for r in rows if r["id"] in network_ids]
    return [(r, [str(h) for h in ipaddress.ip_network(r["cidr"]).hosts()]) for r in rows if not check_network(r["cidr"])]


# --- Scan ------------------------------------------------------------------------

def status() -> Dict:
    with _lock:
        return dict(_state)


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def scan(conn, trigger: str = "manual", user_id: Optional[int] = None) -> int:
    """Scannt alle markierten Netze (blockiert). Liefert die ID des Laufs."""
    with _lock:
        if _state["running"]:
            raise RuntimeError("Es läuft schon ein Scan")
        _state.update(running=True, phase="Vorbereitung", done=0, total=0, started=time.time())
    try:
        tg = targets(conn)
        cur = conn.execute("INSERT INTO scan_runs(trigger, started_by, started_at, networks, addresses) VALUES (?, ?, ?, ?, ?)",
                           (trigger, user_id, now_utc_str(), ", ".join(n["name"] for n, _ in tg), sum(len(h) for _, h in tg)))
        run_id = cur.lastrowid
        _set(run_id=run_id, total=sum(len(h) for _, h in tg), phase="Adressen prüfen")
        found = {}  # ip → {network, ports}
        try:
            for net, hosts in tg:
                _scan_network(net, hosts, found)
            _set(phase="Namen und MAC-Adressen")
            arp = read_arp()
            for net, hosts in tg:
                for ip in hosts:
                    if ip in arp and ip not in found:
                        found[ip] = {"network": net, "ports": []}
            up = list(found)
            with ThreadPoolExecutor(32) as ex:
                names = dict(zip(up, ex.map(lambda ip: dns_name(ip) or netbios_name(ip), up)))
            hosts = [{"network_id": h["network"]["id"], "ip": ip, "mac": arp.get(ip, ""), "hostname": names.get(ip, ""),
                      "ports": h["ports"]} for ip, h in found.items()]
            store_hosts(conn, run_id, hosts, [net["id"] for net, _ in tg])
        except Exception as e:  # noqa: BLE001
            conn.execute("UPDATE scan_runs SET finished_at = ?, error = ? WHERE id = ?", (now_utc_str(), str(e)[:500], run_id))
            raise
        prune_runs(conn)
        return run_id
    finally:
        _set(running=False, phase="")


def store_hosts(conn, run_id: int, hosts: List[Dict], network_ids: List[int]) -> None:
    """Ergebnis eines Laufs speichern (lokal oder vom Agent): Hosts, „zuletzt online“, erster Scan je Netz."""
    stamp = now_utc_str()
    for h in hosts:
        mac = _norm_mac(h.get("mac", ""))
        conn.execute("INSERT OR REPLACE INTO scan_hosts(run_id, network_id, ip, mac, vendor, hostname, ports) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (run_id, h["network_id"], h["ip"], mac, vendor(mac), (h.get("hostname") or "")[:100],
                      ",".join(str(p) for p in sorted(set(h.get("ports") or [])))))
        conn.execute("UPDATE ip_addresses SET last_seen = ? WHERE ip = ? AND network_id = ?", (stamp, h["ip"], h["network_id"]))
    for nid in network_ids:
        conn.execute("UPDATE networks SET first_scan_at = COALESCE(first_scan_at, ?), last_scan_at = ? WHERE id = ?", (stamp, stamp, nid))
    conn.execute("UPDATE scan_runs SET finished_at = ?, hosts_up = ? WHERE id = ?", (now_utc_str(), len(hosts), run_id))


def prune_runs(conn) -> None:
    """Ältere Läufe löschen – aber den jüngsten jedes Scanners (NAS und jeder Agent) immer behalten."""
    keep = {r[0] for r in conn.execute("SELECT MAX(id) FROM scan_runs GROUP BY COALESCE(agent_id, 0)")}
    for (rid,) in conn.execute("SELECT id FROM scan_runs ORDER BY id DESC LIMIT -1 OFFSET ?", (KEEP_RUNS * 2,)).fetchall():
        if rid not in keep:
            conn.execute("DELETE FROM scan_runs WHERE id = ?", (rid,))


def _scan_network(net, hosts: List[str], found: Dict) -> None:
    def quick(ip):
        for port in QUICK_PORTS:
            r = probe(ip, port, 0.35)
            if r:
                return ip, port if r == "open" else None
        return ip, False

    def full(ip):
        return ip, [p for p in ALL_PORTS if p not in found[ip]["ports"] and probe(ip, p, 0.5) == "open"]

    with ThreadPoolExecutor(THREADS) as ex:
        for ip, res in ex.map(quick, hosts):
            with _lock:
                _state["done"] += 1
            if res is not False:
                found[ip] = {"network": net, "ports": [res] if res else []}
        ups = [ip for ip in hosts if ip in found]
        for ip, ports in ex.map(full, ups):
            found[ip]["ports"] += ports


def start_background(trigger: str, user_id: Optional[int]) -> None:
    """Scan im Hintergrund starten (eigene Datenbankverbindung)."""
    from .db import audit, connect
    if status()["running"]:
        raise RuntimeError("Es läuft schon ein Scan")

    def run():
        conn = connect()
        try:
            rid = scan(conn, trigger, user_id)
            r = conn.execute("SELECT * FROM scan_runs WHERE id = ?", (rid,)).fetchone()
            audit(conn, user_id, "scan_run", "scan", f"Netzwerk-Scan ({'nachts' if trigger == 'nightly' else 'von Hand'}): "
                                                     f"{r['hosts_up']} von {r['addresses']} Adressen online")
        except Exception as e:  # noqa: BLE001
            print(f"[itdoku] Netzwerk-Scan FEHLER: {e}", flush=True)
        finally:
            conn.close()
    threading.Thread(target=run, name="itdoku-scan", daemon=True).start()


# --- Auswertung ---------------------------------------------------------------------

def _norm_mac(m: str) -> str:
    return (m or "").upper().replace("-", ":")


def results(conn, stale_days: int = 30) -> Dict:
    last = conn.execute("SELECT * FROM scan_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    out = {"run": dict(last) if last else None, "new": [], "fill": [], "mismatch": [], "stale": []}
    ignored = {r[0] for r in conn.execute("SELECT key FROM scan_ignore")}
    types = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM device_types")}
    if last:
        known = {(r["ip"], r["network_id"]): r for r in conn.execute(
            "SELECT i.*, d.name AS device_name, t.icon AS device_icon FROM ip_addresses i LEFT JOIN devices d ON d.id = i.device_id "
            "LEFT JOIN device_types t ON t.id = d.type_id")}
        known_macs = {_norm_mac(r["mac"]) for r in known.values() if r["mac"]}
        gateways = {r["gateway"] for r in conn.execute("SELECT gateway FROM networks WHERE gateway != ''")}
        latest = {}  # Netz → jüngster fertiger Lauf seines Scanners (NAS selbst oder Agent)
        for n in conn.execute("SELECT id, scan_agent_id FROM networks WHERE scan = 1"):
            r = conn.execute("SELECT MAX(r.id) FROM scan_runs r JOIN scan_hosts h ON h.run_id = r.id AND h.network_id = ? "
                             "WHERE r.finished_at IS NOT NULL AND r.agent_id IS ?", (n["id"], n["scan_agent_id"])).fetchone()
            if r and r[0]:
                latest[n["id"]] = r[0]
        rows = []
        for nid, rid in latest.items():
            rows += conn.execute("SELECT h.*, n.name AS network_name FROM scan_hosts h LEFT JOIN networks n ON n.id = h.network_id "
                                 "WHERE h.run_id = ? AND h.network_id = ? ORDER BY h.network_id", (rid, nid)).fetchall()
        for h in rows:
            ports = [int(p) for p in h["ports"].split(",") if p]
            k = known.get((h["ip"], h["network_id"]))
            mac = _norm_mac(h["mac"])
            if not k:
                if f"new:ip:{h['ip']}" in ignored or (mac and f"new:mac:{mac}" in ignored) or (mac and mac in known_macs):
                    continue
                tname = guess_type(ports, h["vendor"], h["ip"] in gateways)
                out["new"].append({"ip": h["ip"], "network_id": h["network_id"], "network_name": h["network_name"], "mac": mac,
                                   "vendor": h["vendor"], "hostname": h["hostname"], "ports": ports,
                                   "port_names": [f"{p} {PORT_NAMES.get(p, '')}".strip() for p in ports],
                                   "type_name": tname, "type_id": types.get(tname) or types.get("Sonstiges")})
                continue
            if k["mac"] and mac and _norm_mac(k["mac"]) != mac:
                if f"mac:{k['id']}:{mac}" not in ignored:
                    out["mismatch"].append({"ip_id": k["id"], "ip": h["ip"], "device_id": k["device_id"], "device_name": k["device_name"],
                                            "device_icon": k["device_icon"], "mac_doc": k["mac"], "mac_now": mac, "vendor": h["vendor"]})
            elif (not k["mac"] and mac) or (not k["hostname"] and h["hostname"]):
                out["fill"].append({"ip_id": k["id"], "ip": h["ip"], "device_id": k["device_id"], "device_name": k["device_name"],
                                    "device_icon": k["device_icon"], "mac": mac if not k["mac"] else "",
                                    "hostname": h["hostname"] if not k["hostname"] else "",
                                    "rename": h["hostname"].split(".")[0] if h["hostname"] and is_placeholder_name(k["device_name"] or "") else ""})
    limit = to_utc_str(now_utc() - timedelta(days=stale_days))
    for r in conn.execute(
            "SELECT i.*, d.name AS device_name, d.status, t.icon AS device_icon, n.first_scan_at FROM ip_addresses i "
            "JOIN networks n ON n.id = i.network_id AND n.scan = 1 JOIN devices d ON d.id = i.device_id "
            "JOIN device_types t ON t.id = d.type_id WHERE d.status = 'active' AND "
            "((i.last_seen IS NOT NULL AND i.last_seen < ?) OR (i.last_seen IS NULL AND n.first_scan_at < ?)) ORDER BY i.last_seen",
            (limit, limit)):
        out["stale"].append({"ip_id": r["id"], "ip": r["ip"], "device_id": r["device_id"], "device_name": r["device_name"],
                             "device_icon": r["device_icon"], "last_seen": r["last_seen"]})
    return out


def run_due(conn, now=None) -> Optional[int]:
    """Nachts automatisch scannen (einmal pro Tag ab der eingestellten Stunde)."""
    from .db import get_setting, set_setting
    from .timeutil import to_local
    if get_setting(conn, "scan_nightly") != "1" or status()["running"]:
        return None
    local = to_local(now or now_utc())
    try:
        hour = int(get_setting(conn, "scan_hour") or 3)
    except ValueError:
        hour = 3
    today = local.date().isoformat()
    if local.hour < hour or get_setting(conn, "scan_last_day") == today or not targets(conn):
        return None
    set_setting(conn, "scan_last_day", today)
    return scan(conn, "nightly", None)
