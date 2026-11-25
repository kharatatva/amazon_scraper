"""Readiness checks and safe, repeatable local environment setup."""

from __future__ import annotations

import copy
import importlib
import importlib.metadata
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src import config
from src.logger import logger

_REQUIRED_IMPORTS = {
    "beautifulsoup4": "bs4",
    "playwright": "playwright",
    "playwright-stealth": "playwright_stealth",
    "fastapi": "fastapi",
    "requests": "requests",
    "uvicorn": "uvicorn",
}
_REQUIRED_TABLES = {
    "niches",
    "keywords",
    "sellers",
    "search_runs",
    "products",
    "niche_products",
    "snapshots",
    "opportunity_scores",
    "scrape_errors",
    "niche_keywords",
    "schema_migrations",
    "scheduled_niches",
    "demand_backfill_jobs",
}
_SETUP_STAGES = [
    ("folders", "Application folders"),
    ("python", "Python dependencies"),
    ("database", "SQLite database"),
    ("configuration", "Scraper configuration"),
    ("browser", "Playwright Chromium"),
]
_STATUS_LOCK = threading.Lock()
_SETUP_LOCK = threading.Lock()
_OPERATION: dict | None = None
_BROWSER_PROBE: tuple[tuple[str, int, int] | None, bool, str] | None = None
_BROWSER_PATH_CACHE: tuple[str, str] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _component(component_id: str, name: str, status: str, message: str) -> dict:
    return {
        "id": component_id,
        "name": name,
        "status": status,
        "required": True,
        "message": message,
    }


def _probe_directories(*, write_probe: bool) -> dict:
    paths = (config.DATA_DIR, config.LOG_DIR, config.RENDERED_HTML_DIR)
    try:
        if write_probe:
            for path in paths:
                path.mkdir(parents=True, exist_ok=True)
        elif not all(path.is_dir() for path in paths):
            return _component(
                "folders", "Application folders", "missing",
                "One or more application data folders are missing. Initialize the environment from Settings.",
            )
        elif not all(os.access(path, os.W_OK) for path in paths):
            return _component(
                "folders", "Application folders", "error",
                "One or more application data folders cannot be written.",
            )
        if write_probe:
            for path in paths:
                with tempfile.NamedTemporaryFile(
                    prefix=".nichescope-check-", dir=path, delete=True
                ):
                    pass
    except OSError as exc:
        logger.warning("Application storage check failed (%s).", type(exc).__name__)
        return _component(
            "folders", "Application folders", "error",
            "The application data folders are missing or cannot be written.",
        )
    return _component(
        "folders", "Application folders", "ready",
        "Data, logs, and captured-page folders are available.",
    )


def _missing_imports() -> list[str]:
    missing = []
    for package, module in _REQUIRED_IMPORTS.items():
        try:
            importlib.import_module(module)
        except Exception:
            logger.warning("Required Python package failed to import (%s).", package)
            missing.append(package)
    return missing


def _python_component() -> dict:
    missing = _missing_imports()
    if missing:
        return _component(
            "python", "Python dependencies", "missing",
            "Required Python packages are missing: " + ", ".join(missing) + ".",
        )
    return _component(
        "python", "Python dependencies", "ready",
        "All required scraper and API packages are importable.",
    )


def _database_component() -> dict:
    db_path = config.DB_FILE
    if not db_path.is_file():
        return _component(
            "database", "SQLite database", "missing",
            "The local database has not been initialized.",
        )
    if not os.access(db_path, os.W_OK):
        return _component(
            "database", "SQLite database", "error",
            "The database file is read-only. Update its permissions before scraping.",
        )

    try:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            connection.execute("SELECT 1").fetchone()
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing_tables = sorted(_REQUIRED_TABLES - names)
            if missing_tables:
                return _component(
                    "database", "SQLite database", "error",
                    "The database is incomplete. Initialize or repair the database from Settings.",
                )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(search_runs)")
            }
            required_columns = {
                "id", "niche_id", "keyword_id", "status", "current_stage",
                "current_task", "config_json",
            }
            if not required_columns.issubset(columns):
                return _component(
                    "database", "SQLite database", "error",
                    "The database schema is out of date. Apply its pending migrations from Settings.",
                )
            applied = {
                int(row[0])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError) as exc:
        logger.warning("Database readiness check failed (%s).", type(exc).__name__)
        return _component(
            "database", "SQLite database", "error",
            "The database cannot be opened. Check data-folder permissions or use Settings to inspect setup.",
        )

    try:
        from src.storage.migrations import get_migration_files

        expected = {1, *(version for version, _ in get_migration_files())}
    except (OSError, FileNotFoundError, ValueError):
        return _component(
            "database", "SQLite database", "error",
            "Database migration files are unavailable in this project installation.",
        )
    if not expected.issubset(applied):
        return _component(
            "database", "SQLite database", "error",
            "The database has unapplied migrations. Apply them from Settings.",
        )
    return _component(
        "database", "SQLite database", "ready",
        "Database connectivity, required tables, and migrations are healthy.",
    )


