"""Standorte (mit Internetanschluss und Netzwerkplan), Gerätetypen, Netze und IP-Adressen."""
import ipaddress
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_db
from ..doku import (IP_KINDS, clean, delete_attachments, diff, get_or_404, insert_row, ip_key, log,
                    network_for, parse_ip, parse_net, strip_strings, update_row)
from ..security import admin_user, current_user

router = APIRouter(prefix="/api/v1", tags=["Standorte & Netzwerk"])

S = Field(None, max_length=200)
LONG = Field(None, max_length=5000)


# --- Standorte ---------------------------------------------------------------

class SiteIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    address: Optional[str] = S
    notes: Optional[str] = LONG
    isp_provider: Optional[str] = S
    isp_tariff: Optional[str] = S
    isp_public_ip: Optional[str] = S
    isp_customer_no: Optional[str] = S
    isp_notes: Optional[str] = LONG
    sort: Optional[int] = None


SITE_LABELS = {"name": "Name", "address": "Adresse", "notes": "Notizen", "isp_provider": "Anbieter", "isp_tariff": "Tarif",
               "isp_public_ip": "Öffentliche IP", "isp_customer_no": "Kundennummer", "isp_notes": "Notizen Anschluss"}


def site_out(conn, r) -> dict:
    out = dict(r)
    out["devices"] = conn.execute("SELECT COUNT(*) FROM devices WHERE site_id = ? AND status != 'retired'", (r["id"],)).fetchone()[0]
    out["networks"] = conn.execute("SELECT COUNT(*) FROM networks WHERE site_id = ?", (r["id"],)).fetchone()[0]
    d = conn.execute("SELECT id, name, mime, size, created_at FROM attachments WHERE owner_type = 'site' AND owner_id = ? "
                     "AND role = 'diagram' ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
    out["diagram"] = dict(d) if d else None
    return out


@router.get("/sites")
def list_sites(user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return [site_out(conn, r) for r in conn.execute("SELECT * FROM sites ORDER BY sort, id")]


@router.post("/sites", status_code=201)
def create_site(data: SiteIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    values = strip_strings(data.model_dump(exclude_unset=True))
    if not values.get("name"):
        raise HTTPException(400, "Bitte einen Namen angeben")
    sid = insert_row(conn, "sites", values)
    log(conn, admin, "doc_created", "site", sid, values["name"])
    return site_out(conn, get_or_404(conn, "site", sid))


@router.patch("/sites/{site_id}")
def update_site(site_id: int, data: SiteIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "site", site_id)
    values = strip_strings(data.model_dump(exclude_unset=True))
    if "name" in values and not values["name"]:
        raise HTTPException(400, "Der Name darf nicht leer sein")
    text = diff(old, values, SITE_LABELS, hidden=("notes", "isp_notes"))
    update_row(conn, "sites", site_id, values)
    if text:
        log(conn, admin, "doc_updated", "site", site_id, values.get("name") or old["name"], text)
    return site_out(conn, get_or_404(conn, "site", site_id))


@router.delete("/sites/{site_id}")
def delete_site(site_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "site", site_id)
    if conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0] <= 1:
        raise HTTPException(400, "Der letzte Standort kann nicht gelöscht werden – einfach umbenennen")
    used = conn.execute("SELECT (SELECT COUNT(*) FROM devices WHERE site_id = ?) + (SELECT COUNT(*) FROM networks WHERE site_id = ?)",
                        (site_id, site_id)).fetchone()[0]
    if used:
        raise HTTPException(409, "An diesem Standort gibt es noch Geräte oder Netze – bitte zuerst einem anderen Standort zuordnen")
    delete_attachments(conn, "site", site_id)
    conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
    log(conn, admin, "doc_deleted", "site", site_id, old["name"])
    return {"ok": True}


# --- Gerätetypen ---------------------------------------------------------------

class TypeIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=40)
    icon: Optional[str] = Field(None, max_length=8)
    sort: Optional[int] = None


def types_out(conn):
    return [dict(r) for r in conn.execute(
        "SELECT t.*, (SELECT COUNT(*) FROM devices d WHERE d.type_id = t.id AND d.status != 'retired') AS devices, "
        "(SELECT COUNT(*) FROM devices d WHERE d.type_id = t.id) AS devices_all FROM device_types t ORDER BY t.sort, t.name")]


@router.get("/device-types")
def list_types(user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return types_out(conn)


def _check_type_name(conn, name: str, own_id: int = 0) -> str:
    name = clean(name)
    if not name:
        raise HTTPException(400, "Bitte einen Namen angeben")
    if conn.execute("SELECT 1 FROM device_types WHERE name = ? AND id != ?", (name, own_id)).fetchone():
        raise HTTPException(409, f"Den Typ „{name}“ gibt es schon")
    return name


@router.post("/device-types", status_code=201)
def create_type(data: TypeIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    name = _check_type_name(conn, data.name or "")
    sort = data.sort if data.sort is not None else (conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM device_types").fetchone()[0])
    cur = conn.execute("INSERT INTO device_types(name, icon, sort) VALUES (?, ?, ?)", (name, clean(data.icon) or "📦", sort))
    log(conn, admin, "doc_created", "type", cur.lastrowid, name)
    return types_out(conn)


@router.patch("/device-types/{type_id}")
def update_type(type_id: int, data: TypeIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "type", type_id)
    values = data.model_dump(exclude_unset=True)
    if "name" in values:
        values["name"] = _check_type_name(conn, values["name"] or "", type_id)
    if "icon" in values:
        values["icon"] = clean(values["icon"]) or "📦"
    text = diff(old, values, {"name": "Name", "icon": "Symbol"})
    if values:
        conn.execute(f"UPDATE device_types SET {', '.join(k + ' = ?' for k in values)} WHERE id = ?",
                     list(values.values()) + [type_id])
    if text:
        log(conn, admin, "doc_updated", "type", type_id, values.get("name") or old["name"], text)
    return types_out(conn)


@router.post("/device-types/{type_id}/move")
def move_type(type_id: int, up: bool = True, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    get_or_404(conn, "type", type_id)
    ids = [r[0] for r in conn.execute("SELECT id FROM device_types ORDER BY sort, name")]
    i = ids.index(type_id)
    j = i - 1 if up else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        for n, tid in enumerate(ids):
            conn.execute("UPDATE device_types SET sort = ? WHERE id = ?", (n, tid))
    return types_out(conn)


@router.delete("/device-types/{type_id}")
def delete_type(type_id: int, into: Optional[int] = Query(None, description="Geräte vorher diesem Typ zuordnen"),
                admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Löschen – Typen mit Geräten nur zusammen mit „into“ (Zusammenlegen)."""
    old = get_or_404(conn, "type", type_id)
    used = conn.execute("SELECT COUNT(*) FROM devices WHERE type_id = ?", (type_id,)).fetchone()[0]
    text = ""
    if used:
        if not into or into == type_id:
            raise HTTPException(409, f"Dieser Typ hat noch {used} Geräte – zum Löschen einen Typ zum Zusammenlegen wählen")
        target = get_or_404(conn, "type", into)
        conn.execute("UPDATE devices SET type_id = ? WHERE type_id = ?", (into, type_id))
        text = f"{used} Geräte → {target['name']}"
    conn.execute("DELETE FROM device_types WHERE id = ?", (type_id,))
    log(conn, admin, "doc_deleted", "type", type_id, old["name"], text)
    return types_out(conn)


# --- Netze ---------------------------------------------------------------------

class NetworkIn(BaseModel):
    site_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    vlan: Optional[int] = Field(None, ge=0, le=4094)
    cidr: Optional[str] = Field(None, max_length=50)
    gateway: Optional[str] = Field(None, max_length=50)
    dhcp_from: Optional[str] = Field(None, max_length=50)
    dhcp_to: Optional[str] = Field(None, max_length=50)
    dns: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = LONG
    sort: Optional[int] = None
    scan: Optional[bool] = Field(None, description="beim Netzwerk-Scan berücksichtigen (IPv4, höchstens /22)")
    scan_agent_id: Optional[int] = Field(None, description="Agent, der das Netz vor Ort scannt (leer = die NAS selbst)")


NET_LABELS = {"name": "Name", "vlan": "VLAN", "cidr": "Netz", "gateway": "Gateway", "dhcp_from": "DHCP von",
              "dhcp_to": "DHCP bis", "dns": "DNS", "notes": "Notizen", "site_id": "Standort", "scan": "Scannen",
              "scan_agent_id": "Gescannt von"}


def _check_network(conn, values: dict) -> dict:
    if "cidr" in values:
        values["cidr"] = parse_net(values["cidr"] or "")
    for k in ("gateway", "dhcp_from", "dhcp_to"):
        if values.get(k):
            values[k] = parse_ip(values[k])
    if values.get("site_id"):
        get_or_404(conn, "site", values["site_id"])
    if values.get("scan_agent_id") and not conn.execute("SELECT 1 FROM agents WHERE id = ?", (values["scan_agent_id"],)).fetchone():
        raise HTTPException(404, "Agent nicht gefunden")
    if values.get("scan"):
        from ..netscan import check_network
        cidr = values.get("cidr") if "cidr" in values else (conn.execute("SELECT cidr FROM networks WHERE id = ?", (values.get("_id"),)).fetchone() or [""])[0]
        problem = check_network(cidr or "")
        if problem:
            raise HTTPException(400, f"Scannen geht hier nicht: {problem}")
    values.pop("_id", None)
    return values


def network_out(conn, r) -> dict:
    out = dict(r)
    out["scan"] = bool(r["scan"]) if "scan" in r.keys() else False
    out["scan_requested"] = bool(r["scan_requested"]) if "scan_requested" in r.keys() else False
    a = conn.execute("SELECT name FROM agents WHERE id = ?", (r["scan_agent_id"],)).fetchone() \
        if "scan_agent_id" in r.keys() and r["scan_agent_id"] else None
    out["scan_agent_name"] = a["name"] if a else None
    out["used"] = conn.execute("SELECT COUNT(*) FROM ip_addresses WHERE network_id = ?", (r["id"],)).fetchone()[0]
    out["size"] = None
    if r["cidr"]:
        try:
            net = ipaddress.ip_network(r["cidr"])
            out["size"] = max(net.num_addresses - 2, 1) if net.version == 4 and net.prefixlen < 31 else net.num_addresses
        except ValueError:
            pass
    return out


@router.get("/networks")
def list_networks(site_id: Optional[int] = None, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    sql, args = "SELECT * FROM networks", []
    if site_id:
        sql += " WHERE site_id = ?"
        args.append(site_id)
    return [network_out(conn, r) for r in conn.execute(sql + " ORDER BY sort, vlan, name", args)]


@router.post("/networks", status_code=201)
def create_network(data: NetworkIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    values = _check_network(conn, strip_strings(data.model_dump(exclude_unset=True)))
    if not values.get("name"):
        raise HTTPException(400, "Bitte einen Namen angeben")
    if values.get("scan_agent_id"):
        values["scan_requested"] = 1
    nid = insert_row(conn, "networks", values)
    # vorhandene IPs ohne Netz, die hineinpassen, gleich zuordnen
    if values.get("cidr"):
        net = ipaddress.ip_network(values["cidr"])
        for r in conn.execute("SELECT id, ip FROM ip_addresses WHERE network_id IS NULL").fetchall():
            try:
                if ipaddress.ip_address(r["ip"]) in net:
                    conn.execute("UPDATE ip_addresses SET network_id = ? WHERE id = ?", (nid, r["id"]))
            except ValueError:
                pass
    log(conn, admin, "doc_created", "network", nid, values["name"], values.get("cidr", ""))
    return network_out(conn, get_or_404(conn, "network", nid))


@router.patch("/networks/{network_id}")
def update_network(network_id: int, data: NetworkIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "network", network_id)
    values = _check_network(conn, {**strip_strings(data.model_dump(exclude_unset=True)), "_id": network_id})
    if "name" in values and not values["name"]:
        raise HTTPException(400, "Der Name darf nicht leer sein")
    shown_old, shown_new = dict(old), dict(values)
    if "scan_agent_id" in values:
        def agent_name(i):
            r = conn.execute("SELECT name FROM agents WHERE id = ?", (i,)).fetchone() if i else None
            return f"Agent „{r['name']}“" if r else "NAS"
        shown_old["scan_agent_id"], shown_new["scan_agent_id"] = agent_name(old["scan_agent_id"]), agent_name(values["scan_agent_id"])
    text = diff(shown_old, shown_new, NET_LABELS)
    if "scan_agent_id" in values and values["scan_agent_id"] != old["scan_agent_id"] and values["scan_agent_id"]:
        values["scan_requested"] = 1  # neuer Scanner: beim nächsten Kontakt gleich scannen
    update_row(conn, "networks", network_id, values)
    if text:
        log(conn, admin, "doc_updated", "network", network_id, values.get("name") or old["name"], text)
    return network_out(conn, get_or_404(conn, "network", network_id))


@router.delete("/networks/{network_id}")
def delete_network(network_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "network", network_id)
    n = conn.execute("SELECT COUNT(*) FROM ip_addresses WHERE network_id = ?", (network_id,)).fetchone()[0]
    conn.execute("DELETE FROM networks WHERE id = ?", (network_id,))
    delete_attachments(conn, "network", network_id)
    log(conn, admin, "doc_deleted", "network", network_id, old["name"], f"mit {n} IP-Adressen" if n else "")
    return {"ok": True}


# --- IP-Adressen ---------------------------------------------------------------

class IpIn(BaseModel):
    ip: Optional[str] = Field(None, max_length=50)
    network_id: Optional[int] = None
    device_id: Optional[int] = None
    mac: Optional[str] = Field(None, max_length=40)
    hostname: Optional[str] = Field(None, max_length=100)
    kind: Optional[str] = Field(None, description="static, reservation oder dhcp")
    notes: Optional[str] = Field(None, max_length=500)


IP_LABELS = {"ip": "IP", "mac": "MAC", "hostname": "Hostname", "kind": "Art", "notes": "Hinweis", "device_id": "Gerät"}


def ip_out(r) -> dict:
    out = dict(r)
    out["kind_label"] = IP_KINDS.get(r["kind"], r["kind"])
    return out


IP_SELECT = ("SELECT i.*, d.name AS device_name, t.icon AS device_icon, n.name AS network_name FROM ip_addresses i "
             "LEFT JOIN devices d ON d.id = i.device_id LEFT JOIN device_types t ON t.id = d.type_id "
             "LEFT JOIN networks n ON n.id = i.network_id")


def _check_ip(conn, values: dict, own_id: int = 0) -> dict:
    if "ip" in values:
        values["ip"] = parse_ip(values["ip"] or "")
        if "network_id" not in values or values["network_id"] is None:
            values["network_id"] = network_for(conn, values["ip"])
        dup = conn.execute("SELECT d.name FROM ip_addresses i LEFT JOIN devices d ON d.id = i.device_id "
                           "WHERE i.ip = ? AND i.id != ? AND i.network_id IS ?", (values["ip"], own_id, values["network_id"])).fetchone()
        if dup:
            raise HTTPException(409, f"Die IP {values['ip']} ist schon vergeben" + (f" ({dup[0]})" if dup[0] else ""))
    if values.get("network_id"):
        get_or_404(conn, "network", values["network_id"])
    if values.get("device_id"):
        get_or_404(conn, "device", values["device_id"])
    if "kind" in values:
        if values["kind"] not in IP_KINDS:
            raise HTTPException(400, "Art muss static, reservation oder dhcp sein")
    if values.get("mac"):
        values["mac"] = values["mac"].upper().replace("-", ":")
    return values


@router.get("/ips")
def list_ips(network_id: Optional[int] = None, device_id: Optional[int] = None, free: bool = False,
             user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """IP-Liste eines Netzes (oder eines Geräts). Mit free=1 auch freie Adressen außerhalb des DHCP-Bereichs (bis /22)."""
    sql, args = IP_SELECT + " WHERE 1 = 1", []
    if network_id:
        sql += " AND i.network_id = ?"
        args.append(network_id)
    if device_id:
        sql += " AND i.device_id = ?"
        args.append(device_id)
    rows = sorted((ip_out(r) for r in conn.execute(sql, args)), key=lambda x: ip_key(x["ip"]))
    from .. import weburl
    urls = weburl.device_urls(conn, sorted({r["device_id"] for r in rows if r["device_id"]}))
    ports = weburl.latest_ports(conn, [r["ip"] for r in rows])
    for r in rows:
        own = urls.get(r["device_id"], []) if r["device_id"] else []
        r["urls"] = own
        r["web_auto"] = "" if own else weburl.auto_url(r["ip"], r["hostname"], ports.get(r["ip"], ""))
    if free and network_id:
        net = get_or_404(conn, "network", network_id)
        try:
            n = ipaddress.ip_network(net["cidr"])
        except ValueError:
            n = None
        if n and n.version == 4 and n.num_addresses <= 1024:
            used = {r["ip"] for r in rows}
            lo = hi = None
            if net["dhcp_from"] and net["dhcp_to"]:
                lo, hi = int(ipaddress.ip_address(net["dhcp_from"])), int(ipaddress.ip_address(net["dhcp_to"]))
            gw = net["gateway"]
            for a in n.hosts():
                s = str(a)
                if s in used or s == gw or (lo is not None and lo <= int(a) <= hi):
                    continue
                rows.append({"id": None, "ip": s, "free": True})
            rows.sort(key=lambda x: ip_key(x["ip"]))
    return rows


@router.post("/ips", status_code=201)
def create_ip(data: IpIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    values = strip_strings(data.model_dump(exclude_unset=True))
    if not values.get("ip"):
        raise HTTPException(400, "Bitte eine IP-Adresse angeben")
    values = _check_ip(conn, values)
    iid = insert_row(conn, "ip_addresses", values)
    row = conn.execute(IP_SELECT + " WHERE i.id = ?", (iid,)).fetchone()
    log(conn, admin, "doc_created", "ip", iid, row["ip"], row["device_name"] or "")
    if row["device_id"]:
        log(conn, admin, "doc_updated", "device", row["device_id"], row["device_name"], f"IP {row['ip']} hinzugefügt")
    return ip_out(row)


@router.patch("/ips/{ip_id}")
def update_ip(ip_id: int, data: IpIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "ip", ip_id)
    values = _check_ip(conn, strip_strings(data.model_dump(exclude_unset=True)), ip_id)
    text = diff(old, values, IP_LABELS)
    update_row(conn, "ip_addresses", ip_id, values)
    row = conn.execute(IP_SELECT + " WHERE i.id = ?", (ip_id,)).fetchone()
    if text:
        log(conn, admin, "doc_updated", "ip", ip_id, row["ip"], text)
        for dev in {old["device_id"], row["device_id"]} - {None}:
            d = get_or_404(conn, "device", dev)
            log(conn, admin, "doc_updated", "device", dev, d["name"], f"IP {old['ip']}: {text}")
    return ip_out(row)


@router.delete("/ips/{ip_id}")
def delete_ip(ip_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = conn.execute(IP_SELECT + " WHERE i.id = ?", (ip_id,)).fetchone()
    if not old:
        raise HTTPException(404, "IP-Adresse nicht gefunden")
    conn.execute("DELETE FROM ip_addresses WHERE id = ?", (ip_id,))
    log(conn, admin, "doc_deleted", "ip", ip_id, old["ip"], old["device_name"] or "")
    if old["device_id"]:
        log(conn, admin, "doc_updated", "device", old["device_id"], old["device_name"], f"IP {old['ip']} entfernt")
    return {"ok": True}

