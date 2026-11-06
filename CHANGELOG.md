# Änderungen

Alle nennenswerten Änderungen an diesem Projekt. Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.4.0] – 2026-11-06

### Neu
- **Fristen-Mail** (Verwaltung → Mail): einmal pro Woche (Wochentag und Uhrzeit wählbar) eine Sammel-Mail mit
  abgelaufenen und bald ablaufenden Lizenzen, Domains, Zertifikaten und Garantien – nur wenn etwas fällig ist. Dazu je
  Eintrag eine Erinnerung **14 Tage vorher** und **am Ablauftag** (verpasste Tage werden nachgeholt, keine Mail doppelt;
  wird ein Ablaufdatum verlängert, gibt es für das neue Datum wieder Erinnerungen). Empfänger frei eintragbar,
  Vorwarnzeit 30–180 Tage, Vorschau „Das stünde gerade in der Mail“ und „Sammel-Mail jetzt senden“.
- **Notfall-Handbuch als PDF** (Knopf auf der Übersicht): Notfall-Kontakte und weitere Ansprechpartner, je Standort
  Adresse, Internetanschluss, Netze/VLANs, IP-Listen mit DHCP-Bereich und der Netzwerkplan als Bild. Enthält bewusst
  keine Passwörter. Große PNG-Pläne werden ohne Umrechnung übernommen (schnell auch auf ARM-NAS).
- **CSV-Import für Geräte** (Geräte → Import): beliebige CSV (Excel-Export, Inventarliste; Trennzeichen ; , oder Tab;
  UTF-8 oder Windows-1252). Spalten werden automatisch erkannt und lassen sich zuordnen; die Vorschau zeigt je Zeile,
  was passiert. Datumsangaben wie 13.03.2028, 2028-03-13 oder 03/2028, Status-Wörter wie „in Betrieb“ oder „defekt“,
  IP mit MAC und Hostname. Dubletten per Seriennummer werden übersprungen, unbekannte Typen und Standorte auf Wunsch
  angelegt. Alles in einer Transaktion.

## [0.3.0] – 2026-11-06

### Neu
- **Tresor für Zugangsdaten.** Passwort, Notiz und 2FA-Geheimnis jedes Zugangs sowie Lizenzschlüssel liegen
  verschlüsselt in der Datenbank (AES-256-CTR + HMAC-SHA-256, reines Python). Titel, Benutzername, Adresse und
  Zuordnung bleiben lesbar – Liste und Suche funktionieren auch bei gesperrtem Tresor.
- **Tresor-Passwort pro Benutzer** (nicht das Login-Passwort, nirgends gespeichert, PBKDF2-SHA-256 mit 600 000 Runden).
  Einrichten in zwei Schritten mit **Notfall-Schlüssel** zum Ausdrucken (PDF-Blatt mit Anleitung).
- **Auto-Sperre** nach 15 Minuten ohne Aktivität (5–60 einstellbar), beim Abmelden und beim Neustart. Anzeige mit
  Restzeit und „Sperren“ in der Kopfzeile.
- **Freischalten per Einladungscode:** Bei offenem Tresor einen Code für einen Benutzer mit Vollzugriff erzeugen
  (7 Tage gültig); die Person legt damit ihr eigenes Tresor-Passwort fest. Zugang entziehen, Einladung zurückziehen,
  Tresor-Passwort ändern, „Passwort vergessen?“ mit Notfall-Schlüssel, Notfall-Schlüssel neu erzeugen.
- **Reiter „Zugangsdaten“** mit Filter (Geräte, Lizenzen & Portale, Standorte, Kontakte, allgemein, 2FA, Passwort älter
  als 1 Jahr) und Suche. **Anzeigen** (verschwindet nach 30 s) und **Kopieren** (Zwischenablage wird nach 30 s geleert,
  soweit der Browser es erlaubt) – jeder Abruf steht im Änderungsprotokoll.
- **2FA-Codes (TOTP):** Base32-Geheimnis oder `otpauth://`-Link hinterlegen, die App zeigt den aktuellen Code mit Restzeit.
- **Passwort-Generator** im Browser (Länge, Zeichengruppen, ohne ähnliche Zeichen) mit Stärke-Anzeige.
- Zugangsdaten direkt am **Gerät**, an der **Lizenz** (Portale) und am **Standort** (z. B. WLAN); **Lizenzschlüssel**
  an der Lizenz anzeigen, kopieren, ändern.
- Benutzer mit **Lesen** sehen keine Zugangsdaten – auch nicht in Suche und „Zuletzt geändert“. Wer den Vollzugriff
  verliert oder deaktiviert wird, verliert automatisch den Tresor-Zugang; der letzte Zugang lässt sich nicht entfernen.
