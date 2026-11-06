"""Anhänge (Rechnungen, Fotos, Netzwerkplan) – PNG, JPG oder PDF, bis 10 MB, in der Datenbank gespeichert."""
import re
import sqlite3
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from ..db import get_db
from ..doku import KINDS, get_or_404, log
from ..security import admin_user, current_user
from ..timeutil import now_utc_str

router = APIRouter(prefix="/api/v1", tags=["Anhänge"])

MAX_BYTES = 10 * 1024 * 1024
OWNER_TYPES = ("device", "license", "contact", "site", "network")
ROLES = ("file", "diagram")


def sniff(head: bytes) -> Optional[str]:
    """Dateityp am Inhalt erkennen – die Dateiendung zählt nicht."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def safe_name(name: str, mime: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", (name or "").strip())[:150].strip(" .") or "datei"
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "application/pdf": ".pdf"}[mime]
    if not name.lower().endswith((ext, ".jpeg") if ext == ".jpg" else ext):
        name += ext
    return name


@router.post("/attachments", status_code=201)
async def upload(request: Request,
                 owner_type: str = Query(..., description=", ".join(OWNER_TYPES)),
                 owner_id: int = Query(...),
                 role: str = Query("file", description="file oder diagram (Netzwerkplan, nur bei Standorten)"),
                 name: str = Query(..., max_length=300),
                 admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Datei als Rohdaten im Body hochladen (Content-Type egal, erkannt wird am Inhalt)."""
    if owner_type not in OWNER_TYPES or role not in ROLES:
        raise HTTPException(400, "Unbekannte Zuordnung")
    if role == "diagram" and owner_type != "site":
        raise HTTPException(400, "Ein Netzwerkplan gehört zu einem Standort")
    owner = get_or_404(conn, owner_type, owner_id)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BYTES:
        raise HTTPException(413, "Die Datei ist zu groß (höchstens 10 MB)")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, "Die Datei ist zu groß (höchstens 10 MB)")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(400, "Die Datei ist leer")
    mime = sniff(data[:16])
    if not mime:
        raise HTTPException(400, "Erlaubt sind nur PNG, JPG und PDF")
    fname = safe_name(name, mime)
    if role == "diagram":
        conn.execute("DELETE FROM attachments WHERE owner_type = 'site' AND owner_id = ? AND role = 'diagram'", (owner_id,))
    cur = conn.execute("INSERT INTO attachments(owner_type, owner_id, role, name, mime, size, data, created_by, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (owner_type, owner_id, role, fname, mime, len(data), data, admin["id"], now_utc_str()))
    what = "Netzwerkplan hochgeladen" if role == "diagram" else "Anhang hinzugefügt"
    log(conn, admin, "file_added", owner_type, owner_id, owner["name"], f"{what}: {fname}")
    return {"id": cur.lastrowid, "name": fname, "mime": mime, "size": len(data)}


@router.get("/attachments/{att_id}")
def download(att_id: int, inline: bool = False, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    r = conn.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Anhang nicht gefunden")
    disp = "inline" if inline and r["mime"].startswith("image/") else "attachment"
    return Response(bytes(r["data"]), media_type=r["mime"], headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(r['name'])}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'",
        "Cache-Control": "private, max-age=3600",
    })


@router.delete("/attachments/{att_id}")
def delete(att_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    r = conn.execute("SELECT id, owner_type, owner_id, role, name FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Anhang nicht gefunden")
    conn.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
    if r["owner_type"] in KINDS:
        owner = conn.execute(f"SELECT name FROM {KINDS[r['owner_type']][0]} WHERE id = ?", (r["owner_id"],)).fetchone()
        what = "Netzwerkplan entfernt" if r["role"] == "diagram" else "Anhang gelöscht"
        log(conn, admin, "file_deleted", r["owner_type"], r["owner_id"], owner[0] if owner else "?", f"{what}: {r['name']}")
    return {"ok": True}
