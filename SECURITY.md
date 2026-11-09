# Sicherheit

Bitte Sicherheitslücken **nicht** als öffentliches Issue melden, sondern über
[GitHub → Security → Report a vulnerability](https://github.com/rinkelzz/it-doku/security/advisories/new).
Ich melde mich so schnell wie möglich.

Unterstützt wird jeweils die neueste Version unter [Releases](https://github.com/rinkelzz/it-doku/releases).

## Was die App selbst absichert

- **Passwörter** werden mit PBKDF2-SHA256 (200 000 Runden, eigenes Salz) gespeichert, Sitzungen nur als
  SHA-256-Hash. Beim Passwortwechsel und beim Deaktivieren eines Benutzers enden alle seine Sitzungen.
- **Login-Sperre:** 5 Fehlversuche pro Benutzername und Adresse, 10 pro Benutzername insgesamt und 30 pro Adresse
  (gleich welcher Name) – jeweils 15 Minuten. Die Tabelle ist in der Größe begrenzt (50 000 Einträge), Abgelaufenes
  wird regelmäßig entfernt, und bloßes Nachsehen legt keine Einträge an.
- **Kein http aus dem Netz (Standard):** Die Weboberfläche gibt es nur über das DSM-Fenster, über die NAS selbst
  (DSM-Reverse-Proxy) und über https (auch über einen eingetragenen eigenen Reverse Proxy). Direkte http-Zugriffe aus
  dem Netz bekommen eine Hinweisseite; nur Agenten, Agent-Skripte, Paketquelle und Statuscheck bleiben erreichbar.
  Einschaltbar unter Verwaltung → System → Zugriff bzw. `ITD_HTTP_ACCESS=1`. Die App lauscht weiter auf allen
  Schnittstellen (`ITD_HOST=0.0.0.0`), weil Agenten im LAN und ein Reverse Proxy auf einem anderen Gerät sie erreichen
  müssen; wer beides nicht braucht, setzt `ITD_HOST=127.0.0.1` in der Paketkonfiguration.
- **CSRF:** Änderungen per Login-Cookie werden nur von der eigenen Seite angenommen (`Sec-Fetch-Site`
  bzw. `Origin`/`Referer`). Läuft die App hinter einem Proxy, der den `Host`-Header umschreibt, die
  **Öffentliche Adresse** in den Einstellungen eintragen.
- **DSM-Konten:** Per Single Sign-on kommen standardmäßig nur DSM-Administratoren und vom Admin angelegte Benutzer
  hinein. Unbekannte DSM-Konten werden nicht automatisch angelegt (einschaltbar, dann nur mit Lesezugriff).
  Ob jemand DSM-Administrator ist, prüft die App selbst (Gruppe `administrators`) – ein mitgeschickter Header zählt
  nicht. Vollzugriff, der nur aus DSM kam, wird wieder entzogen, sobald die Person kein DSM-Administrator mehr ist
  oder „DSM-Administratoren bekommen Vollzugriff“ ausgeschaltet wird; von Hand vergebener Vollzugriff bleibt.
- **DSM-Passwortprüfung** nur gegen die DSM-Anmeldung der NAS selbst: `http://127.0.0.1:5000` oder
  `https://127.0.0.1:5001` (andere Ports nur per `ITD_DSM_PORTS` in der Paketkonfiguration, nicht über die Oberfläche),
  ohne Proxy-Umgebungsvariablen und ohne Weiterleitungen. DSM-Passwörter verlassen die NAS nie und gehen an keinen
  anderen Dienst. Bei https über Loopback wird das Zertifikat nicht geprüft (DSM nutzt dort meist ein nicht auf
  127.0.0.1 ausgestelltes Zertifikat); die Verbindung verlässt die NAS nicht.
- **Single Sign-on im DSM-Fenster:** Der Schlüssel (`.proxy_secret` im Paketordner) wird nur von
  Verbindungen über 127.0.0.1 ohne `X-Forwarded-For` angenommen, also nur von `app.cgi` auf der NAS selbst.
  Er wird bei jedem Start neu erzeugt. `app.cgi` läuft als Paketbenutzer (auf einer NAS mit DSM 7 geprüft), die
  Datei ist deshalb nur für ihn lesbar (Modus 0600). Lässt sich das nicht setzen, bleibt sie für alle lokalen Benutzer
  der NAS lesbar – die Verwaltung zeigt dann einen Hinweis.
  **Restrisiko:** Wer auf der NAS Programme als Paketbenutzer oder root ausführen kann, kann den Schlüssel
  lesen und sich als beliebiger DSM-Benutzer ausgeben. Wer das ausschließen will, schaltet unter
  Verwaltung → System die **Anmeldung im DSM-Fenster** aus; der Schlüssel wird dann gelöscht und nicht mehr angenommen.
- **Echte Absenderadresse** (`X-Forwarded-For`) wird nur übernommen, wenn die Anfrage vom Reverse Proxy
  auf derselben NAS (127.0.0.1) kommt oder von einem Proxy, der unter **Verwaltung → System → Eigener Reverse Proxy**
  (bzw. `ITD_TRUSTED_PROXIES`) eingetragen ist. Bei einer Kette zählt von rechts die erste Adresse, die selbst kein
  eingetragener Proxy ist; Einträge, die ein Client selbst mitschickt, bleiben wirkungslos. Netze weiter als /16
  werden nicht angenommen. Ist ein Proxy auf einem anderen Gerät **nicht** eingetragen, sieht die App nur dessen
  Adresse: Login- und Agent-Sperre treffen dann alle gemeinsam, und die Paketquelle hält Zugriffe übers Internet für
  lokal.
- **Keine Klartext-Zugangsdaten in Sicherungen:** Das SMTP-Passwort wird vor dem Sichern entfernt (inklusive
  `VACUUM`, damit es auch nicht in freien Seiten der Datei steht). Der Tresor liegt darin nur verschlüsselt.
- **Anhänge** (Netzwerkplan, Rechnungen, Fotos): nur PNG, JPG und PDF, erkannt am **Inhalt** (SVG/HTML werden
  abgelehnt), höchstens 10 MB, schon beim Empfang begrenzt. Hochladen und Löschen nur mit Vollzugriff. Ausgeliefert
  mit `X-Content-Type-Options: nosniff` und `Content-Security-Policy: sandbox`; PDFs immer als Download.
- **Lesezugriff:** Alle ändernden Schnittstellen verlangen Vollzugriff – auch wenn die Oberfläche die Knöpfe
  ohnehin ausblendet.
- **CSV-Exporte** entschärfen Zellen, die mit `=`, `+`, `-`, `@`, Tab oder CR beginnen (Formel-Injection).
- **Paketquelle** (`/spk`) nur aus dem lokalen Netz erreichbar.

## Netzwerk-Scan

- Gescannt werden nur Netze, bei denen jemand mit Vollzugriff „beim Netzwerk-Scan berücksichtigen“ angehakt hat (IPv4,
  höchstens /22). Der Scan versucht TCP-Verbindungen zu 21 gängigen Ports und fragt NetBIOS/DNS-Namen ab – keine Anmeldung,
  keine Exploits, kein Root. Bitte nur Netze scannen, für die du beauftragt bist; manche Sicherheitssysteme melden Scans.
- Starten, Ergebnisse sehen und übernehmen nur mit Vollzugriff.

## Agenten

- Jeder Agent hat einen eigenen Schlüssel (`itd_` + 256 Bit Zufall). Gespeichert wird nur dessen SHA-256; angezeigt wird
  er genau einmal beim Anlegen bzw. Erneuern. Ein neuer Schlüssel macht den alten sofort ungültig, gesperrte Agenten
  werden abgelehnt.
- Ein Agent kann **nur Berichte abliefern** – nichts lesen, nichts ändern außer „seinem“ Gerät (Betriebssystem, leere
  Felder, IP-Adressen aus dokumentierten Netzen). Kein Befehl läuft vom Server zum Agenten zurück.
- Berichte sind auf 4 MB begrenzt und werden vor dem Speichern auf bekannte Felder und Längen beschnitten. Nach 20
  ungültigen Schlüsseln von einer Adresse ist 15 Minuten Pause.
- Auf dem Rechner liegt der Schlüssel in `/etc/itdoku-agent.conf` (nur root) bzw. `C:\ProgramData\ITDoku` (nur SYSTEM
  und Administratoren). Der Agent läuft als root/SYSTEM, weil Seriennummer, Updates und Dienste sonst nicht lesbar sind.
- Unverschlüsseltes `http://` muss beim Einrichten ausdrücklich bestätigt werden – nur im VPN/LAN verwenden.
  Zertifikatsprüfung abschalten (`--insecure`) nur bei selbstsignierten Zertifikaten im eigenen Netz.
- Die Skripte unter `/agent/…` enthalten keine Geheimnisse und sind ohne Anmeldung abrufbar.
- **Windows-Produktschlüssel:** Der Tresor hat ein X25519-Schlüsselpaar; der private Schlüssel liegt nur mit dem
  Tresor-Schlüssel verschlüsselt vor. Ein vom Agent gemeldeter Produktschlüssel wird beim Eingang sofort versiegelt
  (einmaliges Schlüsselpaar → X25519 → HKDF-SHA256 → AES-256-CTR + HMAC, gebunden an die Lizenz) und nie im Klartext
  gespeichert – weder in der Datenbank noch im Bericht noch in der Sicherung. Der Agent schickt ihn nur, wenn die App
  ihn sofort versiegeln kann. Auf dem Weg vom Agenten zur App schützt ihn nur die Verbindung: über `http` im LAN ist er
  mitlesbar – dafür https verwenden oder das Auslesen unter Verwaltung → Agenten abschalten.
- **Selbstupdate der Agenten:** Ein Agent lädt neue Versionen nur von der IT-Dokumentation, bei der er eingerichtet
  ist, prüft die SHA-256-Prüfsumme aus der (per Schlüssel angemeldeten) Nachfrage und ersetzt nur die eingerichtete
  Datei. Die Skripte stammen aus dem Paket und lassen sich über die Oberfläche nicht ändern – wer sie austauschen
  will, braucht Root auf der NAS. Abschaltbar unter Verwaltung → Agenten.
- **Scan vor Ort:** Ein Agent scannt nur Netze, die ihm in der App ausdrücklich zugeordnet sind, und darf nur für diese
  Ergebnisse abliefern; Adressen außerhalb des Netzes werden verworfen. Wird ein Agent gelöscht, wird das Scannen seiner
  Netze ausgeschaltet – sonst würde die NAS ein fremdes Netz mit womöglich gleichen Adressen in ihrem eigenen LAN suchen.

## Tresor

- Zugangsdaten (Passwort, Notiz, 2FA-Geheimnis) und Lizenzschlüssel werden mit einem zufälligen 256-Bit-Datenschlüssel
  verschlüsselt: AES-256-CTR mit zufälliger Nonce, HMAC-SHA-256 über Version, Nonce, Geheimtext und Feldkennung
  (Encrypt-then-MAC; getrennte Schlüssel für Verschlüsselung und HMAC). Die Feldkennung (z. B. `cred:12:password`)
  verhindert, dass Geheimtexte zwischen Einträgen vertauscht werden. AES ist in reinem Python umgesetzt (keine nativen
  Bibliotheken) und wird gegen die Testvektoren aus FIPS-197 und NIST SP 800-38A geprüft.
- Der Datenschlüssel liegt nur verschlüsselt in der Datenbank: pro Benutzer mit dessen **Tresor-Passwort**
  (PBKDF2-SHA-256, 600 000 Runden, eigenes Salz), mit dem **Notfall-Schlüssel** (256 Bit) und befristet mit
  **Einladungscodes** (80 Bit, 7 Tage). Tresor-Passwörter, Notfall-Schlüssel und Codes werden nirgends gespeichert.
- Geöffnet liegt der Datenschlüssel nur im Arbeitsspeicher der App, gebunden an die Sitzung, und verfällt nach X Minuten
  ohne Aktivität, beim Sperren, Abmelden, Wiederherstellen einer Sicherung und beim Neustart. Im DSM-Fenster (Single
  Sign-on) gehört der offene Tresor zum DSM-Benutzer, gilt also für alle seine DSM-Fenster.
- Solange der Tresor offen ist, könnte jemand mit Root-Zugriff auf die NAS den Schlüssel aus dem Speicher lesen. Der
  Tresor schützt vor allem Datenbankdatei, Sicherungen und Benutzer ohne Tresor-Zugang.
- Entsperren, Einladung und Notfall-Schlüssel: höchstens 5 Fehlversuche in 15 Minuten, jeder Fehlversuch steht im
  Protokoll. Jedes Anzeigen und Kopieren eines Geheimnisses wird mit Benutzer und Zeitpunkt protokolliert.
- Benutzer mit **Lesen** bekommen keine Zugangsdaten – weder über die Oberfläche noch über die Schnittstelle, die Suche
  oder „Zuletzt geändert“. Wer den Vollzugriff verliert oder deaktiviert wird, verliert sofort den Tresor-Zugang.
- **Zugang entziehen wechselt den Datenschlüssel nicht.** Wer früher Zugang hatte und eine alte Sicherung samt
  seinem damaligen Tresor-Passwort besitzt, könnte die darin enthaltenen Einträge lesen. Nach dem Entziehen deshalb die
  wichtigen Passwörter ändern.
- Der Passwort-Generator läuft im Browser (`crypto.getRandomValues`, ohne Verzerrung).

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
