"""Persist and execute dashboard scraper jobs through one controlled worker."""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import (
    LOG_DIR,
    MAX_DETAIL_PAGES_PER_RUN,
    MAX_PAGES_TO_CRAWL,
    PROJECT_ROOT,
)
from src.logger import logger
from src.storage.db import (
    get_connection,
    log_scrape_error,
    normalize_text,
    update_search_run,
    update_search_run_execution,
)

MAX_KEYWORDS_PER_REQUEST = 10
MAX_SCRAPE_RUNTIME_SECONDS = 6 * 60 * 60
_WORKER_POLL_SECONDS = 0.5
_worker_lock = threading.Lock()
_worker_started = False
_active_process_lock = threading.Lock()
_active_process: subprocess.Popen | None = None


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Stop a scraper and its browser children during timeout or shutdown."""
    if process.poll() is not None:
        return

    def force_kill() -> None:
        try:
            process.kill()
        except OSError:
            pass

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            force_kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            force_kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        force_kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.error("Scraper process did not stop after forced termination | pid=%s", process.pid)


def _terminate_active_process() -> None:
    with _active_process_lock:
        process = _active_process
    if process is not None:
        _terminate_process_tree(process)


atexit.register(_terminate_active_process)


class ActiveScrapeConflict(ValueError):
    """Raised when the same niche and keyword already have an active run."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_limits(pages: int, products: int) -> None:
    if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= MAX_PAGES_TO_CRAWL:
        raise ValueError(f"pages must be between 1 and {MAX_PAGES_TO_CRAWL}.")
    if (
        isinstance(products, bool)
        or not isinstance(products, int)
        or not 1 <= products <= MAX_DETAIL_PAGES_PER_RUN
    ):
        raise ValueError(f"products must be between 1 and {MAX_DETAIL_PAGES_PER_RUN}.")