def _settings_component() -> dict:
    settings_file = config.SCRAPER_SETTINGS_FILE
    if not settings_file.exists():
        return _component(
            "configuration", "Scraper configuration", "ready",
            "Built-in scraper defaults are active; no local settings file is required.",
        )
    try:
        with settings_file.open("r", encoding="utf-8") as source:
            values = json.load(source)
        if not isinstance(values, dict):
            raise ValueError("settings must be a JSON object")
        from src.storage.backend.scraper_settings import _validate_values

        _validate_values(values)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        return _component(
            "configuration", "Scraper configuration", "error",
            "Saved scraper settings are invalid. Use Repair to preserve the file and restore defaults.",
        )
    return _component(
        "configuration", "Scraper configuration", "ready",
        "Saved scraper settings are valid.",
    )


def _browser_signature() -> tuple[tuple[str, int, int] | None, Path | None]:
    global _BROWSER_PATH_CACHE
    if _missing_imports():
        return None, None
    try:
        version = importlib.metadata.version("playwright")
        if _BROWSER_PATH_CACHE and _BROWSER_PATH_CACHE[0] == version:
            executable = Path(_BROWSER_PATH_CACHE[1])
        else:
            command = (
                "from playwright.sync_api import sync_playwright; "
                "p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()"
            )
            completed = _run_command([sys.executable, "-c", command], timeout=20)
            if completed.returncode != 0:
                return None, None
            executable = Path(completed.stdout.splitlines()[-1].strip())
            _BROWSER_PATH_CACHE = (version, str(executable))
        stat = executable.stat()
        return (str(executable), stat.st_size, stat.st_mtime_ns), executable
    except Exception:
        return None, None


def _browser_component(*, deep_check: bool) -> dict:
    global _BROWSER_PROBE

    signature, executable = _browser_signature()
    if executable is None or signature is None:
        return _component(
            "browser", "Playwright Chromium", "missing",
            "Playwright Chromium is not installed. Initialize the environment to install it.",
        )

    with _STATUS_LOCK:
        cached = _BROWSER_PROBE
    if not deep_check and cached and cached[0] == signature:
        if cached[1]:
            return _component(
                "browser", "Playwright Chromium", "ready",
                "Chromium is installed and passed its launch check.",
            )
        return _component(
            "browser", "Playwright Chromium", "error", cached[2],
        )

    if not deep_check:
        return _component(
            "browser", "Playwright Chromium", "unknown",
            "Chromium is installed but has not passed a launch check. Verify it from Settings.",
        )

    try:
        command = (
            "from playwright.sync_api import sync_playwright; "
            "p=sync_playwright().start(); b=p.chromium.launch(headless=True, timeout=15000); "
            "b.close(); p.stop()"
        )
        completed = _run_command([sys.executable, "-c", command], timeout=25)
        if completed.returncode != 0:
            raise RuntimeError("Browser launch check returned a failure status.")
        result = (signature, True, "Chromium is installed and passed its launch check.")
        with _STATUS_LOCK:
            _BROWSER_PROBE = result
        return _component("browser", "Playwright Chromium", "ready", result[2])
    except Exception as exc:
        logger.warning("Playwright Chromium launch check failed (%s).", type(exc).__name__)
        result = (
            signature,
            False,
            "Chromium could not start. Repair the browser installation or install the operating system libraries it requires.",
        )
        with _STATUS_LOCK:
            _BROWSER_PROBE = result
        return _component("browser", "Playwright Chromium", "error", result[2])


def get_environment_status(
    *, deep_browser_check: bool = False, probe_writable: bool = False
) -> dict:
    """Check current machine state; readiness is derived from live component checks."""
    components = [
        _probe_directories(write_probe=probe_writable),
        _python_component(),
        _database_component(),
        _settings_component(),
        _browser_component(deep_check=deep_browser_check),
    ]
    ready = all(item["status"] == "ready" for item in components)
    return {
        "ready": ready,
        "scraper_ready": ready,
        "checked_at": _utc_now(),
        "components": components,
        "issues": [
            {"id": item["id"], "name": item["name"], "message": item["message"]}
            for item in components
            if item["status"] != "ready"
        ],
    }


