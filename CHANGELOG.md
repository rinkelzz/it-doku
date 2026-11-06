# Änderungen

Alle nennenswerten Änderungen an diesem Projekt. Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.8.2] – 2026-11-06

### Neu
- **Doppelte Geräte zusammenführen:** Am Gerät erscheint ein Hinweis „Möglicherweise doppelt erfasst“, wenn ein anderes
  Gerät dieselbe MAC-Adresse, Seriennummer oder denselben Namen/Hostnamen hat; außerdem gibt es den Knopf ⇄. Das
  gewählte Gerät geht im aktuellen auf: IP-Adressen, Lizenzen, Verbindungen, Zugangsdaten, Anhänge, Web-Adressen und
  ein Agent wandern mit, leere Felder werden ergänzt, Notizen angehängt – in einer Transaktion, mit Verlauf.

### Behoben
- Ein neuer Agent findet ein vom **Netzwerk-Scan** angelegtes Gerät jetzt auch über die **MAC-Adresse** (vorher nur über
  Seriennummer und Name – ein Scan-Gerät ohne Hostnamen wurde dadurch doppelt angelegt). IP-Adressen ohne Gerät übernimmt
  der Agent für sein Gerät.

## [0.8.1] – 2026-11-06

### Behoben
- **„Läuft seit“ bei Windows-Schnellstart:** Herunterfahren ist bei aktivem Schnellstart eigentlich Ruhezustand, die
  Startzeit bleibt deshalb alt („4 Tage“, obwohl der PC gerade eingeschaltet wurde). Der Windows-Agent (1.1) liest jetzt
  das letzte Einschalten aus dem System-Protokoll (Kernel-Boot 27); die App zeigt „eingeschaltet …“ und daneben den
  letzten echten Neustart – wichtig, weil Updates erst nach „Neu starten“ greifen.
- **Selbst gebaute PCs:** Platzhalter wie „To Be Filled By O.E.M.“ oder „System Product Name“ bei Hersteller, Modell
  und Seriennummer werden verworfen; stattdessen kommen Hersteller und Modell des Mainboards (z. B. „ASRock B550 Pro4“).
  Schon gespeicherte Platzhalter am Gerät werden beim nächsten Bericht ersetzt.
- „1 ausstehendes Update“ statt „1 ausstehende Updates“.

## [0.8.0] – 2026-11-06

### Neu
- **Agent scannt das Netz vor Ort** – für entfernte Standorte ohne VPN. Am Netz unter **„Gescannt von“** einen Linux-,
  macOS- oder Synology-Agenten wählen. Der Agent scannt dort mit demselben Verfahren wie die NAS (TCP-Proben, MAC und
  Hersteller aus der ARP-Tabelle, Namen aus DNS/NetBIOS) und schickt das Ergebnis per HTTPS. Es landet im gewohnten
  **🔍 Scan**: neue Geräte übernehmen, ergänzen, Abweichungen, zuletzt online.
- Der Agent **fragt stündlich nach** (`--auto`): Bericht einmal am Tag, Scan einmal am Tag oder sofort, wenn in der App
  „Jetzt scannen“ gedrückt wurde („angefordert“). Netze mit Agent scannt die NAS selbst nicht mit.
- **Synology DSM als Agent:** Modell, Seriennummer, DSM-Version mit Update-Stand, Volumes und installierte Pakete.
  Einrichten per SSH (Befehl unter „Synology“ im Einrichtungsdialog), Zeitplan im DSM-Aufgabenplaner, Dateien unter
  `/usr/local/itdoku-agent`.
- Scan-Ansicht: je Netz der zuständige Scanner, letzter Scan und „angefordert“; Netz-Karte und Agentenliste zeigen,
  wer welches Netz scannt.
- CI: Linux- und macOS-Agent scannen im Ende-zu-Ende-Test ein zugeordnetes Netz.

### Geändert
- Agent 1.1: Zeitplan stündlich statt täglich (Bericht bleibt täglich). Mit 1.0 eingerichtete Agenten laufen weiter;
  für den Scan vor Ort einmal neu einrichten.
