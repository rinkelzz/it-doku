"""Geräte mit IP-Adressen, Lizenzen, Verknüpfungen, Anhängen und Verlauf."""
import csv
import io
import sqlite3
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..csvsafe import row as safe_row
from ..db import audit, get_db
from ..doku import (DEVICE_STATUS, LICENSE_KINDS, attachments, days_until, delete_attachments, diff, get_or_404,
                    history, insert_row, ip_key, log, strip_strings, update_row)
from ..security import admin_user, current_user
from .network import IP_SELECT, ip_out

router = APIRouter(prefix="/api/v1", tags=["Geräte"])

S = Field(None, max_length=200)


class DeviceIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type_id: Optional[int] = None
    site_id: Optional[int] = None
    room: Optional[str] = S
    manufacturer: Optional[str] = S
    model: Optional[str] = S
    serial: Optional[str] = S
    inventory_no: Optional[str] = S
    os: Optional[str] = S
    used_by: Optional[str] = S
    purchased_on: Optional[date] = None
    purchased_from: Optional[str] = S
    warranty_until: Optional[date] = None
    status: Optional[str] = Field(None, description="active, stock oder retired")
    notes: Optional[str] = Field(None, max_length=10000)
    ip: Optional[str] = Field(None, max_length=50, description="nur beim Anlegen: erste IP-Adresse")


LABELS = {"name": "Name", "type_id": "Typ", "site_id": "Standort", "room": "Raum", "manufacturer": "Hersteller",
          "model": "Modell", "serial": "Seriennummer", "inventory_no": "Inventar-Nr.", "os": "Betriebssystem",
          "used_by": "Benutzt von", "purchased_on": "Gekauft am", "purchased_from": "Gekauft bei",
          "warranty_until": "Garantie bis", "status": "Status", "notes": "Notizen"}

SELECT = ("SELECT d.*, t.name AS type_name, t.icon AS type_icon, s.name AS site_name, "
          "(SELECT GROUP_CONCAT(ip, ', ') FROM (SELECT ip FROM ip_addresses WHERE device_id = d.id ORDER BY id)) AS ips "
          "FROM devices d JOIN device_types t ON t.id = d.type_id LEFT JOIN sites s ON s.id = d.site_id")


def _out(r) -> dict:
    out = dict(r)
    out["status_label"] = DEVICE_STATUS.get(r["status"], r["status"])
    out["warranty_days"] = days_until(r["warranty_until"])
    return out


def _check(conn, values: dict) -> dict:
    if values.get("type_id") is not None:
        get_or_404(conn, "type", values["type_id"])
    if values.get("site_id"):
        get_or_404(conn, "site", values["site_id"])
    if "status" in values and values["status"] not in DEVICE_STATUS:
        raise HTTPException(400, "Status muss active, stock oder retired sein")
    return values


def _readable(conn, old, values: dict) -> dict:
    """Für den Verlauf: Typ/Standort/Status als Namen statt IDs."""
    def name(table, i):
        if not i:
            return None
        r = conn.execute(f"SELECT name FROM {table} WHERE id = ?", (i,)).fetchone()
        return r[0] if r else i
    v = dict(values)
    o = dict(old)
    for key, table in (("type_id", "device_types"), ("site_id", "sites")):
        if key in v:
            v[key] = name(table, v[key])
            o[key] = name(table, o[key])
    if "status" in v:
        v["status"] = DEVICE_STATUS.get(v["status"], v["status"])
        o["status"] = DEVICE_STATUS.get(o["status"], o["status"])
    return o, v


