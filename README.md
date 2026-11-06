# IT-Dokumentation für Synology

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-☕-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/lapalutschi)

[![Tests](https://github.com/rinkelzz/it-doku/actions/workflows/ci.yml/badge.svg)](https://github.com/rinkelzz/it-doku/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/rinkelzz/it-doku?include_prereleases)](https://github.com/rinkelzz/it-doku/releases)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-blue.svg)](LICENSE)

Eine schlanke Alternative zu IT Glue: die IT-Dokumentation **eines Kunden** – Standorte, Ansprechpartner, Geräte,
Lizenzen, Netzwerkplan und Zugangsdaten (verschlüsselt im Tresor). Sie läuft als Paket auf der NAS des Kunden, mit
eigenem Fenster in DSM. Die Daten bleiben beim Kunden; der IT-Dienstleister und eine Vertrauensperson beim Kunden
haben vollen Zugriff, alle anderen höchstens Lesezugriff ohne Passwörter.

> **Stand 0.6:** Geräte, Netzwerk mit Netzwerk-Scan, Agent für Server und PCs (Windows, Linux, macOS), Lizenzen,
> Ansprechpartner, Zugangsdaten im verschlüsselten Tresor, Fristen-Mail, Notfall-Handbuch als PDF und CSV-Import –
> siehe [Fahrplan](#fahrplan).

![Übersicht](docs/screenshots/uebersicht.png)

## Inhalt

- [Funktionen](#funktionen)
- [Rechte](#rechte)
- [Tresor für Zugangsdaten](#tresor-für-zugangsdaten)
- [Agent für Server und PCs](#agent-für-server-und-pcs)
- [Fahrplan](#fahrplan)
- [Installation auf der Synology](#installation-auf-der-synology)
- [Updates über das Paket-Zentrum](#updates-über-das-paket-zentrum)
- [Datensicherung](#datensicherung)
- [Von unterwegs erreichbar machen (Reverse Proxy)](#von-unterwegs-erreichbar-machen-reverse-proxy)
- [Port ändern](#port-ändern)
- [Entwicklung](#entwicklung)
- [English](#english)

## Funktionen

### Dokumentation

- **Übersicht:** Zahlen, **„Bald fällig“** (Lizenzen, Domains, Zertifikate, Garantien), **„Im Notfall anrufen“**,
  Standorte und zuletzt Geändertes.
- **Geräte** mit frei pflegbaren Typen, Standort, Raum, Seriennummer, Garantie und Status (aktiv, im Lager, ausgemustert).
  Im Detail: IP-Adressen, Lizenzen, **„Verbunden mit“** (Switch-Port, Drucker), Notizen, Anhänge und Verlauf. CSV-Export.
- **Netzwerk:** Netze/VLANs pro Standort, IP-Liste mit Gerät, Hostname und MAC (auf Wunsch mit freien Adressen),
  **Netzwerkplan** als Bild oder PDF und **Internetanschluss**.
- **Lizenzen**, Abos, Wartungsverträge, Domains und Zertifikate – alles mit Ablaufdatum an einer Stelle, mit Plätzen
  und Geräte-Zuordnung.
- **Ansprechpartner** beim Kunden und externe Dienstleister mit Kundennummer, Notfall-Markierung.
- **Globale Suche** (Taste `/`) über Geräte, IP-/MAC-Adressen, Seriennummern, Personen, Telefonnummern, Lizenzen und Netze.
- **Anhänge** (PNG, JPG, PDF bis 10 MB) an Geräten und Lizenzen – in der Datenbank, also in jeder Sicherung.
- **Fristen-Mail:** wöchentliche Sammel-Mail mit ablaufenden Lizenzen, Domains, Zertifikaten und Garantien an frei
  wählbare Empfänger, dazu je Eintrag eine Erinnerung 14 Tage vorher und am Ablauftag (Verwaltung → Mail).
- **Notfall-Handbuch als PDF** (Übersicht): Notfall-Kontakte, Internetanschluss, Netze, IP-Listen und Netzwerkplan je
  Standort – ohne Passwörter, zum Ausdrucken.
- **Netzwerk-Scan** (von Hand oder nachts): findet unbekannte Geräte und legt sie mit einem Klick an, ergänzt MAC und
  Hostname, meldet abweichende MAC-Adressen und Geräte, die länger nicht erreichbar waren. Läuft ohne Root-Rechte und ohne
  Zusatzprogramme, nur in Netzen mit Haken „scannen“ (IPv4, höchstens /22).
- **Agent für Server und PCs** (Windows, Linux, macOS): meldet täglich Hardware, System, Datenträger, Netzwerk,
  installierte Software, Updates und Dienste – siehe [unten](#agent-für-server-und-pcs).
- **CSV-Import für Geräte:** beliebige Inventarliste hochladen, Spalten zuordnen, Vorschau prüfen, importieren.
  Dubletten (gleiche Seriennummer) werden übersprungen.

| Übersicht | Gerät | Netzwerk |
|---|---|---|
| ![Übersicht](docs/screenshots/uebersicht.png) | ![Gerät](docs/screenshots/geraet.png) | ![Netzwerk](docs/screenshots/netzwerk.png) |
| **Geräte** | **Lizenzen** | **Kontakte** |
| ![Geräte](docs/screenshots/geraete.png) | ![Lizenzen](docs/screenshots/lizenzen.png) | ![Kontakte](docs/screenshots/kontakte.png) |
| **CSV-Import** | **Fristen-Mail** | **Netzwerk-Scan** |
| ![CSV-Import](docs/screenshots/import.png) | ![Fristen-Mail](docs/screenshots/fristen-mail.png) | ![Netzwerk-Scan](docs/screenshots/netzwerk-scan.png) |
| **Vom Agent gemeldet** | **Agenten** | **Agent einrichten** |
| ![Vom Agent gemeldet](docs/screenshots/agent-geraet.png) | ![Agenten](docs/screenshots/agenten.png) | ![Agent einrichten](docs/screenshots/agent-einrichten.png) |
| **Suche** | **Stammdaten** | **Handy** |
| ![Suche](docs/screenshots/suche.png) | ![Stammdaten](docs/screenshots/stammdaten.png) | ![Handy](docs/screenshots/handy.png) |

### Plattform

- **Eigenes Fenster in DSM** mit Single Sign-on: DSM-Administratoren sind ohne weitere Anmeldung drin.
- **Anmeldung** mit eigenem Konto oder DSM-Konto (inklusive Zwei-Faktor-Code), Login-Sperre gegen Durchprobieren.
- **Benutzer** mit **Vollzugriff** oder **nur Lesen** (sieht nie Zugangsdaten).
- **Firmenname und Logo** des Kunden in Kopfzeile und Anmeldung, vier Designs (Klassisch, Synology DSM, Dunkel,
  Warm & groß), für Handy und Desktop.
- **Nächtliche Datensicherung** in einen freigegebenen Ordner (für Hyper Backup), Wiederherstellen per Klick.
- **Updates über das Paket-Zentrum** – die App ist ihre eigene Paketquelle.
- **Änderungsprotokoll** aller wichtigen Aktionen, als CSV exportierbar.
- **Port** in der App änderbar, Mailversand über den eigenen SMTP-Server.

| Anmeldung | Benutzer | System |
|---|---|---|
| ![Anmeldung](docs/screenshots/anmeldung.png) | ![Benutzer](docs/screenshots/benutzer.png) | ![System](docs/screenshots/system.png) |

## Rechte

| | Vollzugriff | Lesen |
|---|---|---|
| Dokumentation ansehen | ✔ | ✔ |
| Dokumentation ändern | ✔ | – |
| Zugangsdaten und Lizenzschlüssel | ✔ (mit eigenem Tresor-Passwort) | – |
| Verwaltung (Benutzer, Einstellungen, Sicherung) | ✔ | – |

Ein DSM-Konto kommt nur hinein, wenn es DSM-Administrator ist (dann mit Vollzugriff) oder wenn in der
IT-Dokumentation ein Benutzer mit gleichem Namen angelegt ist. Beides lässt sich unter **Verwaltung → Einstellungen**
ändern.

## Tresor für Zugangsdaten

| Zugangsdaten | Neuer Zugang | Gerät, Tresor gesperrt |
|---|---|---|
| ![Zugangsdaten](docs/screenshots/tresor-zugangsdaten.png) | ![Neuer Zugang](docs/screenshots/tresor-neuer-zugang.png) | ![Gerät](docs/screenshots/tresor-geraet-gesperrt.png) |
| **Notfall-Schlüssel** | **Verwaltung → Tresor** | |
| ![Notfall-Schlüssel](docs/screenshots/tresor-notfall-schluessel.png) | ![Verwaltung](docs/screenshots/tresor-verwaltung.png) | |

- **Was ist verschlüsselt?** Passwort, Notiz und 2FA-Geheimnis jedes Zugangs sowie Lizenzschlüssel. Titel,
  Benutzername, Adresse und Zuordnung bleiben lesbar, damit Liste und Suche auch bei gesperrtem Tresor funktionieren.
- **Wie?** Ein zufälliger **Datenschlüssel** verschlüsselt die Einträge (AES-256-CTR mit HMAC-SHA-256, in reinem
  Python – ohne native Bibliotheken). In der Datenbank liegt er nur verschlüsselt: einmal pro Benutzer mit dessen
  **Tresor-Passwort** (PBKDF2-SHA-256, 600 000 Runden) und einmal mit dem **Notfall-Schlüssel**.
- **Einrichten:** oben rechts **🔒 Tresor → einrichten** → Tresor-Passwort festlegen → **Notfall-Schlüssel** als PDF
  herunterladen, ausdrucken und sicher verwahren (z. B. im Firmentresor). Ohne Tresor-Passwort und ohne
  Notfall-Schlüssel sind die Zugangsdaten nicht wiederherstellbar. Das ist gewollt.
- **Weitere Personen** (nur mit Vollzugriff): **Verwaltung → Tresor → Freischalten** erzeugt einen Einladungscode
  (7 Tage gültig). Die Person legt damit ihr **eigenes** Tresor-Passwort fest – du erfährst es nie.
- **Auto-Sperre** nach 15 Minuten ohne Aktivität (einstellbar 5–60), beim Abmelden und beim Neustart der App.
- **Anzeigen und Kopieren** wird protokolliert. Kopierte Passwörter werden nach 30 Sekunden aus der Zwischenablage
  gelöscht, soweit der Browser es erlaubt.
- **2FA-Codes:** Base32-Geheimnis oder `otpauth://`-Link (aus dem QR-Code) hinterlegen – die App zeigt den aktuellen
  sechsstelligen Code.
- **Passwort vergessen?** Im Entsperren-Dialog mit dem Notfall-Schlüssel ein neues Tresor-Passwort setzen.
- **Sicherungen** enthalten den Tresor nur verschlüsselt. Nach einem Wiederherstellen (auch auf einer neuen NAS)
  öffnen die bisherigen Tresor-Passwörter und der Notfall-Schlüssel ihn wie gewohnt.

## Agent für Server und PCs

Für Rechner, die der Netzwerk-Scan nicht sieht (Cloud-Server, Filiale, Homeoffice) oder bei denen mehr als die IP
interessiert: Ein kleiner Agent schickt **täglich und nach jedem Start** einen Bericht per HTTPS an die
IT-Dokumentation. Am Server muss **kein Port offen** sein – der Agent meldet sich, nicht umgekehrt.

**Was gemeldet wird:** Rechnername, Betriebssystem mit Build, CPU, Arbeitsspeicher, Hersteller/Modell/Seriennummer,
Laufzeit seit dem letzten Start, Datenträger mit freiem Platz, Netzwerkkarten mit IP/MAC, Gateway und DNS,
installierte Software (durchsuchbar, als CSV), ausstehende Updates und ob ein Neustart nötig ist, Dienste (gestoppte
Dienste mit Autostart werden hervorgehoben). Keine Dateien, keine Passwörter, keine Benutzerdaten.

**Gerät finden:** Beim ersten Bericht sucht die App das Gerät über die Seriennummer, dann über den Rechnernamen – sonst
legt sie es neu an (Typ PC, Laptop oder Server, Standort über das passende Netz). Danach zieht sie das Betriebssystem
nach und ergänzt leere Felder (Hersteller, Modell, Seriennummer); von Hand Gepflegtes bleibt. IPv4-Adressen aus
dokumentierten Netzen landen in der IP-Liste.

**Einrichten:** Verwaltung → 🛰️ Agenten → **＋ Agent**. Die App zeigt einen Schlüssel (nur einmal) und den passenden
Befehl zum Einfügen:

| System | Voraussetzung | Zeitplan |
|---|---|---|
| Windows 10/11, Server 2016+ | Windows PowerShell 5.1 (eingebaut), als Administrator | geplante Aufgabe „ITDoku Agent“ als SYSTEM |
| Linux | Python 3.6+ (Standardbibliothek), sudo | systemd-Timer, sonst Cron |
| macOS | Python 3 (Command Line Tools), sudo | LaunchDaemon |

Entfernen: `sudo itdoku-agent --uninstall` bzw.
`powershell -ExecutionPolicy Bypass -File C:\ProgramData\ITDoku\itdoku-agent.ps1 -Uninstall`.
Ansehen, was gesendet würde, ohne zu senden: `--print` bzw. `-Print`.

**Erreichbarkeit** (Adresse unter Verwaltung → Agenten eintragen):
- **Von außen:** Reverse Proxy mit https wie unten beschrieben – die Agenten nutzen nur `/api/agent/v1/report` und
  zum Herunterladen `/agent/…`.
- **Per VPN/LAN:** die interne Adresse, z. B. `http://192.168.10.5:8780`. Unverschlüsselt muss im Befehl ausdrücklich
  bestätigt werden (`--allow-http` / `-AllowHttp`).

Meldet sich ein Agent länger nicht (Standard: 3 Tage), erscheint ein Hinweis auf der **Übersicht**, am Gerät und in der
wöchentlichen **Fristen-Mail**.

## Fahrplan

| Version | Inhalt |
|---|---|
| **0.1** ✔ | Fundament: SPK, DSM-Fenster, Single Sign-on, Benutzer, Sicherung, Updates, Protokoll |
| **0.2** ✔ | Stammdaten: Standorte, Ansprechpartner, Geräte mit frei pflegbaren Typen und Verbindungen, Lizenzen inkl. Domains und Zertifikate, Netze/VLANs mit IP-Liste, Netzwerkplan, Internetanschluss, Anhänge, Verlauf, globale Suche |
| **0.3** ✔ | Tresor: Zugangsdaten mit Tresor-Passwort pro Benutzer, Einladungscode, Notfall-Schlüssel als PDF, Auto-Sperre, Anzeigen/Kopieren mit Protokoll, Passwort-Generator, 2FA-Codes (TOTP), verschlüsselte Lizenzschlüssel |
| **0.4** ✔ | Komfort: Fristen-Mail (wöchentlich + Stichtage), PDF „Notfall-Handbuch“ (Kontakte, Internet, Netzwerk), CSV-Import für Geräte mit Spaltenzuordnung |
| **0.5** ✔ | Netzwerk-Scan: neue Geräte übernehmen, MAC/Hostname ergänzen, Abweichungen, „zuletzt online“, nachts automatisch |
| **0.6** ✔ | Agent für Server und PCs (Windows, Linux, macOS): Hardware, System, Datenträger, Netzwerk, Software, Updates und Dienste per HTTPS, Gerät wird gefunden oder angelegt, Hinweis bei stillen Agenten |
| später | Wiki-Seiten für Anleitungen, Verknüpfung mit dem Helpdesk aus [Zeitmanagement](https://github.com/rinkelzz/zeitmanagement) |

## Installation auf der Synology

Voraussetzung: DSM 7. Ein Paket für alle Modelle – **Intel/AMD** und **ARM** (ARMv8, ARMv7).

1. Unter [Releases](https://github.com/rinkelzz/it-doku/releases) die neueste
   `itdoku-<version>-0001-noarch.spk` herunterladen.
2. DSM → **Paket-Zentrum** → **Manuelle Installation** → SPK auswählen → Hinweis zu Drittanbieter-Paketen bestätigen.
3. Im Assistenten eingeben:
   - ein Passwort für den Benutzer `admin` (mindestens 8 Zeichen),
   - optional den **Firmennamen** des Kunden,
   - den **Port** (Standard `8780` – nur ändern, wenn er schon belegt ist).
4. „IT-Dokumentation“ erscheint im DSM-Hauptmenü.

Das Paket nutzt das Python der NAS (3.8 bis 3.13). Fehlt es, bricht die Installation mit einem Hinweis ab –
dann im Paket-Zentrum „Python 3.9“ installieren. Die Daten liegen unter `/var/packages/itdoku/var/` und
bleiben bei Updates erhalten. **Beim Deinstallieren werden sie gelöscht** – deshalb die
[Datensicherung](#datensicherung) einrichten.

## Updates über das Paket-Zentrum

Die App ist ihre eigene Paketquelle – neue Releases von GitHub erscheinen im Paket-Zentrum zum Aktualisieren.
Einmalig einrichten:

1. **Paket-Zentrum → Einstellungen → Allgemein → Vertrauensebene:** „Beliebiger Herausgeber“
   (das Paket ist nicht von Synology signiert).
2. **Paket-Zentrum → Einstellungen → Paketquellen → Hinzufügen:** Name `IT-Dokumentation`,
   Ort `http://127.0.0.1:8780/spk` (bei geändertem Port entsprechend – die genaue Adresse steht in der App
   unter **Verwaltung → System → Updates**).

Die App prüft etwa alle 30 Minuten (oder per „Jetzt prüfen“), lädt eine neue SPK auf die NAS und bietet sie dort an.
Die Paketquelle antwortet nur im lokalen Netz.

## Datensicherung

Die App sichert die Datenbank jede Nacht (Standard 2 Uhr) in den Paketordner. Weil DSM diesen Ordner beim
Deinstallieren löscht und Hyper Backup ihn nicht erfasst, gehört zusätzlich ein **freigegebener Ordner** dazu:

1. **Systemsteuerung → Freigegebener Ordner** → z. B. `backup` → **Bearbeiten → Berechtigungen** →
   oben **System-interner Benutzer** wählen → `itdoku` **Lesen/Schreiben** geben.
2. In der App unter **Verwaltung → System → Datensicherung** den Ordner eintragen, z. B.
   `/volume1/backup/itdoku` (die App prüft die Schreibrechte), und die Aufbewahrung in Tagen festlegen.
3. Den freigegebenen Ordner in Hyper Backup aufnehmen.

Sicherungen lassen sich dort auch von Hand erstellen, herunterladen, wiederherstellen und löschen (die neueste ist
geschützt); vor dem Wiederherstellen wird der aktuelle Stand automatisch gesichert. Das **Mail-Passwort wird nicht
mitgesichert**. Den Ordner bitte **nicht für alle freigeben**.

## Von unterwegs erreichbar machen (Reverse Proxy)

Für den Zugriff von außen braucht die App eine eigene https-Adresse, z. B. `https://doku.kundendomain.de`:

1. DNS-Eintrag für die Subdomain auf die NAS zeigen lassen (z. B. CNAME auf die DDNS-Adresse).
2. **Systemsteuerung → Sicherheit → Zertifikat**: Let's-Encrypt-Zertifikat für die Subdomain.
3. **Systemsteuerung → Anmeldeportal → Erweitert → Reverse Proxy**: Quelle `HTTPS doku.kundendomain.de:443`,
   Ziel `HTTP localhost:8780`.
4. In der App unter **Verwaltung → Einstellungen → Öffentliche Adresse** genau diese Adresse eintragen.

Für eine Dokumentation mit Zugangsdaten ist ein **VPN** zur NAS meist die bessere Wahl als eine öffentliche Adresse.
Den Port im Router **nie** direkt freigeben. Greift jemand per `http://` von außerhalb des Heimnetzes zu, zeigt die
App einen Warnhinweis.

## Port ändern

Unter **Verwaltung → System → Port** einen neuen Port eintragen (1025–65535, nicht von DSM belegt). Die App prüft,
ob er frei ist, speichert ihn in `/var/packages/itdoku/var/config.env` und startet sich selbst neu.
Im DSM-Fenster geht es danach einfach weiter. Anpassen musst du nur, was du selbst eingerichtet hast:
die **Paketquelle** im Paket-Zentrum und das **Ziel im Reverse Proxy**.

## Entwicklung

```bash
pip install -r requirements-dev.txt
pytest -q                                    # alle Tests
ITD_DATA_DIR=./data python -m app.main       # startet auf http://localhost:8780
```

Beim ersten Start ohne `ITD_ADMIN_PASSWORD` steht das Admin-Passwort in `data/ERSTES_ADMIN_PASSWORT.txt`.
Die SPK baut `./synology/build_spk.sh` (lädt die Abhängigkeiten für Python 3.8–3.13 und alle Prozessoren von PyPI).

- **Technik:** Python + FastAPI + SQLite, statisches HTML/CSS/JS ohne Build-Schritt, keine nativen Bibliotheken.
  Das Fundament stammt aus [Zeitmanagement](https://github.com/rinkelzz/zeitmanagement) (MIT).
- **Datenbank-Migrationen** über `PRAGMA user_version` in `app/db.py`: Neue Tabellen und Spalten kommen immer als
  neuer, nummerierter Schritt dazu; jeder Schritt läuft in einer eigenen Transaktion. Die Tests spielen jede
  Ausgangsversion durch.
- **Tests** laufen bei jedem Push auf Python 3.8 und 3.13 (GitHub Actions „Tests“).
- **Release:** Version in `app/__init__.py` und `CHANGELOG.md` eintragen, pushen, dann
  **Actions → Release → Run workflow** – baut die SPK und legt das GitHub-Release an.

## Lizenz

[MIT](LICENSE) – frei nutzbar, auch kommerziell. Gefällt dir die App? [Spendier mir einen Kaffee ☕](https://buymeacoffee.com/lapalutschi)

## English

**IT-Dokumentation** is a lean, self-hosted alternative to IT Glue for Synology NAS (DSM 7): per-customer IT
documentation – sites, contacts, devices, licenses, network plan and credentials in an encrypted vault – stored on the
customer's own NAS, in its own DSM window with single sign-on. The user interface is German.

- One noarch package for Intel/AMD and ARM, no native libraries; uses the NAS's Python 3.8–3.13.
- 0.1 (foundation): DSM login incl. 2FA, users with full or read-only access, company name and logo, four themes,
  nightly backups to a shared folder (for Hyper Backup), updates through Package Center, audit log, configurable port.
- 0.2 (documentation): overview with upcoming expiries and emergency contacts, devices with custom types, links,
  attachments and history, networks/VLANs with IP list and network diagram, internet connection, licenses incl.
  domains and certificates, contacts, global search.
- 0.3 (vault): credentials (password, notes, TOTP secret) and license keys encrypted with a random data key
  (AES-256-CTR + HMAC-SHA-256, pure Python), wrapped per user with a vault password (PBKDF2) and with a printable
  recovery key; invitation codes, auto-lock, audited show/copy, password generator, TOTP codes.
- 0.4: weekly expiry digest plus reminders 14 days before and on the day, emergency handbook PDF (contacts, internet,
  networks, IP lists, diagram – no passwords), CSV import for devices with column mapping and preview.
- 0.5: network scan without root (TCP probes, ARP, DNS/NetBIOS): adopt new devices, fill in MAC/hostname, MAC mismatches,
  “last seen”, nightly scans.
- 0.6: agent for servers and PCs (Windows PowerShell, Linux and macOS via Python standard library): daily HTTPS report
  of hardware, OS, disks, network, installed software, pending updates and services, per-agent key; devices are matched
  by serial number or host name or created; silent agents are flagged on the overview and in the weekly mail.
- Planned: wiki pages, link to the Zeitmanagement helpdesk.

Install: download the `.spk` from [Releases](https://github.com/rinkelzz/it-doku/releases) →
Package Center → Manual Install. Security notes: [SECURITY.md](SECURITY.md). License: MIT.

Like it? [Buy me a coffee ☕](https://buymeacoffee.com/lapalutschi)
