"""Fristen-Mail: wöchentliche Sammel-Mail zu ablaufenden Lizenzen, Domains, Zertifikaten und Garantien,
dazu je Eintrag eine Erinnerung 14 Tage vorher und am Ablauftag.

Läuft im Hintergrund-Zeitplan. Verschickt wird nur, wenn etwas fällig ist und Empfänger eingetragen sind.
Bereits verschickte Erinnerungen merkt sich die Tabelle deadline_sent (Schlüssel enthält das Datum – wird eine
Lizenz verlängert, gibt es für das neue Datum wieder Erinnerungen).
"""
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .db import audit, get_setting, set_setting
from .doku import due_items
from .mailer import MailError, send_mail, valid_email
from .timeutil import now_utc, now_utc_str, to_local

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MILESTONES = (14, 0)  # Tage vor Ablauf


def recipients(conn: sqlite3.Connection) -> List[str]:
    raw = get_setting(conn, "deadline_recipients") or ""
    return [a for a in (x.strip() for x in raw.replace(";", ",").replace("\n", ",").split(",")) if valid_email(a)]


def config(conn: sqlite3.Connection) -> Dict:
    def num(key, default):
        try:
            return int(get_setting(conn, key) or default)
        except ValueError:
            return default
    return {"enabled": get_setting(conn, "deadline_enabled") == "1", "recipients": recipients(conn),
            "weekday": num("deadline_weekday", 0), "hour": num("deadline_hour", 7), "days": num("deadline_days", 90),
            "last_run": get_setting(conn, "deadline_last_run"), "last_result": get_setting(conn, "deadline_last_result")}


