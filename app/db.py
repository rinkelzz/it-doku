"""SQLite-Datenbank: Schema, schrittweise Migrationen (PRAGMA user_version) und Verbindungen.

Neue Tabellen oder Spalten kommen IMMER als neuer Migrationsschritt dazu – bestehende Schritte
werden nie verändert. So kommt jede Datenbank (auch eine alte Sicherung) Schritt für Schritt
auf den aktuellen Stand, ohne dass Daten verloren gehen.
"""
import secrets
import sqlite3
from typing import Callable, Dict, Iterator

from .config import settings
from .timeutil import now_utc_str


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _run(conn: sqlite3.Connection, script: str) -> None:
    """Mehrere Anweisungen einzeln ausführen (executescript würde die laufende Transaktion beenden)."""
    for stmt in script.split(";\n"):
        if stmt.strip():
            conn.execute(stmt)


def _m1_basis(conn: sqlite3.Connection) -> None:
    """Version 0.1: Benutzer, Sitzungen, Änderungsprotokoll, Einstellungen."""
    _run(conn, """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    email         TEXT,
    password_hash TEXT,                       -- NULL = Anmeldung nur mit DSM-Konto
    is_admin      INTEGER NOT NULL DEFAULT 0, -- 1 = Vollzugriff (auch Tresor), 0 = nur lesen, ohne Zugangsdaten
    active        INTEGER NOT NULL DEFAULT 1,
    theme         TEXT,                       -- eigenes Design, NULL = Standard der Firma
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    actor_id  INTEGER,
    action    TEXT NOT NULL,
    target    TEXT,
    details   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS app_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
""")


DEVICE_TYPES = [  # vorbelegt, in der Verwaltung frei änderbar
    ("PC", "🖥️"), ("Laptop", "💻"), ("NAS / Server", "🗄️"), ("Drucker", "🖨️"), ("Switch", "🔀"),
    ("Router / Firewall", "🌐"), ("Access Point", "📶"), ("Telefon / TK-Anlage", "☎️"), ("Kartenterminal", "💳"),
    ("Smartphone / Tablet", "📱"), ("Sonstiges", "📦"),
]


