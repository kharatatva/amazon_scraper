"""Check that the configured SQLite database has the expected schema."""

import sqlite3
import sys

from src.config import DB_FILE


# ==================================================
# Expected Schema
# ==================================================

EXPECTED_TABLES = {
    "niches": [
        "id",
        "name",
        "slug",
        "created_at",
        "last_scraped_at",
    ],

    "keywords": [
        "id",
        "text",
    ],

    "sellers": [
        "id",
        "name",
        "first_seen_at",
    ],

    "search_runs": [
        "id",
        "niche_id",
        "keyword_id",
        "run_timestamp",
        "pages_scraped",
        "products_found",
        "status",
        "cuurent_stage"
        "notes",
        'config_json'
    ],

    "products": [
        "id",
        "asin",
        "title",
        "brand",
        "seller_id",
        "fulfillment_type",
        "category_path",
        "product_url",
        "thumbnail_url",
        "first_seen_at",
    ],

    "niche_products": [
        "id",
        "niche_id",
        "product_id",
        "first_associated_at",
    ],

    "snapshots": [
        "id",
        "product_id",
        "search_run_id",
        "parsed_at",
        "price",
        "currency",
        "rating",
        "review_count",
        "bsr_data",
        "search_rank_position",
        "is_sponsored",
        "is_amazons_choice",
        "is_best_seller",
        "images_count",
        "bullet_points_count",
        "has_a_plus_content",
        "variant_count",
        "weight_and_dimensions",
        
    ],

    "opportunity_scores": [
        "id",
        "snapshot_id",
        "demand_score",
        "competition_score",
        "quality_gap_score",
        "final_score",
        "computed_at",
    ],

    "scrape_errors": [
        "id",
        "search_run_id",
        "url",
        "error_type",
        "error_message",
        "attempt_number",
        "occurred_at",
    ],

    "niche_keywords": [
        "niche_id",
        "keyword_id",
    ],
}


EXPECTED_INDEXES = {
    "snapshots": [
        "idx_snapshots_product",
        "idx_snapshots_run",
    ],

    "niche_products": [
        "idx_niche_products_niche",
    ],
}


# ==================================================
# Verification Helpers
# ==================================================

def get_table_columns(cursor, table_name):
    """
    Return the column names reported by SQLite PRAGMA table_info().
    """

    rows = cursor.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def get_table_indexes(cursor, table_name):
    """
    Return the index names reported by SQLite PRAGMA index_list().
    """

    rows = cursor.execute(
        f"PRAGMA index_list({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def verify_tables(cursor):
    """
    Verify that every expected table exists and contains
    every expected column.
    """

    passed = True

    print("=" * 60)
    print("TABLE VERIFICATION")
    print("=" * 60)

    for table_name, expected_columns in EXPECTED_TABLES.items():

        actual_columns = get_table_columns(cursor, table_name)

        if not actual_columns:
            print(f"[FAIL] Table missing: {table_name}")
            passed = False
            continue

        missing_columns = [
            column
            for column in expected_columns
            if column not in actual_columns
        ]

        if missing_columns:
            print(f"[FAIL] Table: {table_name}")

            for column in missing_columns:
                print(f"       Missing column: {column}")

            passed = False

        else:
            print(
                f"[PASS] Table: {table_name} "
                f"({len(expected_columns)} columns verified)"
            )

    return passed


def verify_indexes(cursor):
    """
    Verify that every required explicit index exists.

    The UNIQUE(product_id, search_run_id) constraint on snapshots
    is intentionally not checked as idx_snapshots_product_run because
    SQLite creates an automatic unique index for that constraint.
    """

    passed = True

    print()
    print("=" * 60)
    print("INDEX VERIFICATION")
    print("=" * 60)

    for table_name, expected_indexes in EXPECTED_INDEXES.items():

        actual_indexes = get_table_indexes(cursor, table_name)

        for index_name in expected_indexes:

            if index_name in actual_indexes:
                print(
                    f"[PASS] Index: {index_name} "
                    f"(table: {table_name})"
                )
            else:
                print(
                    f"[FAIL] Index missing: {index_name} "
                    f"(table: {table_name})"
                )
                passed = False

    return passed


def verify_snapshot_unique_constraint(cursor):
    """
    Verify that snapshots enforces uniqueness on
    (product_id, search_run_id).

    This is implemented by the UNIQUE constraint in schema.sql,
    not by a separately named idx_snapshots_product_run index.
    """

    print()
    print("=" * 60)
    print("SNAPSHOT UNIQUENESS VERIFICATION")
    print("=" * 60)

    rows = cursor.execute(
        "PRAGMA index_list(snapshots)"
    ).fetchall()

    for row in rows:
        index_name = row[1]
        is_unique = row[2]

        if not is_unique:
            continue

        index_columns = cursor.execute(
            f"PRAGMA index_info({index_name})"
        ).fetchall()

        columns = [column[2] for column in index_columns]

        if columns == ["product_id", "search_run_id"]:
            print(
                "[PASS] snapshots UNIQUE(product_id, search_run_id)"
            )
            return True

    print(
        "[FAIL] snapshots UNIQUE(product_id, search_run_id) "
        "constraint not found"
    )

    return False


# ==================================================
# Main Verification
# ==================================================

def verify_schema():
    """
    Verify the live database against the expected project schema.
    """

    print("=" * 60)
    print("DATABASE SCHEMA VERIFICATION")
    print("=" * 60)
    print(f"Database: {DB_FILE}")
    print()

    if not DB_FILE.exists():
        print(f"[FAIL] Database does not exist: {DB_FILE}")
        return False

    conn = None

    try:
        conn = sqlite3.connect(DB_FILE)

        # Enable foreign-key enforcement for this connection.
        conn.execute("PRAGMA foreign_keys = ON")

        cursor = conn.cursor()

        tables_passed = verify_tables(cursor)
        indexes_passed = verify_indexes(cursor)
        uniqueness_passed = verify_snapshot_unique_constraint(cursor)

        overall_passed = (
            tables_passed
            and indexes_passed
            and uniqueness_passed
        )

        print()
        print("=" * 60)

        if overall_passed:
            print("SCHEMA VERIFICATION: PASS")
            print("=" * 60)
            print("All expected tables and columns are present.")
            print("All required indexes are present.")
            print(
                "The snapshots product/run uniqueness constraint "
                "is present."
            )

        else:
            print("SCHEMA VERIFICATION: FAIL")
            print("=" * 60)
            print("One or more schema requirements are missing.")

        return overall_passed

    except sqlite3.Error as exc:
        print()
        print("=" * 60)
        print("SCHEMA VERIFICATION: FAIL")
        print("=" * 60)
        print(f"SQLite error: {exc}")

        return False

    finally:
        if conn is not None:
            conn.close()


# ==================================================
# Script Entry Point
# ==================================================

if __name__ == "__main__":
    success = verify_schema()

    sys.exit(0 if success else 1)