def _de(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


def _when(days: int) -> str:
    if days < 0:
        return f"vor {-days} Tag{'' if days == -1 else 'en'} abgelaufen"
    if days == 0:
        return "läuft heute ab"
    return f"in {days} Tag{'' if days == 1 else 'en'}"


def _line(it: Dict) -> str:
    what = it["what"] + (f", {it['info']}" if it.get("info") else "")
    return f"- {_de(it['date'])} ({_when(it['days'])}) – {it['name']} ({what})"


def _footer(conn) -> str:
    url = get_setting(conn, "public_url")
    return ((f"\nZur Übersicht: {url}/#home\n" if url else "\n") +
            "\n--\nDiese Mail verschickt die IT-Dokumentation automatisch. Einstellungen: Verwaltung → Mail → Fristen-Mail.\n")


def _company(conn) -> str:
    c = get_setting(conn, "company_name")
    return f" {c}" if c else ""


def compose_digest(conn: sqlite3.Connection, items: List[Dict], days: int) -> Tuple[str, str]:
    expired = [i for i in items if i["days"] < 0]
    soon = [i for i in items if i["days"] >= 0]
    n = len(items)
    subject = f"IT-Dokumentation{_company(conn)}: {n} Frist{'' if n == 1 else 'en'}" + (f", {len(expired)} abgelaufen" if expired else "")
    body = f"Hallo,\n\ndiese Fristen stehen in der IT-Dokumentation{_company(conn)} an:\n"
    if expired:
        body += "\nABGELAUFEN\n" + "\n".join(_line(i) for i in expired) + "\n"
    if soon:
        body += f"\nIN DEN NÄCHSTEN {days} TAGEN\n" + "\n".join(_line(i) for i in soon) + "\n"
    try:
        from .netscan import results
        new = len(results(conn)["new"])
    except Exception:  # noqa: BLE001
        new = 0
    if new:
        body += f"\nNETZWERK\n- Der letzte Netzwerk-Scan hat {new} unbekannte Gerät{'' if new == 1 else 'e'} gefunden (Netzwerk → Scan).\n"
    return subject, body + _footer(conn)


def compose_reminder(conn: sqlite3.Connection, it: Dict) -> Tuple[str, str]:
    if it["days"] < 0:
        head = f"{it['name']} ist abgelaufen"
    elif it["days"] == 0:
        head = f"{it['name']} läuft heute ab"
    else:
        head = f"{it['name']} läuft in {it['days']} Tagen ab"
    subject = f"Erinnerung: {head}"
    body = (f"Hallo,\n\nkurze Erinnerung aus der IT-Dokumentation{_company(conn)}:\n\n{_line(it)}\n\n"
            "Bitte rechtzeitig verlängern oder kündigen – danach in der IT-Dokumentation das neue Ablaufdatum eintragen.\n")
    return subject, body + _footer(conn)


def _send_all(conn, to: List[str], subject: str, body: str) -> List[str]:
    errors = []
    for addr in to:
        try:
            send_mail(conn, addr, subject, body, headers={"Auto-Submitted": "auto-generated"})
        except MailError as e:
            errors.append(f"{addr}: {e}")
    return errors


def send_digest(conn: sqlite3.Connection, force: bool = False) -> Dict:
    cfg = config(conn)
    items = due_items(conn, None, cfg["days"])
    if not items:
        return {"status": "empty", "count": 0}
    if not cfg["recipients"]:
        raise MailError("Keine Empfänger eingetragen")
    subject, body = compose_digest(conn, items, cfg["days"])
    errors = _send_all(conn, cfg["recipients"], subject, body)
    if len(errors) == len(cfg["recipients"]):
        raise MailError("; ".join(errors))
    audit(conn, None, "deadline_mail", "deadlines", f"Sammel-Mail mit {len(items)} Fristen an {', '.join(cfg['recipients'])}"
          + (" (von Hand)" if force else ""))
    return {"status": "sent", "count": len(items), "errors": errors}


def send_reminders(conn: sqlite3.Connection) -> int:
    """Stichtag-Erinnerungen (14 Tage vorher, Ablauftag). Liefert die Zahl verschickter Erinnerungen."""
    cfg = config(conn)
    if not cfg["recipients"]:
        return 0
    sent = 0
    for it in due_items(conn, None, max(MILESTONES)):
        for m in MILESTONES:
            # verpasste Tage (NAS aus) nachholen: 14er solange noch nicht abgelaufen, 0er bis eine Woche danach
            if not ((m > 0 and 0 < it["days"] <= m) or (m == 0 and -7 <= it["days"] <= 0)):
                continue
            key = f"{it['kind']}:{it['id']}:{it['date']}:{m}"
            if conn.execute("SELECT 1 FROM deadline_sent WHERE key = ?", (key,)).fetchone():
                continue
            subject, body = compose_reminder(conn, it)
            errors = _send_all(conn, cfg["recipients"], subject, body)
            if len(errors) == len(cfg["recipients"]):
                raise MailError("; ".join(errors))
            conn.execute("INSERT INTO deadline_sent(key, sent_at) VALUES (?, ?)", (key, now_utc_str()))
            audit(conn, None, "deadline_mail", f"{it['kind']}:{it['id']}", f"{it['name']} – Erinnerung ({_when(it['days'])})")
            sent += 1
            break  # pro Eintrag höchstens eine Erinnerung je Lauf
    return sent


def run_due(conn: sqlite3.Connection, now: Optional[datetime] = None) -> Optional[Dict]:
    """Vom Zeitplan aufgerufen (etwa minütlich). Arbeitet höchstens einmal pro Tag."""
    cfg = config(conn)
    if not cfg["enabled"] or not cfg["recipients"]:
        return None
    local = to_local(now or now_utc())
    today = local.date().isoformat()
    if local.hour < cfg["hour"] or get_setting(conn, "deadline_last_run") == today:
        return None
    set_setting(conn, "deadline_last_run", today)
    result = {"reminders": 0, "digest": None}
    try:
        result["reminders"] = send_reminders(conn)
        week = "%d-W%02d" % local.isocalendar()[:2]
        if local.weekday() == cfg["weekday"] and get_setting(conn, "deadline_last_week") != week:
            result["digest"] = send_digest(conn)
            set_setting(conn, "deadline_last_week", week)
        set_setting(conn, "deadline_last_result",
                    f"{today}: " + ("Sammel-Mail mit %d Fristen" % result["digest"]["count"] if result["digest"] and result["digest"]["status"] == "sent"
                                    else "nichts fällig" if result["digest"] else "keine Sammel-Mail heute")
                    + (f", {result['reminders']} Erinnerung(en)" if result["reminders"] else ""))
    except MailError as e:
        set_setting(conn, "deadline_last_result", f"{today}: FEHLER – {e}")  # morgen erneut; „Jetzt senden“ geht sofort
        result["error"] = str(e)
    return result
