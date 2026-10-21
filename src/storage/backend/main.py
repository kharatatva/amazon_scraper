"""Expose dashboard, scraper, schedule, and demand endpoints through FastAPI."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from src.config import LOG_DIR
from src.logger import configure_logging, logger
from src.storage.backend import dashboard_queries as dashboard
from src.storage.backend.demand_service import (
    enqueue_demand_backfill,
    enqueue_demand_backfill_if_needed,
    get_demand_backfill_status,
    start_background_services,
)
from src.storage.backend.routes.scrape import router as scrape_router
from src.storage.db import get_connection
from src.storage.demand_schema import ensure_demand_schema
from src.storage.queries import get_price_history, get_rank_history, upsert_scheduled_niche

app = FastAPI(title="NicheScope Dashboard API", version="1.0.0")
configure_logging(LOG_DIR / "api.log")
app.include_router(scrape_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(sqlite3.Error)
async def sqlite_error_handler(_request: Request, exc: sqlite3.Error) -> JSONResponse:
    """Return a safe HTTP error response when a SQLite query fails."""
    logger.error("Dashboard SQLite request failed: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Database query failed. See the API log for details."})


def _date_range(start_date: date | None, end_date: date | None) -> tuple[str | None, str | None]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    return (start_date.isoformat() if start_date else None, end_date.isoformat() if end_date else None)


@app.get("/api/health")
def api_health() -> dict[str, str]:
    """Check database connectivity for the API health endpoint."""
    with dashboard._connect() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "connected"}


@app.get("/api/dashboard")
def api_dashboard() -> dict:
    """Return the dashboard summary payload."""
    return dashboard.dashboard_summary()


@app.get("/api/niches")
def api_list_niches(search: str | None = Query(default=None, max_length=120),
                    keyword_id: int | None = Query(default=None, ge=1)) -> list[dict]:
    """Return niches filtered by the requested search and keyword."""
    return dashboard.list_niches(search=search, keyword_id=keyword_id)


@app.get("/api/niches/{niche_id}")
def api_get_niche(niche_id: int) -> dict:
    """Return one niche or a 404 response when it is absent."""
    niche = dashboard.get_niche(niche_id)
    if niche is None:
        raise HTTPException(status_code=404, detail="Niche not found")
    return niche


@app.get("/api/niches/{niche_id}/runs")
def api_list_niche_runs(niche_id: int, page: int = Query(default=1, ge=1),
                        page_size: int = Query(default=50, ge=1, le=100)) -> dict:
    """Return search runs associated with one niche."""
    return dashboard.list_runs(niche_id=niche_id, page=page, page_size=page_size)


@app.get("/api/niches/{niche_id}/runs/{search_run_id}/opportunities")
def api_niche_run_opportunities(niche_id: int, search_run_id: int) -> list[dict]:
    """Return scored opportunities for one niche run."""
    run = dashboard.get_run(search_run_id)
    if run is None or run["niche_id"] != niche_id:
        raise HTTPException(status_code=404, detail="Search run not found for this niche")
    return dashboard.run_opportunities(niche_id, search_run_id)


@app.get("/api/products")
def api_list_products(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, max_length=160),
    niche_id: int | None = Query(default=None, ge=1), keyword_id: int | None = Query(default=None, ge=1),
    seller_id: int | None = Query(default=None, ge=1), brand: str | None = Query(default=None, max_length=120),
    fulfillment_type: Literal["FBA", "FBM", "Unknown"] | None = None,
    currency: str | None = Query(default=None, min_length=1, max_length=16),
    price_min: float | None = Query(default=None, ge=0), price_max: float | None = Query(default=None, ge=0),
    rating_min: float | None = Query(default=None, ge=0, le=5), reviews_min: int | None = Query(default=None, ge=0),
    sort: Literal["first_seen_at", "title", "asin", "price", "rating", "review_count", "search_rank_position", "final_score"] = "first_seen_at",
    order: Literal["asc", "desc"] = "desc",
) -> dict:
    """Return products filtered and paginated for the dashboard."""
    if price_min is not None and price_max is not None and price_min > price_max:
        raise HTTPException(status_code=422, detail="price_min must be less than or equal to price_max")
    if (price_min is not None or price_max is not None) and currency is None:
        currencies = dashboard.available_filters()["currencies"]
        if len(currencies) > 1:
            raise HTTPException(status_code=422, detail="currency is required for price bounds when multiple currencies are stored")
    return dashboard.list_products(
        page=page, page_size=page_size, search=search, niche_id=niche_id, keyword_id=keyword_id,
        seller_id=seller_id, brand=brand, fulfillment_type=fulfillment_type, currency=currency,
        price_min=price_min, price_max=price_max, rating_min=rating_min,
        reviews_min=reviews_min, sort=sort, order=order,
    )


@app.get("/api/products/filters")
def api_product_filters() -> dict:
    """Return available product filter values."""
    return dashboard.available_filters()


@app.get("/api/products/{product_id}/history")
def api_product_history(product_id: int, niche_id: int | None = Query(default=None, ge=1),
                        start_date: date | None = None, end_date: date | None = None) -> list[dict]:
    """Return snapshot history for one product."""
    start, end = _date_range(start_date, end_date)
    return dashboard.product_history(product_id, niche_id=niche_id, start_date=start, end_date=end)


@app.get("/api/products/{product_id}/price-history")
def api_product_price_history(product_id: int) -> list[tuple[str, float | None]]:
    """Return price history for one product."""
    return get_price_history(product_id)


@app.get("/api/products/{product_id}/rank-history")
def api_product_rank_history(product_id: int, niche_id: int = Query(ge=1)) -> list[tuple[str, int | None]]:
    """Return rank history for one product."""
    return get_rank_history(product_id, niche_id)


@app.get("/api/products/{product_id}")
def api_get_product(product_id: int) -> dict:
    """Return one product or a 404 response when it is absent."""
    product = dashboard.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/api/sellers")
def api_list_sellers(search: str | None = Query(default=None, max_length=120),
                     page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100)) -> dict:
    """Return sellers matching the requested search."""
    return dashboard.list_sellers(search, page=page, page_size=page_size)


@app.get("/api/sellers/{seller_id}")
def api_get_seller(seller_id: int, page: int = Query(default=1, ge=1),
                   page_size: int = Query(default=50, ge=1, le=100)) -> dict:
    """Return one seller or a 404 response when it is absent."""
    seller = dashboard.get_seller(seller_id, page=page, page_size=page_size)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    return seller


@app.get("/api/runs")
def api_list_runs(
    niche_id: int | None = Query(default=None, ge=1), keyword_id: int | None = Query(default=None, ge=1),
    status: Literal["success", "partial", "failed", "running"] | None = None,
    start_date: date | None = None, end_date: date | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
) -> dict:
    """Return search runs matching the requested filters."""
    start, end = _date_range(start_date, end_date)
    return dashboard.list_runs(niche_id=niche_id, keyword_id=keyword_id, status=status,
                               start_date=start, end_date=end, page=page, page_size=page_size)


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: int) -> dict:
    """Return one search run or a 404 response when it is absent."""
    run = dashboard.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Search run not found")
    return run


@app.get("/api/errors")
def api_list_errors(run_id: int | None = Query(default=None, ge=1), error_type: str | None = Query(default=None, max_length=120),
                    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100)) -> dict:
    """Return scrape errors matching the requested filters."""
    return dashboard.list_errors(run_id=run_id, error_type=error_type, page=page, page_size=page_size)


@app.get("/api/schedules")
def api_list_schedules() -> list[dict]:
    """Return configured search schedules."""
    return dashboard.list_schedules()


@app.delete("/api/schedules/{schedule_id}")
def api_delete_schedule(schedule_id: int) -> dict[str, bool]:
    """Deactivate a schedule and return its deletion status."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM scheduled_niches WHERE id=?", (schedule_id,))
        conn.commit()
    finally:
        conn.close()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": True}