def _backup_database() -> None:
    """Create a SQLite-consistent backup before explicit schema recovery."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = config.DB_FILE.with_name(f"{config.DB_FILE.name}.backup-{stamp}")
    suffix = 1
    while backup_path.exists():
        backup_path = config.DB_FILE.with_name(
            f"{config.DB_FILE.name}.backup-{stamp}-{suffix}"
        )
        suffix += 1
    source = sqlite3.connect(config.DB_FILE)
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
        logger.info("Created a database backup before schema recovery.")
    finally:
        backup.close()
        source.close()


def _prepare_storage(*, repair: bool = False) -> None:
    from src.storage.demand_schema import ensure_demand_schema
    from src.storage.init_db import initialize_database
    from src.storage.migrations import apply_migrations

    config.MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not config.DB_FILE.exists() or config.DB_FILE.stat().st_size == 0:
        initialize_database()
    elif repair:
        database = _database_component()
        if database["status"] == "error" and database["message"] in {
            "The database is incomplete. Initialize or repair the database from Settings.",
            "The database schema is out of date. Apply its pending migrations from Settings.",
        }:
            _backup_database()
            initialize_database()
    apply_migrations()
    ensure_demand_schema()
    database = _database_component()
    if database["status"] != "ready":
        raise RuntimeError(database["message"])


def prepare_local_environment() -> None:
    """Prepare directories and storage at backend startup without replacing data."""
    with _cross_process_setup_lock():
        folders = _probe_directories(write_probe=True)
        if folders["status"] != "ready":
            raise PermissionError(folders["message"])
        _prepare_storage()


@contextmanager
def _cross_process_setup_lock() -> Iterator[None]:
    """Lock setup across API processes on Windows and POSIX systems."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = config.DATA_DIR / ".environment-setup.lock"
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        locked = False
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise RuntimeError("Another initialization process is already running.") from exc
                locked = True
            else:
                import fcntl

                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise RuntimeError("Another initialization process is already running.") from exc
                locked = True
            yield
        finally:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _set_stage(operation_id: str, stage_id: str, *, status: str, message: str) -> None:
    with _STATUS_LOCK:
        if _OPERATION is None or _OPERATION["id"] != operation_id:
            return
        stage = next(item for item in _OPERATION["stages"] if item["id"] == stage_id)
        stage["status"] = status
        stage["message"] = message
        _OPERATION["stage"] = stage_id if status == "running" else _OPERATION.get("stage")
        _OPERATION["completed"] = sum(item["status"] in {"ready", "skipped"} for item in _OPERATION["stages"])
        _OPERATION["progress"] = round(100 * _OPERATION["completed"] / len(_OPERATION["stages"]))
        _OPERATION["updated_at"] = _utc_now()


