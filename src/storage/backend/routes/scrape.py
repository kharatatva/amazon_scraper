"""Queue validated dashboard scrape requests for the existing Python pipeline."""

from fastapi import APIRouter, HTTPException

from src.config import MAX_DETAIL_PAGES_PER_RUN, MAX_PAGES_TO_CRAWL
from src.storage.backend.job_manager import (
    ActiveScrapeConflict,
    enqueue_existing_scrape_run,
    enqueue_scrape_batch,
)
from src.storage.backend.environment_setup import get_environment_status, readiness_error
from src.storage.db import get_connection, update_search_run
from src.storage.queries import create_running_search_run, upsert_scheduled_niche

router = APIRouter()


def _integer(payload: dict, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=422, detail=f"{key} must be an integer.")
    return value


def _limits(payload: dict) -> tuple[int, int]:
    pages = _integer(payload, "pages")
    products = _integer(payload, "products")
    if not 1 <= pages <= MAX_PAGES_TO_CRAWL:
        raise HTTPException(
            status_code=422,
            detail=f"pages must be between 1 and {MAX_PAGES_TO_CRAWL}.",
        )
    if not 1 <= products <= MAX_DETAIL_PAGES_PER_RUN:
        raise HTTPException(
            status_code=422,
            detail=f"products must be between 1 and {MAX_DETAIL_PAGES_PER_RUN}.",
        )
    return pages, products


@router.post("/api/scrape/start", status_code=202)
def start_scrape(payload: dict):
    """Create one persisted run per keyword and place each on the managed queue."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="A JSON object is required.")
    readiness = get_environment_status()
    if not readiness["scraper_ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Scraping is unavailable until the local environment is ready. {readiness_error(readiness)} Open Settings > Environment Setup & Maintenance to resolve this.",
        )
    pages, products = _limits(payload)

    if "nicheName" in payload or "keywords" in payload:
        try:
            run_ids = enqueue_scrape_batch(
                niche_name=payload.get("nicheName"),
                keywords=payload.get("keywords"),
                pages=pages,
                products=products,
            )
        except ActiveScrapeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"accepted": True, "runId": run_ids[0], "runIds": run_ids}

    try:
        niche_id = _integer(payload, "nicheId")
        keyword_id = _integer(payload, "keywordId")
    except HTTPException as exc:
        raise HTTPException(
            status_code=422,
            detail="Provide nicheName and keywords, or integer nicheId and keywordId values.",
        ) from exc
    recurring = payload.get("recurring", False)
    frequency = payload.get("frequency", "daily")
    if not isinstance(recurring, bool):
        raise HTTPException(status_code=422, detail="recurring must be a boolean.")
    if recurring and (not isinstance(frequency, str) or frequency not in {"daily", "weekly"}):
        raise HTTPException(status_code=422, detail="frequency must be 'daily' or 'weekly'.")

    conn = get_connection()
    try:
        pair = conn.execute(
            """SELECT 1 FROM niche_keywords
                 WHERE niche_id=? AND keyword_id=?""",
            (niche_id, keyword_id),
        ).fetchone()
        if pair is None:
            raise HTTPException(status_code=404, detail="The keyword is not associated with that niche.")
        active = conn.execute(
            """SELECT id FROM search_runs
                 WHERE niche_id=? AND keyword_id=? AND status='running'
                 ORDER BY id DESC LIMIT 1""",
            (niche_id, keyword_id),
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail=f"Run #{active[0]} is already active for this niche and keyword.")
    finally:
        conn.close()

    run_id = create_running_search_run(niche_id, keyword_id)
    try:
        enqueue_existing_scrape_run(run_id, pages, products)
    except ActiveScrapeConflict as exc:
        update_search_run(
            search_run_id=run_id,
            status="failed",
            current_stage="failed",
            current_task="Duplicate run rejected",
            notes=str(exc),
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        update_search_run(
            search_run_id=run_id,
            status="failed",
            current_stage="failed",
            current_task="Invalid run request",
            notes=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if recurring:
        upsert_scheduled_niche(niche_id, keyword_id, frequency, pages, products)
    return {"accepted": True, "runId": run_id, "runIds": [run_id]}
