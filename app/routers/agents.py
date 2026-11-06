"""Agenten: Bericht empfangen (ohne Login, mit Agent-Schlüssel), verwalten, Skripte ausliefern, Bericht am Gerät."""
import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import agents
from ..csvsafe import row as safe_row
from ..db import audit, get_db, get_setting, set_setting
from ..doku import get_or_404
from ..dsm_auth import clear_failures, note_failure, too_many_attempts
from ..security import admin_user, current_user
from ..config import settings
from ..timeutil import local_iso, now_utc_str

router = APIRouter(tags=["Agenten"])

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
SCRIPTS = {"itdoku-agent.ps1": "windows", "itdoku-agent.py": "linux/macos"}
MAX_FAILS_AGENT = 20


# --- Empfang (Agent) ---------------------------------------------------------

async def _read_body(request: Request) -> bytes:
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > agents.MAX_BODY:
        raise HTTPException(413, "Bericht zu groß")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > agents.MAX_BODY:
            raise HTTPException(413, "Bericht zu groß")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/agent/v1/report", include_in_schema=False)
async def report(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    ip = request.client.host if request.client else ""
    key = "agent:" + ip
    if too_many_attempts(key, MAX_FAILS_AGENT):
        raise HTTPException(429, "Zu viele ungültige Schlüssel – bitte später erneut versuchen")
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    agent = agents.find_by_token(conn, token) if token else None
    if not agent:
        note_failure(key)
        raise HTTPException(401, "Unbekannter Agent-Schlüssel")
    clear_failures(key)
    if agent["disabled"]:
        raise HTTPException(403, "Dieser Agent ist gesperrt")
    body = await _read_body(request)
    try:
        raw = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "Bericht ist kein gültiges JSON")
    if not isinstance(raw, dict):
        raise HTTPException(400, "Bericht ist kein JSON-Objekt")
    rep = agents.sanitize(raw)
    res = agents.store_report(conn, agent, rep, ip)
    return {"ok": True, "device_id": res["device_id"], "created": res["created"]}


@router.get("/agent/{name}", include_in_schema=False)
def script(name: str):
    """Agent-Skripte zum Herunterladen (enthalten keine Geheimnisse – den Schlüssel gibt es nur beim Einrichten)."""
    if name not in SCRIPTS:
        raise HTTPException(404, "Nicht gefunden")
    data = (AGENT_DIR / name).read_bytes()
    return Response(content=data, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-cache",
                             "X-Content-Type-Options": "nosniff"})


# --- Verwaltung --------------------------------------------------------------

def _agent_out(conn, r, days: int) -> dict:
    rep = json.loads(r["report"]) if r["report"] else None
    out = {k: r[k] for k in ("id", "name", "platform", "device_id", "token_hint", "last_ip", "agent_version", "hostname",
                             "os_name", "last_report_at", "created_at")}
    out["disabled"] = bool(r["disabled"])
    out["platform_label"] = agents.PLATFORMS.get(r["platform"], "")
    out["last_report_local"] = local_iso(r["last_report_at"]) if r["last_report_at"] else None
    out["stale"] = not r["disabled"] and agents.is_stale(r["last_report_at"], days)
    out["device_name"] = r["device_name"] if "device_name" in r.keys() else None
    out["device_icon"] = r["device_icon"] if "device_icon" in r.keys() else None
    out["problems"] = agents.problems(rep) if rep else None
    return out


SELECT = ("SELECT a.*, d.name AS device_name, t.icon AS device_icon FROM agents a LEFT JOIN devices d ON d.id = a.device_id "
          "LEFT JOIN device_types t ON t.id = d.type_id")


def _agent_url(conn, request: Request) -> str:
    url = (get_setting(conn, "agent_url") or get_setting(conn, "public_url") or settings.public_url or "").strip().rstrip("/")
    if not url:
        url = str(request.base_url).rstrip("/")
    return url


