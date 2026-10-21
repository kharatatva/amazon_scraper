"""Small idempotent schema ensure for the Demand Tracker runtime."""

from datetime import datetime, timezone

from src.storage.db import get_connection


def ensure_demand_schema() -> None:
    """Create or upgrade the API demand-tracking tables."""
    conn = get_connection()
    try:
        columns = {}
        for table in ("scheduled_niches", "opportunity_scores"):
            columns[table] = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        additions = {
            "scheduled_niches": [
                ("pages", "INTEGER NOT NULL DEFAULT 10"),
                ("products", "INTEGER NOT NULL DEFAULT 100"),
                ("run_times", "TEXT NOT NULL DEFAULT '08:00,20:00'"),
                ("timezone", "TEXT NOT NULL DEFAULT 'Asia/Kolkata'"),
                ("last_slot_key", "TEXT"),
            ],
            "opportunity_scores": [("demand_score_version", "INTEGER NOT NULL DEFAULT 0")],
        }
        for table, definitions in additions.items():
            if not columns[table]:
                raise RuntimeError(f"Required dashboard table is missing: {table}")
            for name, definition in definitions:
                if name not in columns[table]:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_niches_active ON scheduled_niches(is_active,id)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS demand_backfill_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed')),
                total_runs INTEGER NOT NULL DEFAULT 0,
                processed_runs INTEGER NOT NULL DEFAULT 0,
                products_scored INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT
            )"""
        )

        current_run_columns = {row[1] for row in conn.execute("PRAGMA table_info(search_runs)")}
        has_migration_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if has_migration_table and {"current_stage", "current_task", "config_json"}.issubset(current_run_columns):
            applied_at = datetime.now(timezone.utc).isoformat()
            conn.executemany(
                "INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES (?,?)",
                [(version, applied_at) for version in range(2, 10)],
            )
        conn.commit()
    finally:
        conn.close()
