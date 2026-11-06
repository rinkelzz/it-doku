# Änderungen

Alle nennenswerten Änderungen an diesem Projekt. Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

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

[0.1.0]: https://github.com/rinkelzz/it-doku/releases/tag/v0.1.0