- Je Netz zählt im Scan-Ergebnis der jüngste Lauf seines Scanners; alte Läufe werden aufgeräumt, der letzte jedes
  Scanners bleibt.

## [0.7.0] – 2026-11-06

### Neu
- **Web-Oberflächen pro Gerät:** beliebig viele Web-Adressen mit Bezeichnung (z. B. „DSM“, „Vaultwarden“,
  „Proxmox“). Am Gerät als Knöpfe oben und im Abschnitt „Web-Oberflächen“ (hinzufügen, ändern, entfernen – mit
  Verlauf); in der Geräteliste als ↗ hinter dem Namen; die Suche findet Geräte auch über Adresse und Bezeichnung.
- **Hostname in der IP-Liste anklickbar** – öffnet die Web-Adresse des Geräts in einem neuen Tab. Ohne eigene
  Adresse baut die App den Link aus den Web-Ports, die der Netzwerk-Scan gefunden hat (443/8443/5001/8006/9443 als
  https, 80/8080/8123/5000 als http; Hostname, wenn er voll qualifiziert ist, sonst die IP) – gestrichelt markiert.
- Am Gerät schlägt „Gefunden:“ solche Adressen zum Übernehmen mit einem Klick vor.
- Netzwerk-Scan prüft zusätzlich die Ports 8006 (Proxmox), 8123 (Home Assistant) und 9443.
- Nur `http://` und `https://` werden angenommen (kein `javascript:` o. ä.); Links öffnen mit `noopener noreferrer`.

## [0.6.3] – 2026-11-06

### Geändert
- **Agent-Adresse im LAN ist voreingestellt:** automatisch `http://<IP der NAS>:<Port>` (bei Bedarf überschreibbar).
  Daneben optional eine Adresse „von außen“ (https über Reverse Proxy). Beim Einrichten eines Agenten wählst du
  „Im LAN / VPN“ oder „Von außen“, der Befehl passt sich an.

## [0.6.2] – 2026-11-06

### Neu
- **Eigener Reverse Proxy** (Verwaltung → System): IP-Adresse(n) eines Proxys auf einem anderen Gerät eintragen,
  z. B. Nginx Proxy Manager mit Portweiterleitung. Von dort übernimmt die App die echte Absender-Adresse aus
  `X-Forwarded-For` – für die Sperre gegen Durchprobieren (Login und Agent-Schlüssel pro Absender statt für alle
  gemeinsam), das Protokoll, die Anzeige „von Adresse“ bei Agenten und die nur im LAN erreichbare Paketquelle.
  Die Seite zeigt, woher die aktuelle Anfrage kommt, und warnt, wenn offensichtlich ein nicht eingetragener Proxy
  davorsitzt. Alternativ per `ITD_TRUSTED_PROXIES`.
- README: Anleitung für Nginx Proxy Manager, auch „nur Agenten von außen durchlassen“.

## [0.6.1] – 2026-11-06

### Neu
- **Spalten sortieren:** Klick auf einen Spaltenkopf sortiert die Listen Geräte, IP-Adressen, Lizenzen und Agenten
  (zweiter Klick absteigend, dritter wieder wie geliefert). IP-Adressen werden richtig der Zahl nach sortiert
  (…10.9 vor …10.77), Daten nach Datum. Die Sortierung bleibt im Browser gespeichert.
- **Geräte benennen direkt in der IP-Liste:** Geräte, die nur eine IP- oder MAC-Adresse als Namen haben (z. B. vom
  Netzwerk-Scan ohne Hostnamen), sind kursiv markiert und haben einen ✎-Knopf; bei allen anderen erscheint er beim
  Überfahren. Name und Typ lassen sich dort ändern, ein bekannter Hostname wird vorgeschlagen.
- Solche Geräte bekommen ihren Namen automatisch, sobald der Netzwerk-Scan einen Hostnamen findet und man ihn
  übernimmt, oder sobald ein Agent seinen Rechnernamen meldet. Von Hand vergebene Namen bleiben unangetastet.

