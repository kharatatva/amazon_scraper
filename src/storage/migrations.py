"""Apply numbered SQL migrations and record their versions."""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB_FILE
from src.logger import logger
from src.config import MIGRATIONS_DIR, MIGRATION_PATTERN



def get_migration_files() -> list[tuple[int, Path]]:
    """
    Return all migration files in numeric order.

    Expected filename format:

        0001_baseline.sql
        0002_add_something.sql
        0003_another_change.sql
    """

    if not MIGRATIONS_DIR.exists():
        raise FileNotFoundError(
            f"Migrations directory not found: {MIGRATIONS_DIR}"
        )

    migrations = []

    for path in MIGRATIONS_DIR.iterdir():

        if not path.is_file():
            continue

        match = MIGRATION_PATTERN.match(path.name)

        if match is None:
            continue

        version = int(match.group(1))

        migrations.append((version, path))

    migrations.sort(key=lambda item: item[0])

    return migrations


def get_applied_versions(cursor) -> set[int]:
    """
    Return migration versions already recorded
    in schema_migrations.
    """

    rows = cursor.execute(
        """
        SELECT version
        FROM schema_migrations
        ORDER BY version
        """
    ).fetchall()

    return {row[0] for row in rows}

def execute_migration_sql(conn, migration_sql: str) -> None:
    """
    Execute all SQL statements in a migration file.

    Statements are executed individually so that the caller's
    transaction remains active. This avoids sqlite3.executescript()
    implicitly committing the transaction.
    """

    statement = ""

    for line in migration_sql.splitlines():
        stripped_line = line.strip()

        # Ignore empty lines and SQL comment-only lines.
        if not stripped_line or stripped_line.startswith("--"):
            continue

        statement += line + "\n"

        # SQLite tells us when the accumulated text contains
        # a complete SQL statement.
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""

    # Allow the final statement to omit a semicolon.
    remaining = statement.strip()

    if remaining:
        try:
            conn.execute(remaining)
        except sqlite3.Error:
            logger.error(
                "Failed to execute final migration SQL:\n%s",
                remaining,
            )
            raise

# ==================================================
# Migration Execution
# ==================================================

def apply_migrations() -> None:
    """
    Apply every migration that has not yet been recorded.

    Each migration and its corresponding record are committed
    atomically. A migration that has already been recorded is
    never executed again.
    """

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    migrations = get_migration_files()

    conn = None

    try:
        conn = sqlite3.connect(DB_FILE)

        conn.execute("PRAGMA foreign_keys = ON")

        cursor = conn.cursor()

        # --------------------------------------------------
        # Verify migration tracking table exists
        # --------------------------------------------------

        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'schema_migrations'
            """
        )

        if cursor.fetchone() is None:
            raise RuntimeError(
                "schema_migrations table does not exist. "
                "Run database initialization first."
            )

        applied_versions = get_applied_versions(cursor)

        pending_migrations = [
            (version, path)
            for version, path in migrations
            if version not in applied_versions
        ]

        if not pending_migrations:
            logger.info("No migrations to apply.")
            return

        for version, migration_file in pending_migrations:

            logger.info(
                "Applying migration %04d: %s",
                version,
                migration_file.name,
            )

            migration_sql = migration_file.read_text(
                encoding="utf-8"
            )

            try:
                # --------------------------------------------------
                # Migration + tracking record = one transaction
                # --------------------------------------------------
                # USE THIS FOR FOREIGN KEY DISABLE/ENABLE IF NEEDED
                # if version == 7:
                #     conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("BEGIN")

                execute_migration_sql(conn, migration_sql)
                # conn.executescript(migration_sql)

                conn.execute(
                    """
                    INSERT INTO schema_migrations
                    (
                        version,
                        applied_at
                    )
                    VALUES (?, ?)
                    """,
                    (
                        version,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

                conn.commit()
                # USE THIS FOR FOREIGN KEY DISABLE/ENABLE IF NEEDED
                # if version == 7:
                #     conn.execute("PRAGMA foreign_keys = ON")
                logger.info(
                    "Migration %04d applied successfully.",
                    version,
                )

                applied_versions.add(version)

            except Exception:
                conn.rollback()

                logger.exception(
                    "Migration %04d failed. "
                    "Transaction rolled back.",
                    version,
                )

                raise

        logger.info(
            "Migration process complete. Applied %d migration(s).",
            len(pending_migrations),
        )

    except sqlite3.Error:
        logger.exception("Migration process failed.")
        raise

    finally:
        if conn is not None:
            conn.close()


# ==================================================
# Script Entry Point
# ==================================================

if __name__ == "__main__":
    apply_migrations()
