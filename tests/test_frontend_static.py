"""Statische Prüfungen der Oberfläche (ohne Browser)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_close_attribute_only_on_buttons():
    """data-x schließt ein Fenster – Eingabefelder dürfen es nicht tragen (sonst schließt ein Klick ins Passwortfeld das Formular)."""
    for f in STATIC.glob("*.js"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"<(input|textarea|select)[^>]*\sdata-x[=\s>]", src), f.name
    doku = (STATIC / "doku.js").read_text(encoding="utf-8")
    assert '$$("button[data-x]", card).forEach(b => b.onclick = closeSheet)' in doku


def test_remote_protocol_links_not_opened_in_frame():
    """anydesk:/rustdesk:// würden den DSM-iframe auf eine Fehlerseite schicken – sie laufen über das oberste Fenster."""
    doku = (STATIC / "doku.js").read_text(encoding="utf-8")
    assert '" data-proto"' in doku
    assert "window.top.location.href = url" in doku
    assert 'closest("a[data-proto]")' in doku
