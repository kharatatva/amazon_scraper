"""SQLite initialization and migration runner tests with temporary files."""

import sqlite3

from src.storage import migrations


def test_bootstrap_creates_schema_and_records_available_migrations(temp_database):
    with sqlite3.connect(temp_database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]

    assert {"niches", "search_runs", "snapshots", "schema_migrations"} <= tables
    assert versions


def test_migration_runner_accepts_gaps_in_version_numbers(tmp_path, monkeypatch):
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "0001_first.sql").write_text(
        "CREATE TABLE first_table (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (migration_dir / "0003_third.sql").write_text(
        "CREATE TABLE third_table (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    database_path = tmp_path / "migration-test.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )

    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", migration_dir)
    monkeypatch.setattr(migrations, "DB_FILE", database_path)

    migrations.apply_migrations()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]

    assert {"first_table", "third_table"} <= tables
    assert versions == [1, 3]