@router.get("/devices")
def list_devices(site_id: Optional[int] = None, type_id: Optional[int] = None,
                 status: Optional[str] = Query(None, description="active, stock, retired oder all; Standard: alle außer ausgemustert"),
                 q: Optional[str] = Query(None, max_length=100),
                 user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    sql, args = SELECT + " WHERE 1 = 1", []
    if site_id:
        sql += " AND d.site_id = ?"
        args.append(site_id)
    if type_id:
        sql += " AND d.type_id = ?"
        args.append(type_id)
    if status in DEVICE_STATUS:
        sql += " AND d.status = ?"
        args.append(status)
    elif status != "all":
        sql += " AND d.status != 'retired'"
    if q:
        like = f"%{q.strip()}%"
        sql += (" AND (d.name LIKE ? OR d.model LIKE ? OR d.manufacturer LIKE ? OR d.serial LIKE ? OR d.inventory_no LIKE ?"
                " OR d.room LIKE ? OR d.used_by LIKE ? OR d.id IN (SELECT device_id FROM ip_addresses WHERE ip LIKE ?"
                " OR mac LIKE ? OR hostname LIKE ?))")
        args += [like] * 10
    rows = [_out(r) for r in conn.execute(sql + " ORDER BY t.sort, d.name COLLATE NOCASE", args)]
    return rows


@router.get("/devices/counts")
def device_counts(site_id: Optional[int] = None, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Zahlen für die Seitenleiste (Standort, Typ, Status)."""
    where, args = ("WHERE site_id = ?", [site_id]) if site_id else ("", [])
    by_status = {r[0]: r[1] for r in conn.execute(f"SELECT status, COUNT(*) FROM devices {where} GROUP BY status", args)}
    by_type = {r[0]: r[1] for r in conn.execute(
        f"SELECT type_id, COUNT(*) FROM devices {where + (' AND' if where else 'WHERE')} status != 'retired' GROUP BY type_id", args)}
    by_site = {r[0]: r[1] for r in conn.execute("SELECT site_id, COUNT(*) FROM devices WHERE status != 'retired' GROUP BY site_id")}
    return {"status": by_status, "type": by_type, "site": by_site}


@router.get("/devices/suggest")
def suggest(user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Schon erfasste Werte als Vorschläge im Formular."""
    def vals(col):
        return [r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM devices WHERE {col} != '' ORDER BY {col} COLLATE NOCASE LIMIT 200")]
    return {k: vals(k) for k in ("manufacturer", "model", "os", "room", "used_by", "purchased_from")}


@router.get("/devices/export.csv")
def export_csv(site_id: Optional[int] = None, status: Optional[str] = None,
               user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = list_devices(site_id=site_id, type_id=None, status=status, q=None, user=user, conn=conn)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Name", "Typ", "Standort", "Raum", "Hersteller", "Modell", "Seriennummer", "Inventar-Nr.", "Betriebssystem",
                "IP-Adressen", "Benutzt von", "Gekauft am", "Gekauft bei", "Garantie bis", "Status", "Notizen"])
    for r in rows:
        w.writerow(safe_row([r["name"], r["type_name"], r["site_name"] or "", r["room"], r["manufacturer"], r["model"], r["serial"],
                             r["inventory_no"], r["os"], r["ips"] or "", r["used_by"], r["purchased_on"] or "",
                             r["purchased_from"], r["warranty_until"] or "", r["status_label"], r["notes"]]))
    audit(conn, user["id"], "export_csv", "devices", f"Geräteliste, {len(rows)} Geräte")
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="geraete.csv"'})


def device_detail(conn, device_id: int) -> dict:
    r = conn.execute(SELECT + " WHERE d.id = ?", (device_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Gerät nicht gefunden")
    out = _out(r)
    out["ip_list"] = sorted((ip_out(x) for x in conn.execute(IP_SELECT + " WHERE i.device_id = ?", (device_id,))),
                            key=lambda x: ip_key(x["ip"]))
    out["licenses"] = []
    for l in conn.execute("SELECT l.* FROM licenses l JOIN license_devices ld ON ld.license_id = l.id WHERE ld.device_id = ? "
                          "ORDER BY l.name COLLATE NOCASE", (device_id,)):
        used = l["seats_used"] if l["seats_used"] is not None else \
            conn.execute("SELECT COUNT(*) FROM license_devices WHERE license_id = ?", (l["id"],)).fetchone()[0]
        out["licenses"].append({"id": l["id"], "name": l["name"], "kind_label": LICENSE_KINDS.get(l["kind"], ""), "term": l["term"],
                                "seats": l["seats"], "used": used, "expires_on": l["expires_on"],
                                "days": days_until(l["expires_on"])})
    out["links"] = [dict(x) for x in conn.execute(
        "SELECT k.id, k.note, o.id AS device_id, o.name, t.icon FROM device_links k "
        "JOIN devices o ON o.id = CASE WHEN k.a_id = ? THEN k.b_id ELSE k.a_id END JOIN device_types t ON t.id = o.type_id "
        "WHERE k.a_id = ? OR k.b_id = ? ORDER BY o.name COLLATE NOCASE", (device_id, device_id, device_id))]
    out["files"] = attachments(conn, "device", device_id)
    out["history"] = history(conn, "device", device_id)
    return out


@router.get("/devices/{device_id}")
def get_device(device_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return device_detail(conn, device_id)


@router.post("/devices", status_code=201)
def create_device(data: DeviceIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    values = strip_strings(data.model_dump(exclude_unset=True))
    ip = values.pop("ip", None)
    if not values.get("name"):
        raise HTTPException(400, "Bitte einen Namen angeben")
    if not values.get("type_id"):
        raise HTTPException(400, "Bitte einen Typ wählen")
    if "site_id" not in values:  # nur ein Standort? → dorthin
        sites = conn.execute("SELECT id FROM sites LIMIT 2").fetchall()
        if len(sites) == 1:
            values["site_id"] = sites[0][0]
    values = _check(conn, values)
    if ip:
        from .network import _check_ip
        ipv = _check_ip(conn, {"ip": ip})
    did = insert_row(conn, "devices", values)
    log(conn, admin, "doc_created", "device", did, values["name"])
    if ip:
        ipv["device_id"] = did
        iid = insert_row(conn, "ip_addresses", ipv)
        log(conn, admin, "doc_created", "ip", iid, ipv["ip"], values["name"])
    return device_detail(conn, did)


@router.patch("/devices/{device_id}")
def update_device(device_id: int, data: DeviceIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "device", device_id)
    values = strip_strings(data.model_dump(exclude_unset=True))
    values.pop("ip", None)
    if "name" in values and not values["name"]:
        raise HTTPException(400, "Der Name darf nicht leer sein")
    if "type_id" in values and not values["type_id"]:
        raise HTTPException(400, "Bitte einen Typ wählen")
    values = _check(conn, values)
    o, v = _readable(conn, old, values)
    text = diff(o, v, LABELS)
    update_row(conn, "devices", device_id, values)
    if text:
        log(conn, admin, "doc_updated", "device", device_id, values.get("name") or old["name"], text)
    return device_detail(conn, device_id)


@router.delete("/devices/{device_id}")
def delete_device(device_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Endgültig löschen. Für Altgeräte besser Status „ausgemustert“ – dann bleibt die Doku erhalten."""
    old = get_or_404(conn, "device", device_id)
    conn.execute("DELETE FROM ip_addresses WHERE device_id = ?", (device_id,))
    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    delete_attachments(conn, "device", device_id)
    log(conn, admin, "doc_deleted", "device", device_id, old["name"])
    return {"ok": True}


# --- Verknüpfungen („Verbunden mit“) -----------------------------------------

class LinkIn(BaseModel):
    device_id: int
    note: Optional[str] = Field(None, max_length=100, description="z. B. „Port 7“ oder „Standarddrucker“")


@router.post("/devices/{device_id}/links", status_code=201)
def add_link(device_id: int, data: LinkIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    a = get_or_404(conn, "device", device_id)
    b = get_or_404(conn, "device", data.device_id)
    if a["id"] == b["id"]:
        raise HTTPException(400, "Ein Gerät kann nicht mit sich selbst verbunden sein")
    lo, hi = sorted((a["id"], b["id"]))
    if conn.execute("SELECT 1 FROM device_links WHERE a_id = ? AND b_id = ?", (lo, hi)).fetchone():
        raise HTTPException(409, "Diese Verbindung gibt es schon")
    note = (data.note or "").strip()
    conn.execute("INSERT INTO device_links(a_id, b_id, note) VALUES (?, ?, ?)", (lo, hi, note))
    for x, y in ((a, b), (b, a)):
        log(conn, admin, "doc_updated", "device", x["id"], x["name"], f"verbunden mit {y['name']}" + (f" ({note})" if note else ""))
    return device_detail(conn, device_id)


@router.delete("/device-links/{link_id}")
def delete_link(link_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    k = conn.execute("SELECT * FROM device_links WHERE id = ?", (link_id,)).fetchone()
    if not k:
        raise HTTPException(404, "Verbindung nicht gefunden")
    a, b = get_or_404(conn, "device", k["a_id"]), get_or_404(conn, "device", k["b_id"])
    conn.execute("DELETE FROM device_links WHERE id = ?", (link_id,))
    for x, y in ((a, b), (b, a)):
        log(conn, admin, "doc_updated", "device", x["id"], x["name"], f"Verbindung zu {y['name']} entfernt")
    return {"ok": True}
