"""Shared isolated database fixtures for the offline test suite."""

import importlib
import sqlite3

import pytest


@pytest.fixture
def temp_database(tmp_path, monkeypatch):
    """Bootstrap and seed a temporary SQLite database for storage tests."""
    database_path = tmp_path / "scraper_analysis.db"
    module_names = (
        "src.config",
        "src.storage.db",
        "src.storage.init_db",
        "src.storage.migrations",
        "src.storage.queries",
        "src.storage.lifecycle",
        "src.storage.backend.dashboard_queries",
    )
    modules = [importlib.import_module(name) for name in module_names]
    for module in modules:
        if hasattr(module, "DB_FILE"):
            monkeypatch.setattr(module, "DB_FILE", database_path)

    init_db = importlib.import_module("src.storage.init_db")
    migrations = importlib.import_module("src.storage.migrations")
    init_db.initialize_database()
    migrations.apply_migrations()

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            INSERT INTO niches (id, name, slug, created_at)
            VALUES (1, 'Test niche', 'test-niche', '2024-01-01T00:00:00+00:00');
            INSERT INTO keywords (id, text) VALUES (1, 'test keyword');
            INSERT INTO niche_keywords (niche_id, keyword_id) VALUES (1, 1);
            INSERT INTO search_runs
                (id, niche_id, keyword_id, run_timestamp, pages_scraped,
                 products_found, status, current_stage)
            VALUES
                (1, 1, 1, '2024-01-01T00:00:00+00:00', 1, 1, 'success', 'complete'),
                (2, 1, 1, '2024-02-01T00:00:00+00:00', 1, 0, 'success', 'complete'),
                (3, 1, 1, '2024-03-01T00:00:00+00:00', 1, 0, 'success', 'complete');
            INSERT INTO products
                (id, asin, title, brand, first_seen_at)
            VALUES (1, 'B012345678', 'Test product', 'Example brand',
                    '2024-01-01T00:00:00+00:00');
            INSERT INTO niche_products (niche_id, product_id, first_associated_at)
            VALUES (1, 1, '2024-01-01T00:00:00+00:00');
            INSERT INTO snapshots
                (id, product_id, search_run_id, parsed_at, price, currency,
                 rating, review_count, search_rank_position)
            VALUES
                (1, 1, 1, '2024-01-01T00:10:00+00:00', 12.5, 'INR',
                 4.2, 25, 1);
            """
        )

    return database_path