@router.get("/api/v1/agents")
def list_agents(request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    days = agents.stale_days(conn)
    return {"agents": [_agent_out(conn, r, days) for r in conn.execute(SELECT + " ORDER BY a.name COLLATE NOCASE")],
            "settings": {"agent_url": get_setting(conn, "agent_url"), "suggested_url": _agent_url(conn, request),
                         "stale_days": days, "port": settings.port}}


class AgentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    platform: Optional[str] = Field("", max_length=20)
    device_id: Optional[int] = None


def _check_device(conn, device_id: Optional[int], agent_id: Optional[int] = None) -> None:
    if device_id is None:
        return
    get_or_404(conn, "device", device_id)
    other = conn.execute("SELECT name FROM agents WHERE device_id = ? AND id IS NOT ?", (device_id, agent_id)).fetchone()
    if other:
        raise HTTPException(409, f"Das Gerät hat schon den Agent „{other['name']}“")


@router.post("/api/v1/agents", status_code=201)
def create_agent(data: AgentIn, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    _check_device(conn, data.device_id)
    platform = data.platform if data.platform in agents.PLATFORMS else ""
    token = agents.new_token()
    cur = conn.execute(
        "INSERT INTO agents(name, platform, device_id, token_hash, token_hint, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data.name.strip(), platform, data.device_id, agents.token_hash(token), agents.hint(token), admin["id"], now_utc_str()))
    audit(conn, admin["id"], "agent_created", f"agent:{cur.lastrowid}", data.name.strip())
    return {"id": cur.lastrowid, "token": token, "url": _agent_url(conn, request)}


@router.post("/api/v1/agents/{agent_id}/token")
def renew_token(agent_id: int, request: Request, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    a = _get(conn, agent_id)
    token = agents.new_token()
    conn.execute("UPDATE agents SET token_hash = ?, token_hint = ?, updated_at = ? WHERE id = ?",
                 (agents.token_hash(token), agents.hint(token), now_utc_str(), agent_id))
    audit(conn, admin["id"], "agent_token", f"agent:{agent_id}", f"{a['name']}: neuer Schlüssel (alter ungültig)")
    return {"id": agent_id, "token": token, "url": _agent_url(conn, request)}


class AgentPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    disabled: Optional[bool] = None
    device_id: Optional[int] = None


@router.patch("/api/v1/agents/{agent_id}")
def update_agent(agent_id: int, data: AgentPatch, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    a = _get(conn, agent_id)
    values = data.model_dump(exclude_unset=True)
    parts = []
    if "device_id" in values:
        _check_device(conn, values["device_id"], agent_id)
        parts.append("Gerät geändert")
    if values.get("name"):
        values["name"] = values["name"].strip()
        parts.append(f"Name: {a['name']} → {values['name']}")
    if "disabled" in values:
        values["disabled"] = int(bool(values["disabled"]))
        parts.append("gesperrt" if values["disabled"] else "entsperrt")
    if values:
        conn.execute(f"UPDATE agents SET {', '.join(k + ' = ?' for k in values)}, updated_at = ? WHERE id = ?",
                     list(values.values()) + [now_utc_str(), agent_id])
        audit(conn, admin["id"], "agent_updated", f"agent:{agent_id}", f"{a['name']}: {'; '.join(parts)}")
    return {"ok": True}


@router.delete("/api/v1/agents/{agent_id}")
def delete_agent(agent_id: int, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    a = _get(conn, agent_id)
    conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    audit(conn, admin["id"], "agent_deleted", f"agent:{agent_id}", f"{a['name']} (das Gerät bleibt in der Doku)")
    return {"ok": True}


class AgentSettings(BaseModel):
    agent_url: Optional[str] = Field(None, max_length=300)
    stale_days: Optional[int] = Field(None, ge=1, le=60)


@router.patch("/api/v1/agents-settings")
def agent_settings(data: AgentSettings, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    if data.agent_url is not None:
        url = data.agent_url.strip().rstrip("/")
        if url and not url.lower().startswith(("https://", "http://")):
            raise HTTPException(400, "Die Adresse muss mit https:// (oder intern http://) beginnen")
        set_setting(conn, "agent_url", url)
    if data.stale_days is not None:
        set_setting(conn, "agent_stale_days", str(data.stale_days))
    audit(conn, admin["id"], "settings_updated", "agents", f"Agenten: {data.model_dump(exclude_unset=True)}")
    return {"ok": True}


def _get(conn, agent_id: int) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Agent nicht gefunden")
    return r


# --- Bericht am Gerät --------------------------------------------------------

@router.get("/api/v1/devices/{device_id}/agent")
def device_report(device_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    get_or_404(conn, "device", device_id)
    r = conn.execute(SELECT + " WHERE a.device_id = ?", (device_id,)).fetchone()
    if not r:
        return {"agent": None}
    out = _agent_out(conn, r, agents.stale_days(conn))
    if not user["is_admin"]:
        out.pop("token_hint", None)
        out.pop("last_ip", None)
    rep = json.loads(r["report"]) if r["report"] else None
    if rep and rep.get("boot_time"):
        rep["boot_time_local"] = local_iso(rep["boot_time"]) if "T" in rep["boot_time"] else rep["boot_time"]
    return {"agent": out, "report": rep}


@router.get("/api/v1/devices/{device_id}/agent/software.csv")
def software_csv(device_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    d = get_or_404(conn, "device", device_id)
    r = conn.execute("SELECT report FROM agents WHERE device_id = ?", (device_id,)).fetchone()
    if not r or not r["report"]:
        raise HTTPException(404, "Kein Agent-Bericht vorhanden")
    rep = json.loads(r["report"])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Name", "Version", "Hersteller", "Installiert am"])
    for p in rep.get("software", []):
        w.writerow(safe_row([p["name"], p["version"], p["publisher"], p.get("installed_on", "")]))
    audit(conn, user["id"], "export_csv", "devices", f"Software-Liste {d['name']}, {len(rep.get('software', []))} Einträge")
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="software.csv"'})