def _run_command(command: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=config.PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def _install_python_dependencies() -> None:
    if not _missing_imports():
        return
    completed = _run_command(
        [sys.executable, "-m", "pip", "install", "-r", str(config.PROJECT_ROOT / "requirements.txt")],
        timeout=600,
    )
    if completed.returncode != 0 or _missing_imports():
        logger.error("Python dependency setup failed (exit code %s).", completed.returncode)
        raise RuntimeError(
            "Python package installation failed. Check network access and retry from Settings."
        )


def _preserve_invalid_settings() -> None:
    settings_file = config.SCRAPER_SETTINGS_FILE
    if not settings_file.exists() or _settings_component()["status"] == "ready":
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = settings_file.with_name(f"{settings_file.name}.backup-{stamp}")
    suffix = 1
    while backup.exists():
        backup = settings_file.with_name(f"{settings_file.name}.backup-{stamp}-{suffix}")
        suffix += 1
    os.replace(settings_file, backup)
    from src.storage.backend.scraper_settings import reset_scraper_settings

    reset_scraper_settings()


def _initialize_browser(*, repair: bool) -> None:
    component = _browser_component(deep_check=False)
    if not repair and component["status"] == "ready":
        return
    completed = _run_command(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        timeout=600,
    )
    if completed.returncode != 0:
        logger.error("Playwright Chromium installation failed (exit code %s).", completed.returncode)
        raise RuntimeError(
            "Chromium installation failed. Check network access, then retry; Linux may also need browser system libraries."
        )
    browser = _browser_component(deep_check=True)
    if browser["status"] != "ready":
        raise RuntimeError(browser["message"])


def _complete_operation(operation_id: str, repair: bool) -> None:
    global _OPERATION
    current_stage = "folders"
    try:
        with _cross_process_setup_lock():
            actions = {
                "folders": lambda: _probe_directories(write_probe=True),
                "python": _install_python_dependencies,
                "database": lambda: _prepare_storage(repair=repair),
                "configuration": lambda: _preserve_invalid_settings() if repair else None,
                "browser": lambda: _initialize_browser(repair=repair),
            }
            validators = {
                "python": _python_component,
                "database": _database_component,
                "configuration": _settings_component,
                "browser": lambda: _browser_component(deep_check=False),
            }
            for stage_id, _ in _SETUP_STAGES:
                current_stage = stage_id
                _set_stage(operation_id, stage_id, status="running", message="Checking this component…")
                if stage_id == "folders":
                    result = actions[stage_id]()
                    if result["status"] != "ready":
                        raise RuntimeError(result["message"])
                else:
                    actions[stage_id]()
                    result = validators[stage_id]()
                    if result["status"] != "ready":
                        raise RuntimeError(result["message"])
                _set_stage(operation_id, stage_id, status="ready", message="Verified and ready.")

            environment = get_environment_status(deep_browser_check=True)
            if not environment["ready"]:
                issue = environment["issues"][0]["message"] if environment["issues"] else "The environment is not ready."
                raise RuntimeError(issue)
        with _STATUS_LOCK:
            if _OPERATION and _OPERATION["id"] == operation_id:
                _OPERATION.update(
                    status="completed", stage=None, progress=100,
                    message="Environment setup completed successfully.",
                    error=None, updated_at=_utc_now(),
                )
        try:
            from src.storage.backend.main import start_operational_services

            start_operational_services()
        except Exception:
            logger.exception("Could not start dashboard workers after environment setup.")
    except subprocess.TimeoutExpired:
        message = "A setup step timed out. Check network access or system requirements, then retry."
        _set_stage(operation_id, current_stage, status="error", message=message)
        with _STATUS_LOCK:
            if _OPERATION and _OPERATION["id"] == operation_id:
                _OPERATION.update(status="failed", message=message, error=message, updated_at=_utc_now())
    except Exception as exc:
        if current_stage in {"python", "configuration", "browser"} and isinstance(exc, RuntimeError):
            message = str(exc)
        elif current_stage == "database":
            message = "Database initialization failed. Existing data was preserved; check folder permissions and schema files, then retry."
        else:
            message = "Setup could not complete this step. Check folder permissions and retry."
        logger.error(
            "Environment setup failed during %s (%s).",
            current_stage,
            type(exc).__name__,
        )
        _set_stage(operation_id, current_stage, status="error", message=message)
        with _STATUS_LOCK:
            if _OPERATION and _OPERATION["id"] == operation_id:
                _OPERATION.update(status="failed", message=message, error=message, updated_at=_utc_now())


def start_initialization(*, repair: bool = False) -> dict:
    """Start one setup job; repeated requests return the active job instead."""
    global _OPERATION
    with _SETUP_LOCK:
        with _STATUS_LOCK:
            if _OPERATION and _OPERATION["status"] == "running":
                return copy.deepcopy(_OPERATION)
            operation_id = uuid.uuid4().hex
            _OPERATION = {
                "id": operation_id,
                "status": "running",
                "stage": "folders",
                "progress": 0,
                "completed": 0,
                "total": len(_SETUP_STAGES),
                "message": "Preparing the local environment…",
                "error": None,
                "started_at": _utc_now(),
                "updated_at": _utc_now(),
                "stages": [
                    {"id": stage_id, "name": name, "status": "pending", "message": "Waiting to start."}
                    for stage_id, name in _SETUP_STAGES
                ],
            }
        worker = threading.Thread(
            target=_complete_operation,
            args=(operation_id, repair),
            name="nichescope-environment-setup",
            daemon=True,
        )
        worker.start()
        return get_initialization_status()


def get_initialization_status() -> dict | None:
    with _STATUS_LOCK:
        return copy.deepcopy(_OPERATION)


def check_environment(*, deep_browser_check: bool = True) -> dict:
    """Explicit verification action used by Settings and onboarding."""
    return get_environment_status(
        deep_browser_check=deep_browser_check,
        probe_writable=True,
    )


def readiness_error(status: dict) -> str:
    """Describe blocking setup issues without returning local paths or secrets."""
    issues = [item["message"] for item in status.get("issues", [])]
    return "; ".join(issues) or "The local environment is not ready."
