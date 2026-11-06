"""Notfall-Handbuch als PDF: wen anrufen, Internetanschluss, Netze, IP-Listen und Netzwerkplan je Standort.

Enthält bewusst keine Zugangsdaten – die bleiben im Tresor.
"""
import sqlite3
from typing import List, Optional, Sequence, Tuple

from .db import get_setting
from .doku import IP_KINDS, ip_key
from .logo import LogoError, fit_box, image_from_bytes, pdf_image
from .pdf import A4_H, A4_W, PDF, fit
from .timeutil import today_local

M = 48                       # Rand
W = A4_W - 2 * M
TOP, BOTTOM = 70, A4_H - 50
ACCENT = (0.06, 0.46, 0.43)
GREY = (0.42, 0.45, 0.5)
LIGHT = (0.95, 0.96, 0.97)


class Doc:
    def __init__(self, conn: sqlite3.Connection):
        self.company = get_setting(conn, "company_name") or ""
        self.date = today_local().strftime("%d.%m.%Y")
        self.p = PDF(title="Notfall-Handbuch" + (f" – {self.company}" if self.company else ""))
        self.page = 1
        self.y = TOP
        self._chrome()

    def _chrome(self) -> None:
        p = self.p
        p.text(M, 34, fit("Notfall-Handbuch" + (f" · {self.company}" if self.company else ""), W - 140, 8), 8, color=GREY)
        p.text(A4_W - M, 34, f"Stand {self.date}", 8, color=GREY, align="right")
        p.line(M, 42, A4_W - M, 42, 0.4, (0.85, 0.86, 0.88))
        p.text(M, A4_H - 28, "Vertraulich – nur für den internen Gebrauch. Enthält keine Passwörter.", 7.5, color=GREY)
        p.text(A4_W - M, A4_H - 28, f"Seite {self.page}", 7.5, color=GREY, align="right")

    def new_page(self) -> None:
        self.p.new_page()
        self.page += 1
        self.y = TOP
        self._chrome()

    def need(self, h: float) -> None:
        if self.y + h > BOTTOM:
            self.new_page()

    def h1(self, text: str) -> None:
        self.need(60)
        self.y += 10
        self.p.text(M, self.y + 14, text, 15, bold=True, color=ACCENT)
        self.y += 26

    def h2(self, text: str) -> None:
        self.need(50)
        self.y += 6
        self.p.text(M, self.y + 11, text, 11, bold=True)
        self.y += 20

    def para(self, text: str, size: float = 9, color=(0.15, 0.15, 0.15)) -> None:
        for line in wrap(text, W, size):
            self.need(size + 5)
            self.p.text(M, self.y + size, line, size, color=color)
            self.y += size + 4
        self.y += 4

    def kv(self, pairs: Sequence[Tuple[str, str]], label_w: float = 110) -> None:
        for k, v in pairs:
            if not v:
                continue
            lines = wrap(v, W - label_w, 9)
            self.need(13 * len(lines))
            self.p.text(M, self.y + 9, k, 9, color=GREY)
            for line in lines:
                self.p.text(M + label_w, self.y + 9, line, 9)
                self.y += 13
        self.y += 6

    def table(self, cols: Sequence[Tuple[str, float]], rows: List[Sequence[str]], empty: str = "–") -> None:
        """cols: (Titel, Anteil an der Breite). Kopfzeile wird auf neuen Seiten wiederholt."""
        total = sum(c[1] for c in cols)
        widths = [W * c[1] / total for c in cols]
        rh = 15

        def head():
            self.p.rect(M, self.y, W, rh + 2, fill=LIGHT)
            x = M
            for (title, _), w in zip(cols, widths):
                self.p.text(x + 4, self.y + 11, fit(title, w - 8, 8, bold=True), 8, bold=True, color=GREY)
                x += w
            self.y += rh + 2

        self.need(rh * 3)
        head()
        if not rows:
            self.p.text(M + 4, self.y + 11, empty, 8.5, color=GREY)
            self.y += rh + 6
            return
        for i, row in enumerate(rows):
            if self.y + rh > BOTTOM:
                self.new_page()
                head()
            x = M
            for val, w in zip(row, widths):
                self.p.text(x + 4, self.y + 11, fit(val or "", w - 8, 8.5), 8.5)
                x += w
            self.p.line(M, self.y + rh, M + W, self.y + rh, 0.3, (0.88, 0.89, 0.91))
            self.y += rh
        self.y += 10

    def image(self, img: dict, max_h: float = 520) -> None:
        w, h = fit_box(img["width"], img["height"], W, max_h)
        self.need(h + 10)
        self.p.image(M + (W - w) / 2, self.y, w, h, img)
        self.y += h + 12


