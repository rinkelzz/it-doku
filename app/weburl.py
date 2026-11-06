"""Web-Adressen: von Hand gepflegt pro Gerät, sonst automatisch aus Hostname/IP und den vom Netzwerk-Scan gefundenen
Web-Ports. Nur http:// und https:// – nichts, was im Browser Code ausführen könnte (javascript:, data: …)."""
import re
import sqlite3
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException

# Reihenfolge = Vorliebe: verschlüsselt vor unverschlüsselt, Standardports zuerst
WEB_PORTS = [(443, "https"), (8443, "https"), (5001, "https"), (8006, "https"), (9443, "https"),
             (80, "http"), (8080, "http"), (8123, "http"), (5000, "http")]


def clean(url: str) -> str:
    """Eingabe prüfen; „vault.kunde.de“ wird zu „https://vault.kunde.de“."""
    url = (url or "").strip()
    if not url:
        raise HTTPException(400, "Bitte eine Adresse angeben")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    p = urlsplit(url)
    if p.scheme.lower() not in ("http", "https") or not p.hostname or re.search(r"\s", url):
        raise HTTPException(400, "Nur Adressen mit http:// oder https:// sind erlaubt")
    try:
        p.port  # noqa: B018 – wirft bei ungültigem Port
    except ValueError:
        raise HTTPException(400, "Ungültiger Port in der Adresse")
    return url[:500]


def auto_url(ip: str, hostname: str, ports: str) -> str:
    """Aus Scan-Ergebnis eine Adresse bauen. Hostname nur, wenn er voll qualifiziert aussieht (sonst kennt ihn der
    Browser oft nicht); sonst die IP."""
    found = {int(p) for p in (ports or "").split(",") if p.strip().isdigit()}
    for port, scheme in WEB_PORTS:
        if port in found:
            host = hostname if hostname and "." in hostname and not re.match(r"^[\d.]+$", hostname) else ip
            default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
            return f"{scheme}://{host}" + ("" if default else f":{port}")
    return ""


def latest_ports(conn: sqlite3.Connection, ips: Optional[List[str]] = None) -> Dict[str, str]:
    """Offene Ports je IP aus dem jüngsten Scan, in dem die IP vorkam."""
    sql = ("SELECT h.ip, h.ports FROM scan_hosts h WHERE h.run_id = "
           "(SELECT MAX(h2.run_id) FROM scan_hosts h2 WHERE h2.ip = h.ip)")
    args: list = []
    if ips is not None:
        if not ips:
            return {}
        sql += f" AND h.ip IN ({','.join('?' * len(ips))})"
        args = list(ips)
    return {r["ip"]: r["ports"] for r in conn.execute(sql, args)}


def device_urls(conn: sqlite3.Connection, device_ids: List[int]) -> Dict[int, List[dict]]:
    out: Dict[int, List[dict]] = {}
    if not device_ids:
        return out
    for r in conn.execute(f"SELECT id, device_id, label, url FROM device_urls WHERE device_id IN ({','.join('?' * len(device_ids))}) "
                          "ORDER BY sort, id", device_ids):
        out.setdefault(r["device_id"], []).append({"id": r["id"], "label": r["label"], "url": r["url"]})
    return out