def _m2_stammdaten(conn: sqlite3.Connection) -> None:
    """Version 0.2: Standorte, Ansprechpartner, Gerätetypen, Geräte, Netze, IP-Adressen, Lizenzen, Anhänge."""
    _run(conn, """
CREATE TABLE IF NOT EXISTS sites (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    address          TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    isp_provider     TEXT NOT NULL DEFAULT '',   -- Internetanschluss
    isp_tariff       TEXT NOT NULL DEFAULT '',
    isp_public_ip    TEXT NOT NULL DEFAULT '',
    isp_customer_no  TEXT NOT NULL DEFAULT '',
    isp_notes        TEXT NOT NULL DEFAULT '',
    sort             INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    company      TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL DEFAULT '',
    phone        TEXT NOT NULL DEFAULT '',
    mobile       TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    website      TEXT NOT NULL DEFAULT '',
    customer_no  TEXT NOT NULL DEFAULT '',     -- Kundennummer beim Dienstleister
    notes        TEXT NOT NULL DEFAULT '',
    external     INTEGER NOT NULL DEFAULT 0,   -- externer Dienstleister
    emergency    INTEGER NOT NULL DEFAULT 0,   -- „Im Notfall anrufen“
    site_id      INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS device_types (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    icon  TEXT NOT NULL DEFAULT '📦',
    sort  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS devices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    type_id         INTEGER NOT NULL REFERENCES device_types(id) ON DELETE RESTRICT,
    site_id         INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    room            TEXT NOT NULL DEFAULT '',
    manufacturer    TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    serial          TEXT NOT NULL DEFAULT '',
    inventory_no    TEXT NOT NULL DEFAULT '',
    os              TEXT NOT NULL DEFAULT '',
    used_by         TEXT NOT NULL DEFAULT '',
    purchased_on    TEXT,                       -- YYYY-MM-DD
    purchased_from  TEXT NOT NULL DEFAULT '',
    warranty_until  TEXT,                       -- YYYY-MM-DD
    status          TEXT NOT NULL DEFAULT 'active',   -- active | stock | retired
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_site ON devices(site_id, status);
CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(type_id);

CREATE TABLE IF NOT EXISTS device_links (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id    INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    b_id    INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    note    TEXT NOT NULL DEFAULT '',            -- z. B. „Port 7“
    CHECK (a_id <> b_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_links_pair ON device_links(a_id, b_id);
CREATE INDEX IF NOT EXISTS idx_links_b ON device_links(b_id);

CREATE TABLE IF NOT EXISTS networks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id    INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    name       TEXT NOT NULL,
    vlan       INTEGER,
    cidr       TEXT NOT NULL DEFAULT '',        -- z. B. 192.168.10.0/24
    gateway    TEXT NOT NULL DEFAULT '',
    dhcp_from  TEXT NOT NULL DEFAULT '',
    dhcp_to    TEXT NOT NULL DEFAULT '',
    dns        TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    sort       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS ip_addresses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id  INTEGER REFERENCES networks(id) ON DELETE CASCADE,
    ip          TEXT NOT NULL,
    device_id   INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    mac         TEXT NOT NULL DEFAULT '',
    hostname    TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'static',  -- static | reservation | dhcp
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ip_network ON ip_addresses(network_id);
CREATE INDEX IF NOT EXISTS idx_ip_device ON ip_addresses(device_id);

CREATE TABLE IF NOT EXISTS licenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL DEFAULT 'software',  -- software | subscription | maintenance | domain | certificate | other
    name          TEXT NOT NULL,
    vendor        TEXT NOT NULL DEFAULT '',
    term          TEXT NOT NULL DEFAULT '',          -- Laufzeit/Art, z. B. „Abo, jährlich“, „Kauf“, „OEM“
    seats         INTEGER,                            -- NULL = unbegrenzt / nicht gezählt
    seats_used    INTEGER,                            -- von Hand; NULL = zugeordnete Geräte zählen
    expires_on    TEXT,                               -- YYYY-MM-DD, NULL = unbefristet
    contract_ref  TEXT NOT NULL DEFAULT '',           -- Vertrag / Kundennummer / Tenant
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS license_devices (
    license_id  INTEGER NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    PRIMARY KEY (license_id, device_id)
);
CREATE INDEX IF NOT EXISTS idx_licdev_device ON license_devices(device_id);

CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type  TEXT NOT NULL,                  -- device | license | contact | site | network
    owner_id    INTEGER NOT NULL,
    role        TEXT NOT NULL DEFAULT 'file',   -- file | diagram (Netzwerkplan eines Standorts)
    name        TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    data        BLOB NOT NULL,                  -- in der Datenbank, damit die Sicherung alles enthält
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_att_owner ON attachments(owner_type, owner_id);
""")
    if not conn.execute("SELECT 1 FROM device_types LIMIT 1").fetchone():
        for i, (name, icon) in enumerate(DEVICE_TYPES):
            conn.execute("INSERT INTO device_types(name, icon, sort) VALUES (?, ?, ?)", (name, icon, i))
    if not conn.execute("SELECT 1 FROM sites LIMIT 1").fetchone():
        conn.execute("INSERT INTO sites(name, created_at) VALUES ('Hauptstandort', ?)", (now_utc_str(),))


def _m3_tresor(conn: sqlite3.Connection) -> None:
    """Version 0.3: Tresor – verschlüsselte Schlüssel pro Benutzer, Notfall-Schlüssel, Einladungen, Zugangsdaten."""
    _run(conn, """
CREATE TABLE IF NOT EXISTS vault_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,                 -- user | recovery | invite
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    salt         TEXT NOT NULL,
    iterations   INTEGER NOT NULL,
    wrapped      TEXT NOT NULL,                 -- Datenschlüssel, verschlüsselt mit dem Schlüssel aus Passwort/Code
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT,                          -- nur Einladungen
    last_used_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_user ON vault_keys(kind, user_id) WHERE kind IN ('user', 'invite');
CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_recovery ON vault_keys(kind) WHERE kind = 'recovery';

CREATE TABLE IF NOT EXISTS credentials (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT NOT NULL,
    username             TEXT NOT NULL DEFAULT '',
    url                  TEXT NOT NULL DEFAULT '',
    owner_type           TEXT,                  -- device | license | site | contact | NULL (allgemein)
    owner_id             INTEGER,
    password_enc         TEXT,                  -- verschlüsselt (Tresor)
    notes_enc            TEXT,
    totp_enc             TEXT,
    password_changed_at  TEXT,
    created_by           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT
);
CREATE INDEX IF NOT EXISTS idx_cred_owner ON credentials(owner_type, owner_id);
""")
    if "key_enc" not in _columns(conn, "licenses"):
        conn.execute("ALTER TABLE licenses ADD COLUMN key_enc TEXT")  # Lizenzschlüssel, verschlüsselt


