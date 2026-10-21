"""Start a pipeline subprocess from an API request and manage schedules."""

import subprocess
import sys
from fastapi import APIRouter, HTTPException
from src.config import PROJECT_ROOT
from src.logger import logger
from src.storage.db import update_search_run
from src.storage.queries import create_running_search_run, upsert_scheduled_niche

router = APIRouter()


@router.post("/api/scrape/start")
def start_scrape(payload: dict):
    """Create a run, launch the pipeline subprocess, and optionally schedule it."""
    try:
        niche_id = int(payload["nicheId"])
        keyword_id = int(payload["keywordId"])
        pages = int(payload["pages"])
        products = int(payload["products"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="nicheId, keywordId, pages, and products are required integers.") from exc
    if pages < 1 or products < 1:
        raise HTTPException(status_code=400, detail="pages and products must be positive integers.")
    if payload.get("recurring") and payload.get("frequency") not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="frequency must be 'daily' or 'weekly'.")

    run_id = create_running_search_run(niche_id, keyword_id)

    command = [
        sys.executable, "scripts/run_full_pipeline.py",
        "--run-id", str(run_id),
        "--pages", str(pages),
        "--products", str(products),
    ]
    try:
        subprocess.Popen(command, cwd=PROJECT_ROOT)
    except OSError:
        logger.exception("Could not launch pipeline subprocess | run_id=%s", run_id)
        update_search_run(
            search_run_id=run_id,
            status="failed",
            current_stage="failed",
            notes="Could not launch pipeline subprocess.",
        )
        raise HTTPException(status_code=500, detail="Could not launch the scraper pipeline.")
    logger.info("Pipeline subprocess launched | run_id=%s", run_id)
    if payload.get("recurring"):
        upsert_scheduled_niche(niche_id, keyword_id, payload["frequency"], pages, products)
    return {"accepted": True, "runId": run_id}
