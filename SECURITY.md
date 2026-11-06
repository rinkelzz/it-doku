# Sicherheit

Bitte Sicherheitslücken **nicht** als öffentliches Issue melden, sondern über
[GitHub → Security → Report a vulnerability](https://github.com/rinkelzz/it-doku/security/advisories/new).
Ich melde mich so schnell wie möglich.

Unterstützt wird jeweils die neueste Version unter [Releases](https://github.com/rinkelzz/it-doku/releases).

## Was die App selbst absichert

- **Passwörter** werden mit PBKDF2-SHA256 (200 000 Runden, eigenes Salz) gespeichert, Sitzungen nur als
  SHA-256-Hash. Beim Passwortwechsel und beim Deaktivieren eines Benutzers enden alle seine Sitzungen.
- **Login-Sperre:** 5 Fehlversuche pro Benutzername und Adresse, 10 pro Benutzername insgesamt – jeweils
  15 Minuten. Die Tabelle ist in der Größe begrenzt, sie lässt sich nicht volllaufen lassen.
- **CSRF:** Änderungen per Login-Cookie werden nur von der eigenen Seite angenommen (`Sec-Fetch-Site`
  bzw. `Origin`/`Referer`). Läuft die App hinter einem Proxy, der den `Host`-Header umschreibt, die
  **Öffentliche Adresse** in den Einstellungen eintragen.
- **DSM-Konten:** Per Single Sign-on kommen standardmäßig nur DSM-Administratoren und vom Admin angelegte Benutzer
  hinein. Unbekannte DSM-Konten werden nicht automatisch angelegt (einschaltbar, dann nur mit Lesezugriff).
- **DSM-Passwortprüfung** nur gegen die NAS selbst (`127.0.0.1`, `localhost`, `::1` – der Hostname wird
  exakt geprüft), ohne Proxy-Umgebungsvariablen und ohne Weiterleitungen. DSM-Passwörter verlassen die NAS nie.
- **Single Sign-on im DSM-Fenster:** Der Schlüssel (`.proxy_secret` im Paketordner) wird nur von
  Verbindungen über 127.0.0.1 ohne `X-Forwarded-For` angenommen, also nur von `app.cgi` auf der NAS selbst.
- **Echte Absenderadresse** (`X-Forwarded-For`) wird nur übernommen, wenn die Anfrage vom Reverse Proxy
  auf derselben NAS (127.0.0.1) kommt. Bei einem Proxy auf einem anderen Gerät sieht die App dessen Adresse –
  die Login-Sperre greift dann nur noch pro Benutzername.
- **Keine Klartext-Zugangsdaten in Sicherungen:** Das SMTP-Passwort wird vor dem Sichern entfernt (inklusive
  `VACUUM`, damit es auch nicht in freien Seiten der Datei steht). Der Tresor (ab 0.3) liegt darin nur verschlüsselt.
- **CSV-Exporte** entschärfen Zellen, die mit `=`, `+`, `-`, `@`, Tab oder CR beginnen (Formel-Injection).
- **Paketquelle** (`/spk`) nur aus dem lokalen Netz erreichbar.

## Tresor (ab Version 0.3)

- Zugangsdaten und Lizenzschlüssel werden mit einem zufälligen Datenschlüssel verschlüsselt (AES-256-CTR mit
  HMAC-SHA-256 als Echtheitsprüfung, reines Python). Der Datenschlüssel liegt nur verschlüsselt in der Datenbank:
  einmal pro Benutzer mit dessen **Tresor-Passwort** (PBKDF2-SHA-256) und einmal mit dem **Notfall-Schlüssel**.
- Tresor-Passwörter und Notfall-Schlüssel werden nirgends gespeichert. Wer beides verliert, verliert die
  Zugangsdaten. Den Notfall-Schlüssel deshalb ausgedruckt sicher verwahren.
- Der entschlüsselte Datenschlüssel liegt nur im Arbeitsspeicher der App und gehört zur Sitzung. Nach einiger Zeit
  ohne Aktivität sperrt sich der Tresor. Solange er offen ist, könnte jemand mit Root-Zugriff auf die NAS ihn aus dem
  Speicher lesen – der Tresor schützt vor allem Datenbankdatei und Sicherungen.
- Benutzer mit **Lesen** sehen nie Zugangsdaten oder Lizenzschlüssel.
- Jedes Anzeigen und Kopieren eines Passworts wird protokolliert.

## Hinweise für den Betrieb

- Für eine Dokumentation mit Zugangsdaten ist ein **VPN** zur NAS meist besser als eine öffentliche Adresse. Wenn
  doch von außen, dann nur per **HTTPS** (Reverse Proxy von DSM mit Zertifikat), nie den Port (Standard 8780)
  direkt. Bei Zugriff per `http://` aus dem Internet zeigt die App eine Warnung.
- **Vollzugriff** nur an Personen geben, die ihn wirklich brauchen (z. B. IT-Dienstleister und eine Vertrauensperson
  beim Kunden). DSM-Administratoren haben ihn standardmäßig – unter Verwaltung → Einstellungen abschaltbar.
- Updates kommen aus den GitHub-Releases dieses Repos. Sie sind nicht zusätzlich signiert – geschützt
  sind sie durch HTTPS und das (per Zwei-Faktor gesicherte) GitHub-Konto des Maintainers.
- Das SMTP-Passwort liegt in der Datenbank der App (`/var/packages/itdoku/var/`), lesbar nur für
  den Paketbenutzer. Am besten ein eigenes Mail-Konto oder App-Passwort nur für den Versand verwenden.
- Den freigegebenen Ordner für Sicherungen nicht für alle Benutzer freigeben – die Sicherungen enthalten
  alle Daten und die Passwort-Hashes.

# Security (English)

Please report vulnerabilities privately via GitHub's *Report a vulnerability* button, not as a public issue.
