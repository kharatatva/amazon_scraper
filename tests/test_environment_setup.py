"""Safe environment readiness and initialization coverage."""

from __future__ import annotations

import importlib
import sqlite3
import subprocess
import threading
import time
from contextlib import nullcontext
from pathlib import Path

import pytest

from src.storage.backend import environment_setup as setup


@pytest.fixture
def local_paths(tmp_path, monkeypatch):
    """Redirect every storage module used by setup into a temporary workspace."""
    paths = {
        "DATA_DIR": tmp_path / "data",
        "LOG_DIR": tmp_path / "data" / "logs",
        "RENDERED_HTML_DIR": tmp_path / "data" / "rendered_html",
        "DB_FILE": tmp_path / "data" / "scraper_analysis.db",
        "MIGRATIONS_DIR": tmp_path / "migrations",
        "SCRAPER_SETTINGS_FILE": tmp_path / "data" / "scraper_settings.json",
    }
    for key, value in paths.items():
        monkeypatch.setattr(setup.config, key, value)

    modules = (
        "src.storage.db",
        "src.storage.init_db",
        "src.storage.migrations",
    )
    for module_name in modules:
        module = importlib.import_module(module_name)
        if hasattr(module, "DB_FILE"):
            monkeypatch.setattr(module, "DB_FILE", paths["DB_FILE"])
        if hasattr(module, "MIGRATIONS_DIR"):
            monkeypatch.setattr(module, "MIGRATIONS_DIR", paths["MIGRATIONS_DIR"])
    return paths


def test_fresh_install_is_detected_and_initialization_is_idempotent(local_paths):
    before = setup.get_environment_status()
    assert not before["ready"]
    assert next(item for item in before["components"] if item["id"] == "database")["status"] == "missing"

    setup.prepare_local_environment()
    with sqlite3.connect(local_paths["DB_FILE"]) as connection:
        connection.execute(
            "INSERT INTO niches(name,slug,created_at) VALUES(?,?,?)",
            ("Saved niche", "saved-niche", "2026-01-01T00:00:00+00:00"),
        )

    setup.prepare_local_environment()

    with sqlite3.connect(local_paths["DB_FILE"]) as connection:
        assert connection.execute("SELECT name FROM niches").fetchall() == [("Saved niche",)]
        assert connection.execute("SELECT version FROM schema_migrations WHERE version=1").fetchone()


def test_existing_incomplete_database_is_reported_and_never_reinitialized(local_paths):
    local_paths["DATA_DIR"].mkdir(parents=True)
    with sqlite3.connect(local_paths["DB_FILE"]) as connection:
        connection.execute("CREATE TABLE user_data(value TEXT)")
        connection.execute("INSERT INTO user_data VALUES('keep me')")

    status = setup._database_component()
    assert status["status"] == "error"

    with pytest.raises(Exception):
        setup.prepare_local_environment()

    with sqlite3.connect(local_paths["DB_FILE"]) as connection:
        assert connection.execute("SELECT value FROM user_data").fetchone() == ("keep me",)


def test_explicit_repair_backs_up_and_recovers_a_partial_database(local_paths):
    local_paths["DATA_DIR"].mkdir(parents=True)
    with sqlite3.connect(local_paths["DB_FILE"]) as connection:
        connection.execute("CREATE TABLE user_data(value TEXT)")
        connection.execute("INSERT INTO user_data VALUES('keep me')")

    setup._prepare_storage(repair=True)

    backups = list(local_paths["DATA_DIR"].glob("scraper_analysis.db.backup-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT value FROM user_data").fetchone() == ("keep me",)
    with sqlite3.connect(local_paths["DB_FILE"]) as connection:
        assert connection.execute("SELECT value FROM user_data").fetchone() == ("keep me",)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"niches", "search_runs", "snapshots", "schema_migrations"} <= tables


def test_missing_dependencies_and_unverified_browser_do_not_report_ready(monkeypatch, local_paths):
    monkeypatch.setattr(setup, "_missing_imports", lambda: ["playwright"])
    assert setup._python_component()["status"] == "missing"
    assert setup._browser_component(deep_check=False)["status"] == "missing"

    monkeypatch.setattr(setup, "_missing_imports", lambda: [])
    browser_path = Path(local_paths["DATA_DIR"]) / "chromium.exe"
    signature = (str(browser_path), 10, 1)
    monkeypatch.setattr(setup, "_browser_signature", lambda: (signature, browser_path))
    monkeypatch.setattr(setup, "_BROWSER_PROBE", None)
    assert setup._browser_component(deep_check=False)["status"] == "unknown"
    monkeypatch.setattr(setup, "_BROWSER_PROBE", (signature, False, "Browser launch failed."))
    assert setup._browser_component(deep_check=False)["status"] == "error"


def test_missing_python_package_repair_uses_pip_without_a_shell(monkeypatch):
    missing = iter((["playwright"], []))
    commands = []
    monkeypatch.setattr(setup, "_missing_imports", lambda: next(missing))

    def run_command(command, *, timeout):
        commands.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(setup, "_run_command", run_command)

    setup._install_python_dependencies()

    assert commands[0][0][:3] == [setup.sys.executable, "-m", "pip"]
    assert commands[0][0][-2:] == ["-r", str(setup.config.PROJECT_ROOT / "requirements.txt")]
    assert commands[0][1] == 600


def test_browser_repair_installs_and_launch_verifies_chromium(monkeypatch):
    ready = setup._component("browser", "Playwright Chromium", "ready", "Launch verified")
    commands = []
    monkeypatch.setattr(
        setup,
        "_browser_component",
        lambda *, deep_check: ready,
    )

    def run_command(command, *, timeout):
        commands.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(setup, "_run_command", run_command)

    setup._initialize_browser(repair=True)

    assert commands[0][0][1:] == ["-m", "playwright", "install", "chromium"]
    assert commands[0][1] == 600