- Neuer Bereich **„Tresor“** im Änderungsprotokoll; Fehlversuche beim Entsperren sind begrenzt (5 in 15 Minuten).

## [0.2.0] – 2026-11-06

### Neu
- **Übersicht:** Zahlen zu Geräten, Lizenzen, Netzen und Ansprechpartnern, **„Bald fällig“** (abgelaufene und in
  90 Tagen ablaufende Lizenzen, endende Garantien), **„Im Notfall anrufen“**, Standorte und **„Zuletzt geändert“**.
- **Geräte** mit frei pflegbaren **Gerätetypen** (vorbelegt, mit Symbol, sortierbar, zusammenlegbar), Standort, Raum,
  Hersteller/Modell, Seriennummer, Inventar-Nr., Betriebssystem, Nutzer, Kauf und Garantie, Status aktiv / im Lager /
  ausgemustert. Liste mit Filter nach Standort, Typ und Status, Suche, CSV-Export; Formular mit Vorschlägen aus schon
  erfassten Werten und „Speichern & nächstes“.
- **Gerät im Detail:** IP-Adressen, zugeordnete Lizenzen, **„Verbunden mit“** (z. B. Switch Port 7, Standarddrucker),
  Notizen, **Anhänge** und **Verlauf** aller Änderungen. Platzhalter für den Tresor (0.3).
- **Netzwerk:** Netze/VLANs pro Standort (Netz, Gateway, DHCP-Bereich, DNS) mit Belegung, **IP-Liste** mit Gerät,
  Hostname, MAC und Art (fest, DHCP-Reservierung, DHCP), auf Wunsch mit **freien Adressen**. IPs werden automatisch dem
  passenden Netz zugeordnet, doppelte IPs abgelehnt. **Netzwerkplan** als Bild oder PDF pro Standort und
  **Internetanschluss** (Anbieter, Tarif, öffentliche IP, Kundennummer).
- **Lizenzen** mit Art (Software, Abo, Wartungsvertrag, **Domain**, **Zertifikat**, Sonstiges), Laufzeit, Plätzen
  (genutzt = zugeordnete Geräte oder von Hand), Ablaufdatum, Vertrag/Kundennummer, Geräte-Zuordnung, Anhängen und
  Verlauf. Filter „läuft ab“ und „abgelaufen“.
- **Ansprechpartner** intern und extern (Dienstleister mit Kundennummer), Markierung **Notfall**, Telefonnummern zum
  Antippen.
- **Globale Suche** in der Kopfzeile (Taste `/`): Geräte, IP-/MAC-Adressen, Hostnamen, Seriennummern, Personen (auch
  Telefonnummern ohne Leerzeichen), Lizenzen, Netze, Standorte.
- **Verwaltung → Stammdaten:** Standorte und Gerätetypen. Mit nur einem Standort ist die Standort-Auswahl ausgeblendet.
- **Anhänge** (PNG, JPG, PDF bis 10 MB) liegen in der Datenbank und sind damit in jeder Sicherung enthalten.
- Benutzer mit **Lesen** sehen alles, ändern aber nichts. Alle Änderungen stehen im Änderungsprotokoll (Bereich „Dokumentation“).

## [0.1.0] – 2026-11-06

Erste Version: das Fundament der IT-Dokumentation (übernommen aus [Zeitmanagement](https://github.com/rinkelzz/zeitmanagement)).

### Neu
- **Synology-Paket** (`itdoku`, noarch für Intel/AMD und ARM, Python 3.8–3.13) mit eigenem **DSM-Fenster** und
  **Single Sign-on**. Installationsassistent mit Admin-Passwort, Firmenname und Port (Standard 8780).
- **Anmeldung** mit eigenem Konto oder DSM-Konto (inklusive Zwei-Faktor-Code), Login-Sperre pro Adresse und Benutzername.
- **Benutzer** mit **Vollzugriff** oder **nur Lesen**. DSM-Administratoren kommen per Single Sign-on mit Vollzugriff
  hinein; andere DSM-Konten nur, wenn der Admin sie anlegt (automatisches Anlegen mit Lesezugriff ist abschaltbar).
- **Firmenname und Logo** in Kopfzeile und Anmeldung, vier Designs, für Handy und Desktop.
- **Nächtliche Datensicherung** in einen freigegebenen Ordner, Wiederherstellen per Klick; das Mail-Passwort wird
  nicht mitgesichert.
- **Updates über das Paket-Zentrum** (die App ist ihre eigene Paketquelle).
- **Änderungsprotokoll** mit Filter und CSV-Export (gegen Formel-Injection abgesichert).
- **Port** in der App änderbar, Mailversand über den eigenen SMTP-Server mit Testmail.
- Neues Symbol (Dokument mit Schloss).

[0.4.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.4.0
[0.3.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.3.0
[0.2.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.2.0
[0.1.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.1.0
