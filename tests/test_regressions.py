"""Regression coverage for pipeline startup and storage call contracts."""

import importlib
import inspect
import sqlite3

from src.scraper.fetch import fetch_page
from src.storage import db


def test_pipeline_module_imports_without_starting_a_scrape():
    assert importlib.import_module("scripts.run_full_pipeline")


def test_product_fetch_call_binds_with_optional_proxy_arguments():
    bound = inspect.signature(fetch_page).bind(
        "https://example.test/product", object(), run_id=1
    )
    bound.apply_defaults()

    assert bound.arguments["run_id"] == 1
    assert bound.arguments["proxy_manager"] is None
    assert bound.arguments["context_factory"] is None


def test_log_scrape_error_inserts_a_row_in_the_temporary_database(temp_database):
    db.log_scrape_error(
        search_run_id=1,
        url="https://example.test/product",
        error_type="test-error",
        error_message="synthetic failure",
    )

    with sqlite3.connect(temp_database) as connection:
        row = connection.execute(
            "SELECT search_run_id, url, error_type, error_message, occurred_at "
            "FROM scrape_errors"
        ).fetchone()

    assert row[:4] == (
        1,
        "https://example.test/product",
        "test-error",
        "synthetic failure",
    )
    assert row[4]