def _get_or_create_niche(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM niches WHERE name=?", (name,)).fetchone()
    if row:
        return int(row[0])
    slug = re.sub(r"\s+", "-", name)
    collision = conn.execute("SELECT name FROM niches WHERE slug=?", (slug,)).fetchone()
    if collision:
        raise ValueError("That niche name conflicts with an existing niche slug.")
    cursor = conn.execute(
        "INSERT INTO niches(name,slug,created_at) VALUES(?,?,?)",
        (name, slug, _utc_now()),
    )
    return int(cursor.lastrowid)


def _get_or_create_keyword(conn, text: str) -> int:
    row = conn.execute("SELECT id FROM keywords WHERE text=?", (text,)).fetchone()
    if row:
        return int(row[0])
    cursor = conn.execute("INSERT INTO keywords(text) VALUES(?)", (text,))
    return int(cursor.lastrowid)


def enqueue_scrape_batch(niche_name: str, keywords: list[str], pages: int, products: int) -> list[int]:
    """Create/reuse the niche and keywords, then queue one run per keyword atomically."""
    _validate_limits(pages, products)
    if not isinstance(niche_name, str) or len(niche_name.strip()) > 120:
        raise ValueError("nicheName must be a string of at most 120 characters.")
    normalized_niche = normalize_text(niche_name)
    if not normalized_niche:
        raise ValueError("nicheName cannot be empty.")
    if not isinstance(keywords, list) or not 1 <= len(keywords) <= MAX_KEYWORDS_PER_REQUEST:
        raise ValueError(f"Submit between 1 and {MAX_KEYWORDS_PER_REQUEST} keywords.")

    normalized_keywords: list[str] = []
    for keyword in keywords:
        if not isinstance(keyword, str) or len(keyword.strip()) > 160:
            raise ValueError("Each keyword must be a string of at most 160 characters.")
        normalized = normalize_text(keyword)
        if not normalized:
            raise ValueError("Keywords cannot be empty.")
        normalized_keywords.append(normalized)
    if len(set(normalized_keywords)) != len(normalized_keywords):
        raise ValueError("Keywords must be unique after normalization.")

    conn = get_connection()
    run_ids: list[int] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        niche_id = _get_or_create_niche(conn, normalized_niche)
        keyword_ids = [_get_or_create_keyword(conn, keyword) for keyword in normalized_keywords]

        for keyword_id in keyword_ids:
            active = conn.execute(
                """SELECT id FROM search_runs
                    WHERE niche_id=? AND keyword_id=? AND status='running'
                    ORDER BY id DESC LIMIT 1""",
                (niche_id, keyword_id),
            ).fetchone()
            if active:
                raise ActiveScrapeConflict(
                    f"A run for '{normalized_niche}' and "
                    f"'{normalized_keywords[keyword_ids.index(keyword_id)]}' is already active."
                )

        now = _utc_now()
        conn.executemany(
            "INSERT OR IGNORE INTO niche_keywords(niche_id,keyword_id) VALUES(?,?)",
            [(niche_id, keyword_id) for keyword_id in keyword_ids],
        )
        for keyword_id in keyword_ids:
            cursor = conn.execute(
                """INSERT INTO search_runs
                       (niche_id,keyword_id,run_timestamp,pages_scraped,products_found,
                        status,current_stage,current_task,config_json)
                   VALUES(?,?,?,0,0,'running','queued','Waiting for scraper worker',?)""",
                (
                    niche_id,
                    keyword_id,
                    now,
                    json.dumps(
                        {
                            "_nichescope": {
                                "managed": True,
                                "requested_pages": pages,
                                "requested_products": products,
                                "queued_at": now,
                            }
                        },
                        sort_keys=True,
                    ),
                ),
            )
            run_ids.append(int(cursor.lastrowid))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _wake_worker()
    return run_ids


def enqueue_existing_scrape_run(run_id: int, pages: int, products: int) -> None:
    """Put an existing run (for schedules or legacy callers) on the same queue."""
    _validate_limits(pages, products)
    now = _utc_now()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT niche_id,keyword_id,status FROM search_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Search run {run_id} does not exist.")
        if row[2] != "running":
            raise ValueError("Only a running search run can be queued.")
        active = conn.execute(
            """SELECT id FROM search_runs
                 WHERE niche_id=? AND keyword_id=? AND status='running' AND id<>?
                 ORDER BY id DESC LIMIT 1""",
            (row[0], row[1], run_id),
        ).fetchone()
        if active:
            raise ActiveScrapeConflict(
                f"Run #{active[0]} is already active for this niche and keyword."
            )
        config = {
            "_nichescope": {
                "managed": True,
                "requested_pages": pages,
                "requested_products": products,
                "queued_at": now,
            }
        }
        conn.execute(
            """UPDATE search_runs
                  SET current_stage='queued',current_task='Waiting for scraper worker',config_json=?
                WHERE id=?""",
            (json.dumps(config, sort_keys=True), run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _wake_worker()


def _wake_worker() -> None:
    # Queue polling is short and durable; no process-local queue can lose jobs.
    start_scrape_worker()


def _recover_interrupted_jobs() -> None:
    """Fail managed runs whose process disappeared, retaining live worker runs."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _reconcile_active_runs(conn)
        conn.commit()
    finally:
        conn.close()


def _process_is_alive(process_id: Any) -> bool:
    try:
        pid = int(process_id)
        if pid < 1:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _reconcile_active_runs(conn) -> bool:
    """Return whether a real process still occupies the single-run slot."""
    rows = conn.execute(
        """SELECT id,current_stage,config_json FROM search_runs
             WHERE status='running' AND COALESCE(current_stage,'') NOT IN ('queued','completed','failed')"""
    ).fetchall()
    active_process = False
    for run_id, current_stage, raw_config in rows:
        try:
            config = json.loads(raw_config) if raw_config else {}
        except (TypeError, json.JSONDecodeError):
            config = {}
        execution = config.get("_nichescope", {}) if isinstance(config, dict) else {}
        if not isinstance(execution, dict) or not execution.get("managed"):
            active_process = True
            continue
        if _process_is_alive(execution.get("process_id")):
            active_process = True
            continue

        claimed_at = execution.get("claimed_at")
        if not execution.get("process_id") and claimed_at:
            try:
                claimed = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - claimed).total_seconds() < 60:
                    active_process = True
                    continue
            except (AttributeError, TypeError, ValueError):
                pass

        now = _utc_now()
        message = "The managed scraper process is no longer available."
        execution["finished_at"] = now
        config["_nichescope"] = execution
        conn.execute(
            """UPDATE search_runs SET status='failed',current_stage='failed',
                   current_task='Scraper process interrupted',notes=?,config_json=? WHERE id=?""",
            (message, json.dumps(config, ensure_ascii=False, sort_keys=True), run_id),
        )
        conn.execute(
            """INSERT INTO scrape_errors
                   (search_run_id,url,error_type,error_message,attempt_number,occurred_at)
               VALUES(?,?,?,?,?,?)""",
            (run_id, "PIPELINE", "ProcessInterrupted", message, 1, now),
        )
        logger.warning("Marked interrupted scraper run as failed | run_id=%s | stage=%s", run_id, current_stage)
    return active_process


def _claim_next_run() -> dict[str, Any] | None:
    """Claim at most one active process across API workers using SQLite locking."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if _reconcile_active_runs(conn):
            conn.commit()
            return None
        row = conn.execute(
            """SELECT id,config_json FROM search_runs
                 WHERE status='running' AND current_stage='queued'
                 ORDER BY id LIMIT 1"""
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        run_id, raw_config = row
        try:
            config = json.loads(raw_config) if raw_config else {}
        except (TypeError, json.JSONDecodeError):
            config = {}
        execution = config.get("_nichescope", {}) if isinstance(config, dict) else {}
        if not isinstance(execution, dict) or not execution.get("managed"):
            conn.execute(
                "UPDATE search_runs SET status='failed',current_stage='failed',notes='Invalid queued job metadata.' WHERE id=?",
                (run_id,),
            )
            conn.commit()
            return None
        pages = execution.get("requested_pages")
        products = execution.get("requested_products")
        try:
            _validate_limits(pages, products)
        except ValueError as exc:
            conn.execute(
                """UPDATE search_runs SET status='failed',current_stage='failed',
                       current_task='Invalid scraper configuration',notes=? WHERE id=?""",
                (str(exc), run_id),
            )
            conn.commit()
            return None
        cursor = conn.execute(
            """UPDATE search_runs SET current_stage='starting',
                   current_task='Starting the scraper process'
                 WHERE id=? AND status='running' AND current_stage='queued'""",
            (run_id,),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        execution["claimed_at"] = _utc_now()
        config["_nichescope"] = execution
        conn.execute(
            "UPDATE search_runs SET config_json=? WHERE id=?",
            (json.dumps(config, ensure_ascii=False, sort_keys=True), run_id),
        )
        conn.commit()
        return {"run_id": int(run_id), "pages": pages, "products": products}
    except Exception:
        conn.rollback()
        logger.exception("Could not claim a queued scraper run.")
        return None
    finally:
        conn.close()


def _mark_failed(run_id: int, message: str, error_type: str) -> None:
    update_search_run(
        search_run_id=run_id,
        status="failed",
        current_stage="failed",
        current_task="Pipeline failed",
        notes=message,
    )
    try:
        log_scrape_error(
            search_run_id=run_id,
            url="PIPELINE",
            error_type=error_type,
            error_message=message,
        )
    except Exception:
        logger.exception("Could not record managed pipeline failure | run_id=%s", run_id)
    update_search_run_execution(run_id, finished_at=_utc_now())


def _execute_run(job: dict[str, Any]) -> None:
    global _active_process
    run_id = job["run_id"]
    from src.storage.backend.environment_setup import get_environment_status, readiness_error

    readiness = get_environment_status()
    if not readiness["scraper_ready"]:
        _mark_failed(
            run_id,
            "Scraper prerequisites are unavailable: " + readiness_error(readiness),
            "EnvironmentNotReady",
        )
        return
    process = None
    run_log = LOG_DIR / "runs" / f"{run_id}.log"
    run_log.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "scripts/run_full_pipeline.py",
        "--run-id",
        str(run_id),
        "--pages",
        str(job["pages"]),
        "--products",
        str(job["products"]),
        "--backend-managed",
    ]
    logger.info("Launching managed scraper | run_id=%s | pages=%s | products=%s", run_id, job["pages"], job["products"])
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with run_log.open("ab") as log_file:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                shell=False,
                close_fds=True,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            with _active_process_lock:
                _active_process = process
            try:
                update_search_run_execution(run_id, process_id=process.pid)
                return_code = process.wait(timeout=MAX_SCRAPE_RUNTIME_SECONDS)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process)
                _mark_failed(
                    run_id,
                    f"Scraper exceeded the {MAX_SCRAPE_RUNTIME_SECONDS // 3600}-hour runtime limit and was stopped.",
                    "ScrapeTimeout",
                )
                return
            except Exception:
                _terminate_process_tree(process)
                raise
            finally:
                with _active_process_lock:
                    if _active_process is process:
                        _active_process = None
        run = get_connection()
        try:
            row = run.execute(
                "SELECT status,current_stage FROM search_runs WHERE id=?",
                (run_id,),
            ).fetchone()
        finally:
            run.close()
        if return_code != 0:
            if row and row[0] == "failed":
                update_search_run_execution(
                    run_id,
                    finished_at=_utc_now(),
                    process_exit_code=return_code,
                )
            else:
                _mark_failed(run_id, f"Scraper process exited with code {return_code}.", "ProcessExit")
        elif not row or row[0] not in {"success", "partial"} or row[1] != "completed":
            _mark_failed(
                run_id,
                "Scraper process exited without recording a completed run.",
                "IncompleteProcess",
            )
        else:
            update_search_run_execution(run_id, finished_at=_utc_now(), process_exit_code=return_code)
        logger.info("Managed scraper finished | run_id=%s | exit_code=%s", run_id, return_code)
    except OSError as exc:
        logger.exception("Could not launch managed scraper | run_id=%s", run_id)
        _mark_failed(run_id, f"Could not launch the scraper process: {exc}", "ProcessLaunchError")
    except Exception as exc:
        logger.exception("Managed scraper supervisor failed | run_id=%s", run_id)
        _mark_failed(run_id, f"Scraper supervisor failed: {exc}", "ProcessManagerError")


def _worker_loop() -> None:
    _recover_interrupted_jobs()
    while True:
        job = _claim_next_run()
        if job is None:
            time.sleep(_WORKER_POLL_SECONDS)
            continue
        try:
            _execute_run(job)
        except Exception:
            logger.exception("Unexpected scraper worker error.")


def start_scrape_worker() -> None:
    """Start one durable queue worker for dashboard and scheduled scraping."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name="nichescope-scrape-worker", daemon=True)
        thread.start()
        _worker_started = True
