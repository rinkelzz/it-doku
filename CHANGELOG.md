# Änderungen

Alle nennenswerten Änderungen an diesem Projekt. Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

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

[0.2.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.2.0
[0.1.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.1.0
