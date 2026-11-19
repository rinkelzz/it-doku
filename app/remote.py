"""Fernwartung: TeamViewer-, AnyDesk-, RustDesk- und andere Kennungen pro Gerät – von Hand oder vom Agent gemeldet.

Kennwörter werden hier bewusst nicht gespeichert (dafür gibt es die Zugangsdaten im Tresor), und der Agent liest
keine aus. Verbinden-Links werden nur aus geprüften Kennungen gebaut (keine frei eingegebenen URLs/Schemata).
"""
import re
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

TOOLS = {"teamviewer": "TeamViewer", "anydesk": "AnyDesk", "rustdesk": "RustDesk", "other": "Andere"}
ICONS = {"teamviewer": "🟦", "anydesk": "🟥", "rustdesk": "🦀", "other": "🖧"}


def clean_id(tool: str, value: Any) -> str:
    """Kennung prüfen und vereinheitlichen; leer = ungültig."""
    v = str(value or "").strip()
    if tool in ("teamviewer", "anydesk", "rustdesk"):
        digits = re.sub(r"[\s-]", "", v)
        if re.fullmatch(r"\d{6,12}", digits):
            return digits
        if tool == "anydesk" and re.fullmatch(r"[A-Za-z0-9._-]{1,50}@[A-Za-z0-9_-]{1,30}", v):
            return v  # AnyDesk-Alias, z. B. praxis-pc@ad
        if tool == "rustdesk" and re.fullmatch(r"[A-Za-z0-9_-]{6,32}", v):
            return v  # eigene RustDesk-Kennung
        return ""
    v = re.sub(r"[\x00-\x1f\x7f]", "", v)
    return v[:100]


def pretty(tool: str, rid: str) -> str:
    """123456789 → „123 456 789“ (wie TeamViewer/AnyDesk sie anzeigen)."""
    if tool in ("teamviewer", "anydesk", "rustdesk") and rid.isdigit():
        return " ".join(rid[max(0, i - 3):i] for i in range(len(rid), 0, -3)[::-1])
    return rid


def connect_url(tool: str, rid: str) -> str:
    """Link zum Verbinden – nur für die drei bekannten Programme, nur aus einer geprüften Kennung."""
    if not rid or clean_id(tool, rid) != rid:
        return ""
    if tool == "teamviewer":
        return "https://start.teamviewer.com/" + rid
    if tool == "anydesk":
        return "anydesk:" + quote(rid, safe="@._-")
    if tool == "rustdesk":
        return "rustdesk://" + quote(rid, safe="_-")
    return ""


def out(r: sqlite3.Row) -> Dict[str, Any]:
    tool = r["tool"]
    return {"id": r["id"], "device_id": r["device_id"], "tool": tool,
            "tool_label": r["label"] if tool == "other" and r["label"] else TOOLS.get(tool, tool),
            "icon": ICONS.get(tool, "🖧"), "label": r["label"], "remote_id": r["remote_id"],
            "display": pretty(tool, r["remote_id"]), "url": connect_url(tool, r["remote_id"]), "note": r["note"],
            "source": r["source"], "version": r["version"]}


def for_devices(conn: sqlite3.Connection, ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    res: Dict[int, List[Dict[str, Any]]] = {}
    if not ids:
        return res
    for r in conn.execute(f"SELECT * FROM device_remote WHERE device_id IN ({','.join('?' * len(ids))}) "
                          "ORDER BY CASE tool WHEN 'other' THEN 1 ELSE 0 END, tool, id", ids):
        res.setdefault(r["device_id"], []).append(out(r))
    return res


def validate(tool: str, label: Optional[str], rid: str) -> Dict[str, str]:
    if tool not in TOOLS:
        raise HTTPException(400, "Unbekanntes Programm")
    label = (label or "").strip()[:60]
    if tool == "other" and not label:
        raise HTTPException(400, "Bitte den Namen des Programms angeben (z. B. Splashtop, RDP)")
    cid = clean_id(tool, rid)
    if not cid:
        hint = {"teamviewer": "TeamViewer-IDs bestehen aus 9–10 Ziffern",
                "anydesk": "AnyDesk-IDs bestehen aus 9–10 Ziffern oder einem Alias wie name@ad",
                "rustdesk": "RustDesk-IDs bestehen aus Ziffern oder Buchstaben"}.get(tool, "Bitte eine Kennung angeben")
        raise HTTPException(400, hint)
    return {"tool": tool, "label": label if tool == "other" else "", "remote_id": cid}


# --- vom Agent ----------------------------------------------------------------

def sanitize(raw: Any) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return found
    for x in raw[:20]:
        if not isinstance(x, dict):
            continue
        tool = str(x.get("tool") or "").lower()
        if tool not in ("teamviewer", "anydesk", "rustdesk"):
            continue
        rid = clean_id(tool, x.get("id"))
        if not rid or any(f["tool"] == tool and f["remote_id"] == rid for f in found):
            continue
        found.append({"tool": tool, "remote_id": rid, "version": str(x.get("version") or "")[:40],
                      "note": re.sub(r"[\x00-\x1f\x7f]", "", str(x.get("note") or ""))[:150]})
    return found


def sync_from_agent(conn: sqlite3.Connection, agent_id: int, device: sqlite3.Row, found: List[Dict[str, str]]) -> None:
    """Agent-Einträge des Geräts abgleichen: neue anlegen, Version/Hinweis nachziehen, nicht mehr gemeldete entfernen.
    Von Hand angelegte Einträge bleiben unangetastet (gleiche Kennung von Hand → kein zweiter Eintrag)."""
    from .doku import log
    from .timeutil import now_utc_str
    now = now_utc_str()
    existing = conn.execute("SELECT * FROM device_remote WHERE device_id = ?", (device["id"],)).fetchall()
    keep = set()
    for f in found:
        same = [e for e in existing if e["tool"] == f["tool"] and e["remote_id"] == f["remote_id"]]
        if same:
            e = same[0]
            keep.add(e["id"])
            if e["source"] == "agent" and (e["version"] != f["version"] or e["note"] != f["note"]):
                conn.execute("UPDATE device_remote SET version = ?, note = ?, updated_at = ? WHERE id = ?",
                             (f["version"], f["note"], now, e["id"]))
            continue
        conn.execute("INSERT INTO device_remote(device_id, tool, label, remote_id, note, version, source, agent_id, created_at) "
                     "VALUES (?, ?, '', ?, ?, ?, 'agent', ?, ?)",
                     (device["id"], f["tool"], f["remote_id"], f["note"], f["version"], agent_id, now))
        log(conn, None, "doc_updated", "device", device["id"], device["name"],
            f"Fernwartung vom Agent: {TOOLS[f['tool']]} {pretty(f['tool'], f['remote_id'])}")
    for e in existing:
        if e["source"] == "agent" and e["id"] not in keep:
            conn.execute("DELETE FROM device_remote WHERE id = ?", (e["id"],))
            log(conn, None, "doc_updated", "device", device["id"], device["name"],
                f"Fernwartung entfernt (nicht mehr installiert): {TOOLS.get(e['tool'], e['tool'])} {pretty(e['tool'], e['remote_id'])}")
