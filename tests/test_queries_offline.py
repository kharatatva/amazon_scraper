"""Storage query tests against the shared temporary SQLite database."""

from src.storage import queries


def test_niche_snapshot_returns_only_the_requested_run(temp_database):
    snapshot = queries.get_niche_snapshot(niche_id=1, search_run_id=1)

    assert len(snapshot) == 1
    assert snapshot[0]["product_id"] == 1
    assert snapshot[0]["asin"] == "B012345678"
    assert snapshot[0]["review_count"] == 25


def test_latest_run_and_product_detail_use_seeded_rows(temp_database):
    latest_run = queries.get_latest_run_for_niche(niche_id=1)
    product = queries.get_product_detail(product_id=1)

    assert latest_run == 3
    assert product["asin"] == "B012345678"
    assert product["title"] == "Test product"
