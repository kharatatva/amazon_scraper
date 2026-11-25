"""Offline coverage for dashboard-created scraper jobs."""

import json
import sqlite3

import pytest

from src.storage.backend import dashboard_queries, job_manager


def test_new_niche_and_multiple_keywords_create_queued_runs(temp_database, monkeypatch):
    monkeypatch.setattr(job_manager, "_wake_worker", lambda: None)

    run_ids = job_manager.enqueue_scrape_batch(
        "Portable Blenders",
        ["usb travel blender", "rechargeable smoothie blender"],
        pages=4,
        products=35,
    )

    assert len(run_ids) == 2
    with sqlite3.connect(temp_database) as connection:
        niche = connection.execute(
            "SELECT id,name,slug FROM niches WHERE name='portable blenders'"
        ).fetchone()
        keywords = connection.execute(
            """SELECT k.text FROM keywords k JOIN niche_keywords nk ON nk.keyword_id=k.id
                 WHERE nk.niche_id=? ORDER BY k.text""",
            (niche[0],),
        ).fetchall()
        runs = connection.execute(
            "SELECT id,status,current_stage,config_json FROM search_runs ORDER BY id DESC LIMIT 2"
        ).fetchall()

    assert niche[1:] == ("portable blenders", "portable-blenders")
    assert [row[0] for row in keywords] == [
        "rechargeable smoothie blender",
        "usb travel blender",
    ]
    assert {row[1:3] for row in runs} == {("running", "queued")}
    assert all(
        json.loads(row[3])["_nichescope"]["requested_pages"] == 4
        and json.loads(row[3])["_nichescope"]["requested_products"] == 35
        for row in runs
    )

    queued = dashboard_queries.get_run(run_ids[0])
    assert queued["status"] == "queued"
    assert queued["products_processed"] == 0
    assert queued["requested_pages"] == 4
    assert queued["requested_products"] == 35


def test_active_duplicate_is_rejected_without_creating_more_runs(temp_database, monkeypatch):
    monkeypatch.setattr(job_manager, "_wake_worker", lambda: None)
    job_manager.enqueue_scrape_batch("coffee gear", ["manual coffee grinder"], 2, 20)

    with pytest.raises(job_manager.ActiveScrapeConflict):
        job_manager.enqueue_scrape_batch("Coffee Gear", ["manual coffee grinder"], 2, 20)

    with sqlite3.connect(temp_database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
    assert count == 4


@pytest.mark.parametrize(
    ("niche", "keywords", "pages", "products"),
    [
        ("", ["valid keyword"], 1, 1),
        ("valid niche", [""], 1, 1),
        ("valid niche", ["same keyword", "Same Keyword"], 1, 1),
        ("valid niche", ["valid keyword"], 11, 1),
        ("valid niche", ["valid keyword"], 1, 101),
    ],
)
def test_invalid_scrape_configuration_is_rejected(
    temp_database, monkeypatch, niche, keywords, pages, products
):
    monkeypatch.setattr(job_manager, "_wake_worker", lambda: None)
    with pytest.raises(ValueError):
        job_manager.enqueue_scrape_batch(niche, keywords, pages, products)

    with sqlite3.connect(temp_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0] == 3


def test_queue_claim_respects_single_process_limit(temp_database, monkeypatch):
    monkeypatch.setattr(job_manager, "_wake_worker", lambda: None)
    run_ids = job_manager.enqueue_scrape_batch(
        "desk accessories",
        ["desk shelf", "monitor riser"],
        pages=1,
        products=5,
    )

    first = job_manager._claim_next_run()
    second = job_manager._claim_next_run()

    assert first["run_id"] == run_ids[0]
    assert second is None


def test_failed_process_is_persisted_in_run_history(temp_database, monkeypatch):
    monkeypatch.setattr(job_manager, "_wake_worker", lambda: None)
    run_id = job_manager.enqueue_scrape_batch(
        "travel mugs",
        ["insulated travel mug"],
        pages=1,
        products=5,
    )[0]

    job_manager._mark_failed(run_id, "Fixture process failure.", "ProcessExit")
    run = dashboard_queries.get_run(run_id)

    assert run["status"] == "failed"
    assert run["current_stage"] == "failed"
    assert run["notes"] == "Fixture process failure."
    assert run["error_count"] == 1
    assert run["finished_at"] is not None
