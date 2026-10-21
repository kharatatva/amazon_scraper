"""Background scheduling and demand-score backfill for the dashboard API."""

from __future__ import annotations

import subprocess
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config import PROJECT_ROOT
from src.logger import logger
from src.storage.db import get_connection, update_search_run
from src.storage.queries import create_running_search_run

_worker_lock = threading.Lock()
_worker_started = False
_POLL_SECONDS = 30


def _utc_now() -> str:
    return datetime.now(datetime_timezone.utc).isoformat()


def _resolve_timezone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError):
        if name == "Asia/Kolkata":
            return datetime_timezone(timedelta(hours=5, minutes=30), name=name)
        raise


def _scheduled_slots(schedule) -> list[str]:
    slots = sorted({value.strip() for value in (schedule["run_times"] or "").split(",") if value.strip()})
    valid = []
    for value in slots:
        try:
            datetime.strptime(value, "%H:%M")
            valid.append(value)
        except ValueError:
            logger.error("Ignoring invalid schedule time | schedule_id=%s | time=%s", schedule["id"], value)
    return valid


def _claim_schedule(schedule_id: int, slot_key: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """UPDATE scheduled_niches
                  SET last_slot_key=?,last_triggered_at=?
                WHERE id=? AND is_active=1
                  AND COALESCE(last_slot_key,'')<>?
                  AND NOT EXISTS (
                      SELECT 1 FROM search_runs sr
                       WHERE sr.niche_id=scheduled_niches.niche_id
                         AND sr.keyword_id=scheduled_niches.keyword_id
                         AND sr.status='running'
                  )""",
            (slot_key, _utc_now(), schedule_id, slot_key),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def _launch_scheduled_run(schedule) -> None:
    run_id = create_running_search_run(int(schedule["niche_id"]), int(schedule["keyword_id"]))
    command = [
        sys.executable, "scripts/run_full_pipeline.py",
        "--run-id", str(run_id),
        "--pages", str(schedule["pages"]),
        "--products", str(schedule["products"]),
    ]
    try:
        subprocess.Popen(command, cwd=PROJECT_ROOT)
        logger.info("Scheduled pipeline launched | schedule_id=%s | run_id=%s", schedule["id"], run_id)
    except OSError:
        logger.exception("Could not launch scheduled pipeline | schedule_id=%s | run_id=%s", schedule["id"], run_id)
        update_search_run(
            search_run_id=run_id,
            status="failed",
            current_stage="failed",
            notes="Could not launch scheduled pipeline subprocess.",
        )


def run_due_schedules(now: datetime | None = None) -> int:
    """Claim and launch schedule slots matching the current local minute."""
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        schedules = conn.execute("SELECT * FROM scheduled_niches WHERE is_active=1 ORDER BY id").fetchall()
    finally:
        conn.close()

    launched = 0
    for schedule in schedules:
        try:
            zone = _resolve_timezone(schedule["timezone"] or "Asia/Kolkata")
        except (ZoneInfoNotFoundError, TypeError):
            logger.error("Invalid timezone on schedule | schedule_id=%s", schedule["id"])
            continue
        local_now = now.astimezone(zone) if now is not None and now.tzinfo else (now.replace(tzinfo=zone) if now is not None else datetime.now(zone))
        slots = _scheduled_slots(schedule)
        if schedule["frequency"] == "weekly":
            slots = slots[:1] if local_now.weekday() == 0 else []
        current_slot = local_now.strftime("%H:%M")
        if current_slot not in slots:
            continue
        slot_key = f"{local_now.date().isoformat()}T{current_slot}"
        if not _claim_schedule(int(schedule["id"]), slot_key):
            continue
        _launch_scheduled_run(schedule)
        launched += 1
    return launched


def enqueue_demand_backfill() -> dict:
    """Persist a demand backfill job and queue it for processing."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "SELECT id,status,total_runs,processed_runs,products_scored,created_at,started_at,completed_at,error_message "
            "FROM demand_backfill_jobs WHERE status IN ('queued','running') ORDER BY id DESC LIMIT 1"
        )
        active = cursor.fetchone()
        if active:
            columns = [column[0] for column in cursor.description]
            conn.commit()
            return {**dict(zip(columns, active)), "already_active": True}
        total_runs = conn.execute(
            """SELECT COUNT(*) FROM search_runs sr
                WHERE sr.status IN ('success','partial')
                  AND EXISTS (SELECT 1 FROM snapshots sn WHERE sn.search_run_id=sr.id)"""
        ).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO demand_backfill_jobs(status,total_runs,created_at) VALUES ('queued',?,?)",
            (total_runs, _utc_now()),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "status": "queued", "total_runs": total_runs,
                "processed_runs": 0, "products_scored": 0, "created_at": _utc_now(),
                "started_at": None, "completed_at": None, "error_message": None,
                "already_active": False}
    finally:
        conn.close()


def enqueue_demand_backfill_if_needed() -> dict | None:
    """Queue one automatic historical recalculation for pre-v1 score rows."""
    conn = get_connection()
    try:
        outdated = conn.execute(
            """SELECT COUNT(*) FROM search_runs sr JOIN snapshots sn ON sn.search_run_id=sr.id
                 LEFT JOIN opportunity_scores os ON os.snapshot_id=sn.id
                WHERE sr.status IN ('success','partial')
                  AND (os.snapshot_id IS NULL OR COALESCE(os.demand_score_version,0)<1)"""
        ).fetchone()[0]
    finally:
        conn.close()
    if not outdated:
        return None
    job = enqueue_demand_backfill()
    logger.info("Queued historical demand-score backfill | stale_snapshots=%s | job_id=%s", outdated, job["id"])
    return job


def get_demand_backfill_status(job_id: int | None = None) -> dict | None:
    """Read the status and progress of a demand backfill job."""
    conn = get_connection()
    try:
        if job_id is None:
            row = conn.execute(
                "SELECT * FROM demand_backfill_jobs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM demand_backfill_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        columns = [column[0] for column in conn.execute("SELECT * FROM demand_backfill_jobs LIMIT 0").description]
        return dict(zip(columns, row))
    finally:
        conn.close()


def _claim_backfill_job() -> dict | None:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id FROM demand_backfill_jobs WHERE status='queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        job_id = row[0]
        conn.execute(
            "UPDATE demand_backfill_jobs SET status='running',started_at=? WHERE id=? AND status='queued'",
            (_utc_now(), job_id),
        )
        conn.commit()
        return get_demand_backfill_status(job_id)
    finally:
        conn.close()


def _process_backfill_job(job: dict) -> None:
    from scripts.run_scoring import run_scoring

    conn = get_connection()
    try:
        run_ids = [row[0] for row in conn.execute(
            """SELECT sr.id FROM search_runs sr
                WHERE sr.status IN ('success','partial')
                  AND EXISTS (SELECT 1 FROM snapshots sn WHERE sn.search_run_id=sr.id)
                ORDER BY sr.run_timestamp,sr.id"""
        ).fetchall()]
    finally:
        conn.close()

    processed = 0
    products_scored = 0
    errors = []
    for run_id in run_ids:
        try:
            result = run_scoring(int(run_id))
            products_scored += len(result)
        except Exception as exc:
            errors.append(f"run {run_id}: {exc}")
            logger.exception("Demand backfill failed for search run %s", run_id)
        processed += 1
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE demand_backfill_jobs SET processed_runs=?,products_scored=? WHERE id=?",
                (processed, products_scored, job["id"]),
            )
            conn.commit()
        finally:
            conn.close()

    status = "failed" if errors else "completed"
    error_message = "\n".join(errors[:10]) if errors else None
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE demand_backfill_jobs SET status=?,completed_at=?,error_message=? WHERE id=?",
            (status, _utc_now(), error_message, job["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Demand backfill finished | job_id=%s | runs=%s | errors=%s", job["id"], processed, len(errors))


def _run_backfill_safely(job: dict) -> None:
    try:
        _process_backfill_job(job)
    except Exception as exc:
        logger.exception("Demand backfill worker failed | job_id=%s", job["id"])
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE demand_backfill_jobs SET status='failed',completed_at=?,error_message=? WHERE id=?",
                (_utc_now(), str(exc), job["id"]),
            )
            conn.commit()
        finally:
            conn.close()


def _worker_loop() -> None:
    while True:
        try:
            run_due_schedules()
            job = _claim_backfill_job()
            if job:
                threading.Thread(
                    target=_run_backfill_safely,
                    args=(job,),
                    name=f"demand-backfill-{job['id']}",
                    daemon=True,
                ).start()
        except Exception:
            logger.exception("Demand tracker background worker iteration failed")
        time.sleep(_POLL_SECONDS)


def start_background_services() -> None:
    """Start the DB-claimed schedule and backfill worker for this API process."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name="nichescope-demand-worker", daemon=True)
        thread.start()
        _worker_started = True
        logger.info("Demand tracker worker started")
