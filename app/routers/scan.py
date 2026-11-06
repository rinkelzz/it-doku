"""Netzwerk-Scan: starten, Fortschritt, Ergebnisse, neue Geräte übernehmen, ergänzen, ignorieren."""
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import netscan
from ..db import audit, get_db, get_setting, set_setting
from ..doku import get_or_404, insert_row, log, parse_ip
from ..security import admin_user
from ..timeutil import local_iso, now_utc_str

router = APIRouter(prefix="/api/v1/scan", tags=["Netzwerk-Scan"])


def _stale_days(conn) -> int:
    try:
        return int(get_setting(conn, "scan_stale_days") or 30)
    except ValueError:
        return 30


@router.get("")
def overview(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    res = netscan.results(conn, _stale_days(conn))
    if res["run"]:
        for k in ("started_at", "finished_at"):
            res["run"][k + "_local"] = local_iso(res["run"][k])
    res["status"] = netscan.status()
    res["settings"] = {"nightly": get_setting(conn, "scan_nightly") == "1", "hour": int(get_setting(conn, "scan_hour") or 3),
                       "stale_days": _stale_days(conn)}
    res["networks"] = [{"id": r["id"], "name": r["name"], "cidr": r["cidr"], "scan": bool(r["scan"]),
                        "problem": netscan.check_network(r["cidr"]) if r["cidr"] else "Kein Netz (CIDR) eingetragen"}
                       for r in conn.execute("SELECT * FROM networks ORDER BY sort, id")]
    return res


@router.post("/start")
def start(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    if not netscan.targets(conn):
        raise HTTPException(400, "Kein Netz zum Scannen markiert – im Netz „scannen“ anhaken (IPv4, höchstens /22)")
    try:
        netscan.start_background("manual", admin["id"])
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@router.get("/status")
def scan_status(admin=Depends(admin_user)):
    return netscan.status()


class SettingsIn(BaseModel):
    nightly: Optional[bool] = None
    hour: Optional[int] = Field(None, ge=0, le=23)
    stale_days: Optional[int] = Field(None, ge=7, le=365)


@router.patch("/settings")
def scan_settings(data: SettingsIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    if data.nightly is not None:
        set_setting(conn, "scan_nightly", "1" if data.nightly else "0")
    if data.hour is not None:
        set_setting(conn, "scan_hour", str(data.hour))
    if data.stale_days is not None:
        set_setting(conn, "scan_stale_days", str(data.stale_days))
    audit(conn, admin["id"], "settings_updated", "scan", f"Netzwerk-Scan: {data.model_dump(exclude_unset=True)}")
    return {"ok": True}


class AdoptItem(BaseModel):
    ip: str = Field(..., max_length=50)
    network_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=100)
    type_id: int
    mac: Optional[str] = Field("", max_length=40)
    hostname: Optional[str] = Field("", max_length=100)


class AdoptIn(BaseModel):
    items: List[AdoptItem] = Field(..., max_length=500)


@router.post("/adopt")
def adopt(data: AdoptIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Gefundene Adressen als Geräte anlegen (mit IP, MAC, Hostname)."""
    n = 0
    for it in data.items:
        ip = parse_ip(it.ip)
        get_or_404(conn, "type", it.type_id)
        site_id = None
        if it.network_id:
            site_id = get_or_404(conn, "network", it.network_id)["site_id"]
        if conn.execute("SELECT 1 FROM ip_addresses WHERE ip = ? AND network_id IS ?", (ip, it.network_id)).fetchone():
            continue
        did = insert_row(conn, "devices", {"name": it.name.strip(), "type_id": it.type_id, "site_id": site_id, "status": "active"})
        insert_row(conn, "ip_addresses", {"ip": ip, "network_id": it.network_id, "device_id": did, "mac": (it.mac or "").upper(),
                                          "hostname": (it.hostname or "").strip(), "kind": "static", "last_seen": now_utc_str()})
        log(conn, admin, "doc_created", "device", did, it.name.strip(), f"aus dem Netzwerk-Scan ({ip})")
        n += 1
    return {"created": n}


class FillItem(BaseModel):
    ip_id: int
    mac: Optional[str] = Field(None, max_length=40)
    hostname: Optional[str] = Field(None, max_length=100)


class FillIn(BaseModel):
    items: List[FillItem] = Field(..., max_length=1000)


@router.post("/fill")
def fill(data: FillIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """MAC/Hostname an bekannte IPs übernehmen (auch: neue MAC bei Abweichung)."""
    n = 0
    for it in data.items:
        row = get_or_404(conn, "ip", it.ip_id)
        parts, sets, args = [], [], []
        if it.mac:
            sets.append("mac = ?")
            args.append(it.mac.upper())
            parts.append(f"MAC: {row['mac'] or '–'} → {it.mac.upper()}")
        if it.hostname:
            sets.append("hostname = ?")
            args.append(it.hostname.strip())
            parts.append(f"Hostname: {row['hostname'] or '–'} → {it.hostname.strip()}")
        if not sets:
            continue
        conn.execute(f"UPDATE ip_addresses SET {', '.join(sets)}, updated_at = ? WHERE id = ?", args + [now_utc_str(), it.ip_id])
        if row["device_id"]:
            d = get_or_404(conn, "device", row["device_id"])
            log(conn, admin, "doc_updated", "device", d["id"], d["name"], f"IP {row['ip']}: {'; '.join(parts)} (Netzwerk-Scan)")
        n += 1
    return {"updated": n}


class IgnoreIn(BaseModel):
    keys: List[str] = Field(..., max_length=1000)


@router.post("/ignore")
def ignore(data: IgnoreIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    for k in data.keys:
        if not k.startswith(("new:ip:", "new:mac:", "mac:")) or len(k) > 100:
            raise HTTPException(400, "Ungültiger Eintrag")
        conn.execute("INSERT OR IGNORE INTO scan_ignore(key, created_by, created_at) VALUES (?, ?, ?)", (k, admin["id"], now_utc_str()))
    return {"ok": True}


@router.delete("/ignore")
def clear_ignore(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    n = conn.execute("DELETE FROM scan_ignore").rowcount
    audit(conn, admin["id"], "settings_updated", "scan", f"Ignorierliste geleert ({n} Einträge)")
    return {"removed": n}