MIGRATIONS: Dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _m1_basis,
    2: _m2_stammdaten,
    3: _m3_tresor,
}
SCHEMA_VERSION = max(MIGRATIONS)

DEFAULT_SETTINGS = {
    "company_name": "",
    "theme_default": "classic",
    # Öffentliche Adresse (Reverse Proxy) fürs DSM-Fenster; leer = automatisch
    "public_url": "",
    # Anmeldung mit DSM-Konten. DSM-Administratoren kommen per Single Sign-on hinein (Vollzugriff), andere
    # DSM-Benutzer nur, wenn der Admin sie anlegt. Zugangsdaten bleiben trotzdem im Tresor mit eigenem Passwort.
    "dsm_login": "1",
    "dsm_auto_create": "0",  # unbekannte (Nicht-Admin-)DSM-Benutzer automatisch mit Lesezugriff anlegen
    "dsm_admins": "1",
    "dsm_url": "http://127.0.0.1:5000",
    # Mailversand (SMTP)
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_security": "starttls",   # starttls | ssl | none
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_from_name": "IT-Dokumentation",
    # Datensicherung: jede Nacht, lokal + optional in einen freigegebenen Ordner
    "backup_enabled": "1",
    "backup_hour": "2",
    "backup_keep_days": "30",
    "backup_dir": "",              # z. B. /volume1/backup/it-doku
    # Tresor: nach so vielen Minuten ohne Aktivität sperren
    "vault_timeout_min": "15",
}


class MigrationError(RuntimeError):
    pass


def migrate(conn: sqlite3.Connection) -> int:
    """Bringt die Datenbank Schritt für Schritt auf SCHEMA_VERSION. Liefert die Ausgangsversion.

    Jeder Schritt läuft in einer eigenen Transaktion und setzt user_version erst am Ende – bricht
    ein Schritt ab, bleibt die Datenbank auf dem letzten vollständigen Stand."""
    start = conn.execute("PRAGMA user_version").fetchone()[0]
    if start > SCHEMA_VERSION:
        raise MigrationError(
            f"Die Datenbank stammt aus einer neueren Version (Schema {start}, diese App kennt {SCHEMA_VERSION}). "
            "Bitte die neueste Version des Pakets installieren.")
    for version in range(start + 1, SCHEMA_VERSION + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            MIGRATIONS[version](conn)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return start


def connect() -> sqlite3.Connection:
    # Autocommit: jede Änderung ist sofort gespeichert (FastAPI räumt get_db() erst nach dem Senden auf).
    # check_same_thread=False: FastAPI öffnet die Verbindung u. U. in einem anderen Thread als dem des
    # Endpunkts. Jede Verbindung gehört trotzdem nur einem Request.
    conn = sqlite3.connect(str(settings.db_path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI-Dependency: eine Verbindung pro Request (Autocommit)."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Legt Datenordner, Schema und (beim ersten Start) den Admin-Zugang an."""
    from .security import hash_password  # vermeidet Import-Zyklus

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        migrate(conn)
        first_start = not conn.execute("SELECT 1 FROM app_settings LIMIT 1").fetchone()
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO app_settings(key, value) VALUES (?, ?)", (key, value))
        if first_start:
            # Werte aus dem Installationsassistenten (nur beim allerersten Start)
            if settings.initial_company.strip():
                set_setting(conn, "company_name", settings.initial_company.strip()[:80])

        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            password = settings.initial_admin_password or secrets.token_urlsafe(12)
            conn.execute(
                "INSERT INTO users(username, display_name, password_hash, is_admin, created_at) "
                "VALUES ('admin', 'Administrator', ?, 1, ?)",
                (hash_password(password), now_utc_str()),
            )
            if not settings.initial_admin_password:
                cred_file = settings.data_dir / "ERSTES_ADMIN_PASSWORT.txt"
                cred_file.write_text(
                    "Benutzer: admin\nPasswort: " + password + "\n\n"
                    "Bitte nach dem ersten Login ändern und diese Datei löschen.\n",
                    encoding="utf-8",
                )
                print(f"[it-doku] Admin angelegt, Passwort steht in {cred_file}", flush=True)
    finally:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO app_settings(key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def audit(conn: sqlite3.Connection, actor_id, action: str, target: str = "", details: str = "") -> None:
    """Eintrag ins Änderungsprotokoll. Einträge werden nie geändert oder gelöscht."""
    conn.execute(
        "INSERT INTO audit_log(ts, actor_id, action, target, details) VALUES (?, ?, ?, ?, ?)",
        (now_utc_str(), actor_id, action, target or "", (details or "")[:2000]),
    )