def wrap(text: str, width: float, size: float) -> List[str]:
    from .pdf import text_width
    out = []
    for raw in str(text or "").split("\n"):
        line = ""
        for word in raw.split(" "):
            cand = (line + " " + word).strip()
            if text_width(cand, size) <= width or not line:
                line = cand
            else:
                out.append(line)
                line = word
        out.append(fit(line, width, size))
    return out


def dhcp_range(a: str, b: str) -> str:
    if not a:
        return ""
    pa, pb = a.split("."), (b or "").split(".")
    if len(pa) == 4 and len(pb) == 4 and pa[:3] == pb[:3]:
        return f"{a} – .{pb[3]}"
    return f"{a} – {b}"


def _contact_rows(rows) -> List[List[str]]:
    return [[r["name"], " · ".join(x for x in (r["company"], r["role"]) if x), r["phone"], r["mobile"], r["customer_no"],
             "extern" if r["external"] else ""] for r in rows]


def build(conn: sqlite3.Connection, site_id: Optional[int] = None) -> bytes:
    d = Doc(conn)
    p = d.p
    # Titel
    logo = pdf_image(conn)
    if logo:
        lw, lh = fit_box(logo["width"], logo["height"], 160, 54)
        p.image(A4_W - M - lw, TOP - 4, lw, lh, logo)
    p.text(M, d.y + 24, "Notfall-Handbuch", 24, bold=True)
    d.y += 34
    if d.company:
        p.text(M, d.y + 13, d.company, 13, color=GREY)
        d.y += 22
    p.text(M, d.y + 10, f"Stand: {d.date}", 10, color=GREY)
    d.y += 24
    d.para("Für den Ernstfall: wen anrufen, wie das Netz aufgebaut ist und welche Adressen die Geräte haben. "
           "Passwörter stehen hier bewusst nicht drin – sie liegen verschlüsselt im Tresor der IT-Dokumentation. "
           "Bitte ausgedruckt griffbereit, aber nicht offen herumliegen lassen.", 9.5, GREY)

    contact_cols = [("Name", 2.2), ("Firma / Rolle", 3.8), ("Telefon", 1.8), ("Mobil", 1.8), ("Kundennr.", 1.3), ("", 0.7)]
    d.h1("Im Notfall anrufen")
    sos = conn.execute("SELECT * FROM contacts WHERE emergency = 1 ORDER BY external, name COLLATE NOCASE").fetchall()
    d.table(contact_cols, _contact_rows(sos), "Noch niemand als Notfall-Kontakt markiert.")
    others = conn.execute("SELECT * FROM contacts WHERE emergency = 0 ORDER BY external DESC, name COLLATE NOCASE").fetchall()
    if others:
        d.h2("Weitere Ansprechpartner und Dienstleister")
        d.table(contact_cols, _contact_rows(others))

    sites = conn.execute("SELECT * FROM sites" + (" WHERE id = ?" if site_id else "") + " ORDER BY sort, id",
                         (site_id,) if site_id else ()).fetchall()
    multi = conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0] > 1
    for s in sites:
        d.new_page()
        d.h1(f"Standort {s['name']}" if multi else "Netzwerk und Internet")
        if s["address"]:
            d.para(s["address"], 10)
        d.h2("Internetanschluss")
        isp = [("Anbieter", s["isp_provider"]), ("Tarif", s["isp_tariff"]), ("Öffentliche IP", s["isp_public_ip"]),
               ("Kundennummer", s["isp_customer_no"]), ("Hinweise", s["isp_notes"])]
        if any(v for _, v in isp):
            d.kv(isp)
        else:
            d.para("Nicht erfasst.", 9, GREY)
        nets = conn.execute("SELECT * FROM networks WHERE site_id = ? OR (site_id IS NULL AND ?) ORDER BY sort, vlan, name",
                            (s["id"], 0 if multi else 1)).fetchall()
        d.h2("Netze")
        d.table([("Name", 2.4), ("VLAN", 0.8), ("Netz", 2), ("Gateway", 1.6), ("DHCP", 2.6), ("DNS", 1.6)],
                [[n["name"], "" if n["vlan"] is None else str(n["vlan"]), n["cidr"], n["gateway"],
                  dhcp_range(n["dhcp_from"], n["dhcp_to"]), n["dns"]] for n in nets], "Keine Netze erfasst.")
        for n in nets:
            if n["notes"]:
                d.para(f"{n['name']}: {n['notes']}", 8.5, GREY)
        for n in nets:
            ips = sorted(conn.execute(
                "SELECT i.*, d.name AS device FROM ip_addresses i LEFT JOIN devices d ON d.id = i.device_id WHERE i.network_id = ?",
                (n["id"],)).fetchall(), key=lambda r: ip_key(r["ip"]))
            if not ips:
                continue
            d.h2(f"IP-Adressen · {n['name']}" + (f" ({n['cidr']})" if n["cidr"] else ""))
            rows = [[r["ip"], r["device"] or "", r["hostname"], r["mac"],
                     " · ".join(x for x in (IP_KINDS.get(r["kind"], "") if r["kind"] != "static" else "", r["notes"]) if x)]
                    for r in ips]
            if n["dhcp_from"]:
                rows.append([dhcp_range(n["dhcp_from"], n["dhcp_to"]), "DHCP-Bereich", "", "", ""])
            d.table([("IP", 2.4), ("Gerät", 2.6), ("Hostname", 2), ("MAC", 2.2), ("Hinweis", 2.6)], rows)
        dg = conn.execute("SELECT name, mime, data FROM attachments WHERE owner_type = 'site' AND owner_id = ? AND role = 'diagram' "
                          "ORDER BY id DESC LIMIT 1", (s["id"],)).fetchone()
        if dg:
            img = None
            if dg["mime"] in ("image/png", "image/jpeg"):
                try:
                    img = image_from_bytes(bytes(dg["data"]), "jpeg" if dg["mime"] == "image/jpeg" else "png")
                except (LogoError, ValueError, IndexError):
                    img = None
            if img:
                _, ih = fit_box(img["width"], img["height"], W, 520)
                d.need(ih + 50)
                d.h2("Netzwerkplan")
                d.image(img)
            else:
                d.h2("Netzwerkplan")
                d.para(f"Der Netzwerkplan „{dg['name']}“ liegt als Datei in der IT-Dokumentation (Netzwerk → Netzwerkplan).", 9, GREY)
    if not multi or not site_id:
        loose = conn.execute("SELECT i.*, d.name AS device FROM ip_addresses i LEFT JOIN devices d ON d.id = i.device_id "
                             "WHERE i.network_id IS NULL").fetchall()
        if loose:
            d.h2("IP-Adressen ohne Netz")
            d.table([("IP", 1.8), ("Gerät", 2.6), ("Hostname", 2), ("MAC", 2.2), ("Hinweis", 2.8)],
                    [[r["ip"], r["device"] or "", r["hostname"], r["mac"], r["notes"]] for r in sorted(loose, key=lambda r: ip_key(r["ip"]))])
    return p.output()
