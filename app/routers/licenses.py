"""Lizenzen, Abos, Wartungsverträge, Domains und Zertifikate – alles mit Ablaufdatum an einer Stelle."""
import sqlite3
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_db
from ..doku import (LICENSE_KINDS, attachments, days_until, delete_attachments, diff, get_or_404, history, insert_row, log,
                    strip_strings, update_row)
from ..security import admin_user, current_user
from ..timeutil import today_local

router = APIRouter(prefix="/api/v1", tags=["Lizenzen"])


class LicenseIn(BaseModel):
    kind: Optional[str] = Field(None, description=", ".join(LICENSE_KINDS))
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    vendor: Optional[str] = Field(None, max_length=150)
    term: Optional[str] = Field(None, max_length=100, description="z. B. „Abo, jährlich“, „Kauf“, „OEM“")
    seats: Optional[int] = Field(None, ge=0, le=1_000_000, description="leer = unbegrenzt/nicht gezählt")
    seats_used: Optional[int] = Field(None, ge=0, le=1_000_000, description="leer = zugeordnete Geräte zählen")
    expires_on: Optional[date] = None
    contract_ref: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=10000)


LABELS = {"kind": "Art", "name": "Name", "vendor": "Hersteller/Anbieter", "term": "Laufzeit", "seats": "Plätze",
          "seats_used": "Genutzt", "expires_on": "Läuft ab", "contract_ref": "Vertrag/Kd.-Nr.", "notes": "Notizen"}


def _out(conn, r) -> dict:
    out = dict(r)
    out["kind_label"] = LICENSE_KINDS.get(r["kind"], r["kind"])
    out["assigned"] = conn.execute("SELECT COUNT(*) FROM license_devices WHERE license_id = ?", (r["id"],)).fetchone()[0]
    out["used"] = r["seats_used"] if r["seats_used"] is not None else out["assigned"]
    out["days"] = days_until(r["expires_on"])
    return out


@router.get("/licenses")
def list_licenses(filter: Optional[str] = Query(None, description="due (läuft in 90 Tagen ab) oder expired"),
                  kind: Optional[str] = None, q: Optional[str] = Query(None, max_length=100),
                  user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    sql, args = "SELECT * FROM licenses WHERE 1 = 1", []
    today = today_local().isoformat()
    if filter == "expired":
        sql += " AND expires_on < ?"
        args.append(today)
    elif filter == "due":
        from datetime import timedelta
        sql += " AND expires_on >= ? AND expires_on <= ?"
        args += [today, (today_local() + timedelta(days=90)).isoformat()]
    if kind in LICENSE_KINDS:
        sql += " AND kind = ?"
        args.append(kind)
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (name LIKE ? OR vendor LIKE ? OR contract_ref LIKE ? OR term LIKE ?)"
        args += [like] * 4
    rows = [_out(conn, r) for r in conn.execute(sql + " ORDER BY name COLLATE NOCASE", args)]
    return rows


@router.get("/licenses/counts")
def license_counts(user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    from datetime import timedelta
    today = today_local()
    t, d = today.isoformat(), (today + timedelta(days=90)).isoformat()
    return {"all": conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0],
            "due": conn.execute("SELECT COUNT(*) FROM licenses WHERE expires_on >= ? AND expires_on <= ?", (t, d)).fetchone()[0],
            "expired": conn.execute("SELECT COUNT(*) FROM licenses WHERE expires_on < ?", (t,)).fetchone()[0]}


def license_detail(conn, license_id: int) -> dict:
    out = _out(conn, get_or_404(conn, "license", license_id))
    out["devices"] = [dict(r) for r in conn.execute(
        "SELECT d.id, d.name, t.icon, d.status FROM devices d JOIN license_devices ld ON ld.device_id = d.id "
        "JOIN device_types t ON t.id = d.type_id WHERE ld.license_id = ? ORDER BY d.name COLLATE NOCASE", (license_id,))]
    out["files"] = attachments(conn, "license", license_id)
    out["history"] = history(conn, "license", license_id)
    return out


@router.get("/licenses/{license_id}")
def get_license(license_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return license_detail(conn, license_id)


def _check(values: dict) -> dict:
    if "kind" in values and values["kind"] not in LICENSE_KINDS:
        raise HTTPException(400, "Unbekannte Art – erlaubt: " + ", ".join(LICENSE_KINDS))
    return values


@router.post("/licenses", status_code=201)
def create_license(data: LicenseIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    values = _check(strip_strings(data.model_dump(exclude_unset=True)))
    if not values.get("name"):
        raise HTTPException(400, "Bitte einen Namen angeben")
    lid = insert_row(conn, "licenses", values)
    log(conn, admin, "doc_created", "license", lid, values["name"])
    return license_detail(conn, lid)


@router.patch("/licenses/{license_id}")
def update_license(license_id: int, data: LicenseIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "license", license_id)
    values = _check(strip_strings(data.model_dump(exclude_unset=True)))
    if "name" in values and not values["name"]:
        raise HTTPException(400, "Der Name darf nicht leer sein")
    shown = dict(values)
    o = dict(old)
    if "kind" in shown:
        shown["kind"], o["kind"] = LICENSE_KINDS[shown["kind"]], LICENSE_KINDS.get(o["kind"], o["kind"])
    text = diff(o, shown, LABELS)
    update_row(conn, "licenses", license_id, values)
    if text:
        log(conn, admin, "doc_updated", "license", license_id, values.get("name") or old["name"], text)
    return license_detail(conn, license_id)


@router.delete("/licenses/{license_id}")
def delete_license(license_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "license", license_id)
    conn.execute("DELETE FROM licenses WHERE id = ?", (license_id,))
    delete_attachments(conn, "license", license_id)
    log(conn, admin, "doc_deleted", "license", license_id, old["name"])
    return {"ok": True}


class AssignIn(BaseModel):
    device_id: int


@router.post("/licenses/{license_id}/devices")
def assign(license_id: int, data: AssignIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    lic = get_or_404(conn, "license", license_id)
    dev = get_or_404(conn, "device", data.device_id)
    if conn.execute("SELECT 1 FROM license_devices WHERE license_id = ? AND device_id = ?", (license_id, dev["id"])).fetchone():
        raise HTTPException(409, "Die Lizenz ist diesem Gerät schon zugeordnet")
    conn.execute("INSERT INTO license_devices(license_id, device_id) VALUES (?, ?)", (license_id, dev["id"]))
    log(conn, admin, "doc_updated", "license", license_id, lic["name"], f"zugeordnet: {dev['name']}")
    log(conn, admin, "doc_updated", "device", dev["id"], dev["name"], f"Lizenz {lic['name']} zugeordnet")
    return license_detail(conn, license_id)


@router.delete("/licenses/{license_id}/devices/{device_id}")
def unassign(license_id: int, device_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    lic = get_or_404(conn, "license", license_id)
    dev = get_or_404(conn, "device", device_id)
    conn.execute("DELETE FROM license_devices WHERE license_id = ? AND device_id = ?", (license_id, device_id))
    log(conn, admin, "doc_updated", "license", license_id, lic["name"], f"Zuordnung entfernt: {dev['name']}")
    log(conn, admin, "doc_updated", "device", device_id, dev["name"], f"Lizenz {lic['name']} entfernt")
    return license_detail(conn, license_id)
