"""Übersicht (Zahlen, Fristen, Notfall-Kontakte, zuletzt geändert) und globale Suche."""
import re
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from ..db import audit, get_db
from ..doku import DOC_ACTIONS, KINDS, due_items
from ..security import current_user
from ..timeutil import local_iso
from .network import list_networks, list_sites

router = APIRouter(prefix="/api/v1", tags=["Übersicht & Suche"])


def recent_changes(conn: sqlite3.Connection, limit: int = 8, with_credentials: bool = False) -> list:
    acts = list(DOC_ACTIONS)
    rows = conn.execute(
        f"SELECT a.ts, a.action, a.target, a.details, u.display_name AS actor FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id "
        f"WHERE a.action IN ({','.join('?' * len(acts))}) AND a.target NOT LIKE 'ip:%' AND a.target NOT LIKE 'type:%' "
        f"{'' if with_credentials else ' AND a.target NOT LIKE ' + chr(39) + 'credential:%' + chr(39)} "
        f"ORDER BY a.id DESC LIMIT ?", acts + [limit]).fetchall()
    out = []
    for r in rows:
        kind, _, sid = (r["target"] or "").partition(":")
        name, _, text = (r["details"] or "").partition(" – ")
        exists = False
        if kind in KINDS and sid.isdigit():
            exists = bool(conn.execute(f"SELECT 1 FROM {KINDS[kind][0]} WHERE id = ?", (int(sid),)).fetchone())
        out.append({"ts_local": local_iso(r["ts"]), "actor": r["actor"] or "System", "kind": kind,
                    "id": int(sid) if sid.isdigit() else None, "icon": KINDS.get(kind, ("", "", "•"))[2],
                    "name": name, "label": DOC_ACTIONS.get(r["action"], ""), "text": text, "exists": exists})
    return out


def _scan_new(conn) -> int:
    from .. import netscan
    try:
        return len(netscan.results(conn)["new"])
    except Exception:  # noqa: BLE001 – Übersicht soll nie am Scan scheitern
        return 0


def _agents_stale(conn) -> list:
    from .. import agents
    try:
        return [{"id": a["id"], "name": a["name"], "device_id": a["device_id"], "device_name": a["device_name"],
                 "last_report_at": a["last_report_at"]} for a in agents.stale_agents(conn)]
    except Exception:  # noqa: BLE001
        return []


@router.get("/overview")
def overview(site_id: Optional[int] = None, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    def one(sql, args=()):
        return conn.execute(sql, args).fetchone()[0]
    dw, da = (" AND site_id = ?", [site_id]) if site_id else ("", [])
    nets = list_networks(site_id=site_id, user=user, conn=conn)
    due = due_items(conn, site_id)
    return {
        "devices": one("SELECT COUNT(*) FROM devices WHERE status != 'retired'" + dw, da),
        "devices_stock": one("SELECT COUNT(*) FROM devices WHERE status = 'stock'" + dw, da),
        "licenses": one("SELECT COUNT(*) FROM licenses"),
        "licenses_due": sum(1 for d in due if d["kind"] == "license"),
        "networks": len(nets),
        "ips_used": sum(n["used"] for n in nets),
        "contacts": one("SELECT COUNT(*) FROM contacts"),
        "contacts_external": one("SELECT COUNT(*) FROM contacts WHERE external = 1"),
        "due": due,
        "emergency": [dict(r) for r in conn.execute(
            "SELECT id, name, company, role, phone, mobile, external FROM contacts WHERE emergency = 1 "
            "ORDER BY external, name COLLATE NOCASE")],
        "sites": list_sites(user=user, conn=conn),
        "recent": recent_changes(conn, with_credentials=bool(user["is_admin"])),
        "scan_new": _scan_new(conn) if user["is_admin"] else 0,
        "agents_stale": _agents_stale(conn) if user["is_admin"] else [],
    }


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=100), user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Sucht in Geräten, IP-Adressen, Ansprechpartnern, Lizenzen, Netzen und Standorten (je höchstens 8 Treffer)."""
    q = q.strip()
    like = f"%{q}%"
    digits = re.sub(r"\D", "", q)
    out = {}
    out["devices"] = [dict(r) for r in conn.execute(
        "SELECT d.id, d.name, t.icon, d.room, d.model, d.manufacturer, d.serial, d.status, "
        "(SELECT ip FROM ip_addresses WHERE device_id = d.id ORDER BY id LIMIT 1) AS ip "
        "FROM devices d JOIN device_types t ON t.id = d.type_id WHERE d.name LIKE ? OR d.serial LIKE ? OR d.model LIKE ? "
        "OR d.manufacturer LIKE ? OR d.inventory_no LIKE ? OR d.used_by LIKE ? OR d.room LIKE ? OR d.os LIKE ? "
        "ORDER BY d.status = 'retired', d.name COLLATE NOCASE LIMIT 8", [like] * 8)]
    out["ips"] = [dict(r) for r in conn.execute(
        "SELECT i.id, i.ip, i.mac, i.hostname, i.device_id, d.name AS device_name, n.name AS network_name, i.network_id "
        "FROM ip_addresses i LEFT JOIN devices d ON d.id = i.device_id LEFT JOIN networks n ON n.id = i.network_id "
        "WHERE i.ip LIKE ? OR i.mac LIKE ? OR i.hostname LIKE ? LIMIT 8", [like, like.upper(), like])]
    contacts = []
    for r in conn.execute("SELECT id, name, company, role, phone, mobile, email, customer_no, external FROM contacts "
                          "ORDER BY name COLLATE NOCASE"):
        text = " ".join(str(r[k] or "") for k in ("name", "company", "role", "email", "customer_no")).lower()
        phones = re.sub(r"\D", "", (r["phone"] or "") + " " + (r["mobile"] or ""))
        if q.lower() in text or (len(digits) >= 3 and digits in phones):
            contacts.append(dict(r))
        if len(contacts) >= 8:
            break
    out["contacts"] = contacts
    out["licenses"] = [dict(r) for r in conn.execute(
        "SELECT id, name, vendor, kind, expires_on FROM licenses WHERE name LIKE ? OR vendor LIKE ? OR contract_ref LIKE ? "
        "ORDER BY name COLLATE NOCASE LIMIT 8", [like] * 3)]
    out["networks"] = [dict(r) for r in conn.execute(
        "SELECT id, name, cidr, vlan, site_id FROM networks WHERE name LIKE ? OR cidr LIKE ? LIMIT 8", [like, like])]
    out["credentials"] = [dict(r) for r in conn.execute(
        "SELECT id, title, username, url, owner_type, owner_id FROM credentials WHERE title LIKE ? OR username LIKE ? OR url LIKE ? "
        "ORDER BY title COLLATE NOCASE LIMIT 8", [like] * 3)] if user["is_admin"] else []
    out["sites"] = [dict(r) for r in conn.execute(
        "SELECT id, name, address FROM sites WHERE name LIKE ? OR address LIKE ? OR isp_customer_no LIKE ? OR isp_public_ip LIKE ? LIMIT 8",
        [like] * 4)]
    return out


@router.get("/handbook.pdf")
def handbook(site_id: Optional[int] = None, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Notfall-Handbuch als PDF (ohne Passwörter): Notfall-Kontakte, Internet, Netze, IP-Listen, Netzwerkplan."""
    from ..handbook import build
    from ..timeutil import today_local
    pdf = build(conn, site_id)
    audit(conn, user["id"], "handbook_pdf", "handbook", f"Notfall-Handbuch erstellt{' (ein Standort)' if site_id else ''}")
    name = f"notfall-handbuch-{today_local().isoformat()}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
