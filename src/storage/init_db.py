"""Create the SQLite database from the canonical schema."""

from datetime import datetime, timezone, timezone
import sqlite3
from pathlib import Path

from src.config import DB_FILE, MIGRATIONS_DIR, MIGRATION_PATTERN
from src.logger import logger


# ==================================================
# PROJECT PATHS
# ==================================================

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


# ==================================================
# Database Initialization
# ==================================================

def initialize_database():
    """
    Initialize the SQLite database using the canonical schema.sql file.

    The database schema is maintained exclusively in schema.sql.
    This function is responsible only for:
        1. Locating the database.
        2. Reading the schema file.
        3. Opening the SQLite connection.
        4. Enabling foreign-key enforcement.
        5. Executing the schema.
        6. Committing the changes.
    """

    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(
            f"Database schema file not found: {SCHEMA_FILE}"
        )

    # Ensure the parent directory for the database exists.
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Initializing database...")
    logger.info("Database file: %s", DB_FILE)
    logger.info("Schema file: %s", SCHEMA_FILE)

    # Read the canonical schema.
    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")

    conn = None

    try:
        conn = sqlite3.connect(DB_FILE)

        # Enable foreign-key enforcement for this connection.
        conn.execute("PRAGMA foreign_keys = ON;")

        # Execute the complete schema.
        conn.executescript(schema_sql)
        latest_version = max(
            (int(match.group(1)) for file in MIGRATIONS_DIR.iterdir()
             if (match := MIGRATION_PATTERN.match(file.name))),
            default=1,
        )
        applied_at = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES (?,?)",
            [(version, applied_at) for version in range(1, latest_version + 1)],
        )

        conn.commit()

        logger.info("Database initialized successfully.")

    except sqlite3.Error:
        if conn is not None:
            conn.rollback()

        logger.exception("Database initialization failed.")
        raise

    except Exception:
        if conn is not None:
            conn.rollback()

        logger.exception("Unexpected error during database initialization.")
        raise

    finally:
        if conn is not None:
            conn.close()


# ==================================================
# Script Entry Point
# ==================================================

if __name__ == "__main__":
    initialize_database()