@app.get("/api/demand")
def api_demand_tracker(
    niche_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=250),
) -> dict:
    """Return demand scores and backfill progress."""
    return dashboard.demand_tracker(niche_id, page=page, page_size=page_size)


@app.post("/api/demand/schedules")
def api_create_demand_schedule(payload: dict) -> dict:
    """Create or update a recurring niche demand schedule."""
    try:
        niche_id = int(payload["nicheId"])
        keyword_id = int(payload["keywordId"])
        pages = int(payload.get("pages", 10))
        products = int(payload.get("products", 100))
        run_times = str(payload.get("runTimes", "08:00,20:00"))
        timezone_name = str(payload.get("timezone", "Asia/Kolkata"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="nicheId and keywordId must be integers.") from exc
    if pages < 1 or pages > 100 or products < 1 or products > 10000:
        raise HTTPException(status_code=400, detail="pages must be 1–100 and products 1–10000.")
    conn = get_connection()
    try:
        linked = conn.execute(
            "SELECT 1 FROM niche_keywords WHERE niche_id=? AND keyword_id=?",
            (niche_id, keyword_id),
        ).fetchone()
    finally:
        conn.close()
    if not linked:
        raise HTTPException(status_code=400, detail="The keyword is not linked to the selected niche.")
    try:
        schedule_id = upsert_scheduled_niche(
            niche_id, keyword_id, "daily", pages, products, run_times, timezone_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": schedule_id, "active": True, "runTimes": run_times, "timezone": timezone_name}


@app.post("/api/demand/backfill")
def api_start_demand_backfill() -> dict:
    """Queue demand backfill work for eligible search runs."""
    return enqueue_demand_backfill()


@app.get("/api/demand/backfill")
def api_get_demand_backfill() -> dict | None:
    """Return the latest demand backfill status."""
    return get_demand_backfill_status()


@app.get("/api/demand/backfill/{job_id}")
def api_get_demand_backfill_job(job_id: int) -> dict:
    """Return one demand backfill job or a 404 response."""
    job = get_demand_backfill_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Demand backfill job not found")
    return job


@app.get("/api/analytics")
def api_analytics(niche_id: int | None = Query(default=None, ge=1), start_date: date | None = None,
                  end_date: date | None = None, limit: int = Query(default=5000, ge=1, le=10000),
                  currency: str | None = Query(default=None, min_length=1, max_length=16)) -> dict:
    """Return analytics for the requested niche and date range."""
    start, end = _date_range(start_date, end_date)
    return dashboard.analytics(niche_id=niche_id, start_date=start, end_date=end, limit=limit, currency=currency)


@app.on_event("startup")
def start_dashboard_workers() -> None:
    """Start the background workers used by dashboard services."""
    ensure_demand_schema()
    enqueue_demand_backfill_if_needed()
    start_background_services()

