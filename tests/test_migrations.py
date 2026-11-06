"""Datenbank-Migrationen: frische DB, schrittweise ab jeder Version, Abbruch, neuere DB."""
import sqlite3

import pytest

from app import db
from app.db import MIGRATIONS, SCHEMA_VERSION, MigrationError, migrate


def _conn(path):
    c = sqlite3.connect(str(path), isolation_level=None)
    c.row_factory = sqlite3.Row
    return c


def test_versions_are_consecutive():
    assert sorted(MIGRATIONS) == list(range(1, SCHEMA_VERSION + 1))


def test_fresh_database(tmp_path):
    c = _conn(tmp_path / "a.db")
    assert migrate(c) == 0
    assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "sessions", "audit_log", "app_settings"} <= tables
    assert migrate(c) == SCHEMA_VERSION  # zweiter Lauf ändert nichts


@pytest.mark.parametrize("start", range(1, SCHEMA_VERSION + 1))
def test_upgrade_from_every_version_keeps_data(tmp_path, start):
    """Datenbank auf Stand `start` bringen, Daten hinein, dann bis zum Ende migrieren."""
    c = _conn(tmp_path / "b.db")
    for v in range(1, start + 1):
        MIGRATIONS[v](c)
    c.execute(f"PRAGMA user_version = {start}")
    c.execute("INSERT INTO users(username, display_name, is_admin, created_at) VALUES ('alt', 'Alt', 1, '2026-01-01T00:00:00+00:00')")
    c.execute("INSERT INTO app_settings(key, value) VALUES ('company_name', 'Alt GmbH')")
    migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert c.execute("SELECT display_name FROM users WHERE username = 'alt'").fetchone()[0] == "Alt"
    assert c.execute("SELECT value FROM app_settings WHERE key = 'company_name'").fetchone()[0] == "Alt GmbH"


def test_failed_step_rolls_back(tmp_path, monkeypatch):
    c = _conn(tmp_path / "c.db")
    migrate(c)

    def broken(conn):
        conn.execute("CREATE TABLE halb (id INTEGER)")
        raise RuntimeError("Stromausfall")

    monkeypatch.setitem(MIGRATIONS, SCHEMA_VERSION + 1, broken)
    monkeypatch.setattr(db, "SCHEMA_VERSION", SCHEMA_VERSION + 1)
    with pytest.raises(RuntimeError):
        db.migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'halb'").fetchone()


def test_newer_database_is_refused(tmp_path):
    c = _conn(tmp_path / "d.db")
    migrate(c)
    c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
    with pytest.raises(MigrationError, match="neueren Version"):
        migrate(c)
