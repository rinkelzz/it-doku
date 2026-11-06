"""Ansprechpartner: Personen beim Kunden und externe Dienstleister, mit Notfall-Markierung."""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_db
from ..doku import attachments, delete_attachments, diff, get_or_404, history, insert_row, log, strip_strings, update_row
from ..mailer import valid_email
from ..security import admin_user, current_user

router = APIRouter(prefix="/api/v1", tags=["Ansprechpartner"])

S = Field(None, max_length=200)


class ContactIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    company: Optional[str] = S
    role: Optional[str] = S
    phone: Optional[str] = Field(None, max_length=60)
    mobile: Optional[str] = Field(None, max_length=60)
    email: Optional[str] = S
    website: Optional[str] = S
    customer_no: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=10000)
    external: Optional[bool] = None
    emergency: Optional[bool] = None
    site_id: Optional[int] = None


LABELS = {"name": "Name", "company": "Firma", "role": "Rolle", "phone": "Telefon", "mobile": "Mobil", "email": "E-Mail",
          "website": "Webseite", "customer_no": "Kundennummer", "notes": "Notizen", "external": "Extern",
          "emergency": "Notfall", "site_id": "Standort"}


def _out(r) -> dict:
    out = dict(r)
    out["external"], out["emergency"] = bool(r["external"]), bool(r["emergency"])
    return out


def _check(conn, values: dict) -> dict:
    if values.get("email") and not valid_email(values["email"]):
        raise HTTPException(400, "Ungültige E-Mail-Adresse")
    if values.get("site_id"):
        get_or_404(conn, "site", values["site_id"])
    return values


@router.get("/contacts")
def list_contacts(filter: Optional[str] = Query(None, description="internal, external oder emergency"),
                  q: Optional[str] = Query(None, max_length=100),
                  user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    sql, args = "SELECT * FROM contacts WHERE 1 = 1", []
    if filter == "internal":
        sql += " AND external = 0"
    elif filter == "external":
        sql += " AND external = 1"
    elif filter == "emergency":
        sql += " AND emergency = 1"
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (name LIKE ? OR company LIKE ? OR role LIKE ? OR phone LIKE ? OR mobile LIKE ? OR email LIKE ? OR customer_no LIKE ?)"
        args += [like] * 7
    return [_out(r) for r in conn.execute(sql + " ORDER BY emergency DESC, name COLLATE NOCASE", args)]


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    out = _out(get_or_404(conn, "contact", contact_id))
    out["files"] = attachments(conn, "contact", contact_id)
    out["history"] = history(conn, "contact", contact_id)
    return out


@router.post("/contacts", status_code=201)
def create_contact(data: ContactIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    values = _check(conn, strip_strings(data.model_dump(exclude_unset=True)))
    if not values.get("name"):
        raise HTTPException(400, "Bitte einen Namen angeben")
    cid = insert_row(conn, "contacts", values)
    log(conn, admin, "doc_created", "contact", cid, values["name"])
    return get_contact(cid, admin, conn)


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, data: ContactIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "contact", contact_id)
    values = _check(conn, strip_strings(data.model_dump(exclude_unset=True)))
    if "name" in values and not values["name"]:
        raise HTTPException(400, "Der Name darf nicht leer sein")
    text = diff(old, values, LABELS)
    update_row(conn, "contacts", contact_id, values)
    if text:
        log(conn, admin, "doc_updated", "contact", contact_id, values.get("name") or old["name"], text)
    return get_contact(contact_id, admin, conn)


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    old = get_or_404(conn, "contact", contact_id)
    conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    delete_attachments(conn, "contact", contact_id)
    log(conn, admin, "doc_deleted", "contact", contact_id, old["name"])
    return {"ok": True}