def test_repair_backs_up_invalid_saved_settings_before_reset(monkeypatch, local_paths):
    settings_file = local_paths["SCRAPER_SETTINGS_FILE"]
    local_paths["DATA_DIR"].mkdir(parents=True)
    settings_file.write_text("{invalid", encoding="utf-8")
    settings_module = importlib.import_module("src.storage.backend.scraper_settings")

    def reset_to_defaults():
        settings_file.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(settings_module, "reset_scraper_settings", reset_to_defaults)
    assert setup._settings_component()["status"] == "error"

    setup._preserve_invalid_settings()

    backups = list(settings_file.parent.glob("scraper_settings.json.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{invalid"
    assert settings_file.read_text(encoding="utf-8") == "{}\n"


def _wait_for_operation(timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        operation = setup.get_initialization_status()
        if operation and operation["status"] != "running":
            return operation
        time.sleep(0.01)
    raise AssertionError("Environment setup operation did not finish")


def _mock_successful_steps(monkeypatch):
    ready = setup._component("component", "Component", "ready", "Ready")
    monkeypatch.setattr(setup, "_cross_process_setup_lock", nullcontext)
    monkeypatch.setattr(setup, "_probe_directories", lambda **_: ready)
    monkeypatch.setattr(setup, "_install_python_dependencies", lambda: None)
    monkeypatch.setattr(setup, "_prepare_storage", lambda **_: None)
    monkeypatch.setattr(setup, "_preserve_invalid_settings", lambda: None)
    monkeypatch.setattr(setup, "_initialize_browser", lambda **_: None)
    monkeypatch.setattr(setup, "_python_component", lambda: ready)
    monkeypatch.setattr(setup, "_database_component", lambda: ready)
    monkeypatch.setattr(setup, "_settings_component", lambda: ready)
    monkeypatch.setattr(setup, "_browser_component", lambda **_: ready)
    monkeypatch.setattr(setup, "get_environment_status", lambda **_: {"ready": True, "issues": []})
    main = importlib.import_module("src.storage.backend.main")
    monkeypatch.setattr(main, "start_operational_services", lambda: None)


def test_initialization_reports_stage_progress_and_success(monkeypatch):
    _mock_successful_steps(monkeypatch)

    initial = setup.start_initialization()
    assert initial["status"] in {"running", "completed"}
    assert initial["total"] == 5

    result = _wait_for_operation()
    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert {stage["status"] for stage in result["stages"]} == {"ready"}


def test_initialization_failure_is_reported_at_the_database_stage(monkeypatch):
    _mock_successful_steps(monkeypatch)
    monkeypatch.setattr(setup, "_prepare_storage", lambda **_: (_ for _ in ()).throw(RuntimeError("migration failure")))

    setup.start_initialization()
    result = _wait_for_operation()

    assert result["status"] == "failed"
    assert result["stages"][2]["status"] == "error"
    assert "Existing data was preserved" in result["error"]


def test_parallel_initialization_requests_share_one_operation(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def wait_for_release(operation_id, repair):
        calls.append((operation_id, repair))
        started.set()
        assert release.wait(1)
        with setup._STATUS_LOCK:
            setup._OPERATION.update(status="completed", progress=100)

    monkeypatch.setattr(setup, "_complete_operation", wait_for_release)
    first = setup.start_initialization()
    assert started.wait(1)
    second = setup.start_initialization(repair=True)
    assert second["id"] == first["id"]
    assert len(calls) == 1

    release.set()
    assert _wait_for_operation()["status"] == "completed"


def test_scrape_api_explains_readiness_block(monkeypatch):
    from fastapi import HTTPException

    from src.storage.backend.routes import scrape

    monkeypatch.setattr(
        scrape,
        "get_environment_status",
        lambda: {
            "scraper_ready": False,
            "issues": [{"id": "browser", "name": "Chromium", "message": "Chromium is missing."}],
        },
    )

    with pytest.raises(HTTPException) as error:
        scrape.start_scrape({"pages": 1, "products": 1})
    assert error.value.status_code == 503
    assert "Open Settings > Environment Setup & Maintenance" in error.value.detail


def test_scheduled_scrapes_are_not_claimed_while_environment_is_unhealthy(monkeypatch):
    from src.storage.backend import demand_service

    monkeypatch.setattr(
        demand_service,
        "get_environment_status",
        lambda: {"scraper_ready": False},
    )

    assert demand_service.run_due_schedules() == 0


def test_environment_api_returns_live_status_and_operation(monkeypatch):
    from fastapi import HTTPException

    from src.storage.backend import main

    expected = {"ready": False, "scraper_ready": False, "components": [], "issues": []}
    verified = {"ready": True, "scraper_ready": True, "components": [], "issues": []}
    operation = {"id": "setup-1", "status": "running"}
    monkeypatch.setattr(main, "get_environment_status", lambda **_: expected)
    monkeypatch.setattr(main, "check_environment", lambda **_: verified)
    monkeypatch.setattr(main, "get_initialization_status", lambda: operation)
    monkeypatch.setattr(main, "start_initialization", lambda **_: operation)

    assert main.api_environment_status() == {"environment": expected, "operation": operation}
    assert main.api_check_environment() == {"environment": verified, "operation": operation}
    assert main.api_initialize_environment({"repair": True}) == {
        "environment": expected,
        "operation": operation,
    }
    with pytest.raises(HTTPException) as error:
        main.api_initialize_environment({"repair": "true"})
    assert error.value.status_code == 422
