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


MIGRATIONS: Dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _m1_basis,
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