## [0.6.0] – 2026-11-06

### Neu
- **Agent für Server und PCs** – Windows (PowerShell 5.1, ohne Zusatzmodule), Linux und macOS (Python 3, nur
  Standardbibliothek). Meldet sich täglich und nach jedem Start per HTTPS mit eigenem Schlüssel pro Agent; am Server
  muss kein Port offen sein. Erreichbar über Reverse Proxy (https) oder intern per VPN.
- Gemeldet werden Rechnername, Betriebssystem mit Build, CPU, Arbeitsspeicher, Hersteller/Modell/Seriennummer, Laufzeit,
  Datenträger mit freiem Platz, Netzwerkkarten, Gateway und DNS, installierte Software, ausstehende Updates samt
  „Neustart nötig“ und Dienste.
- **Am Gerät:** Abschnitt „🛰️ Vom Agent gemeldet“ mit Datenträger-Balken, auffälligen Diensten (Autostart, aber
  gestoppt), durchsuchbarer Software-Liste und CSV-Export; Karte „Agent“ mit letztem Bericht.
- **Gerät finden oder anlegen:** über Seriennummer, dann Rechnername; sonst neu mit passendem Typ und Standort.
  Betriebssystem wird nachgezogen, leere Felder ergänzt, Handarbeit bleibt. IPv4-Adressen aus dokumentierten Netzen
  kommen in die IP-Liste.
- **Verwaltung → 🛰️ Agenten:** Agenten anlegen (Schlüssel wird nur einmal angezeigt), Einrichtungsbefehl für Windows,
  Linux und macOS zum Kopieren, neuer Schlüssel, sperren, löschen; Adresse für Agenten und „still nach“ einstellbar.
- **Stille Agenten** (Standard: 3 Tage ohne Bericht) auf der Übersicht, am Gerät und in der Fristen-Mail – die
  Sammel-Mail kommt dann auch, wenn keine Frist ansteht.
- CI testet die Agenten echt auf Windows, macOS und Linux (Bericht senden und Einrichten des Zeitplans).

## [0.5.0] – 2026-11-06

### Neu
- **Netzwerk-Scan** (Netzwerk → 🔍 Scan): prüft Netze mit Haken „beim Netzwerk-Scan berücksichtigen“ (IPv4, höchstens /22)
  – von Hand oder jede Nacht (Uhrzeit wählbar). Ohne Root-Rechte und ohne Zusatzprogramme: TCP-Verbindungsversuche auf
  gängige Ports (auch eine Ablehnung zeigt, dass ein Gerät da ist), MAC-Adressen aus der ARP-Tabelle der NAS, Namen aus
  DNS und NetBIOS, Hersteller aus dem MAC-Präfix.
- **Neu gefunden:** unbekannte Adressen mit Name, MAC, Hersteller und offenen Ports; Gerätetyp wird geraten (z. B. Drucker
  bei Port 9100, NAS bei 5000/5001, PC bei RDP/SMB, Handy bei zufälliger MAC) und lässt sich vor dem Anlegen ändern.
  Mehrere auf einmal **als Geräte anlegen** oder **ignorieren**.
- **Ergänzen:** fehlende MAC-Adressen und Hostnamen bekannter IPs mit einem Klick übernehmen.
- **Abweichungen:** bekannte IP mit anderer MAC (Gerätetausch oder doppelt vergebene IP) – neue MAC übernehmen oder ignorieren.
- **Länger nicht gesehen:** aktive Geräte, die über 30 Tage nicht erreichbar waren – auf Wunsch als ausgemustert markieren.
- IP-Liste mit Punkt und Spalte **„zuletzt online“**, Hinweis auf der **Übersicht** und in der **Fristen-Mail**, wenn
  der Scan unbekannte Geräte gefunden hat.

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

[0.5.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.5.0
[0.4.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.4.0
[0.3.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.3.0
[0.2.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.2.0
[0.1.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.1.0
