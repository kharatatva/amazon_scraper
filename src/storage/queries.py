"""Read product, niche, run, history, and schedule data from SQLite."""

from datetime import datetime, timezone

from src.storage.db import create_search_run, get_connection


def create_running_search_run(niche_id: int, keyword_id: int) -> int:
    """Create the run record used by a backend-started pipeline."""
    run_id = create_search_run(niche_id, keyword_id)
    if run_id is None:
        raise RuntimeError("Could not create a search run.")
    return run_id


def upsert_scheduled_niche(
    niche_id: int,
    keyword_id: int,
    frequency: str,
    pages: int = 10,
    products: int = 100,
    run_times: str = "08:00,20:00",
    timezone_name: str = "Asia/Kolkata",
) -> int:
    """Create or reactivate a schedule for a niche and keyword."""
    if frequency not in {"daily", "weekly"}:
        raise ValueError("frequency must be 'daily' or 'weekly'.")
    if pages < 1 or products < 1:
        raise ValueError("pages and products must be positive integers.")
    slots = [slot.strip() for slot in run_times.split(",") if slot.strip()]
    if len(slots) != 2 or len(set(slots)) != 2:
        raise ValueError("run_times must contain two different local times.")
    for slot in slots:
        try:
            datetime.strptime(slot, "%H:%M")
        except ValueError as exc:
            raise ValueError("run_times must use HH:MM 24-hour times.") from exc
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        if timezone_name != "Asia/Kolkata":
            raise ValueError("timezone must be a valid IANA timezone.") from exc

    normalized_slots = ",".join(sorted(slots))

    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id FROM scheduled_niches
            WHERE niche_id = ? AND keyword_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (niche_id, keyword_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE scheduled_niches
                SET frequency = ?, is_active = 1, pages = ?, products = ?,
                    run_times = ?, timezone = ?, last_slot_key = NULL
                WHERE id = ?
                """,
                (frequency, pages, products, normalized_slots, timezone_name, existing[0]),
            )
            schedule_id = int(existing[0])
        else:
            cursor = conn.execute(
                """
                INSERT INTO scheduled_niches
                    (niche_id, keyword_id, frequency, is_active, pages, products,
                     run_times, timezone, created_at)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (niche_id, keyword_id, frequency, pages, products, normalized_slots,
                 timezone_name, datetime.now(timezone.utc).isoformat()),
            )
            schedule_id = int(cursor.lastrowid)
        conn.commit()
        return schedule_id
    finally:
        conn.close()


# ==================================================
# Niche Snapshot
# ==================================================

def get_niche_snapshot(niche_id, search_run_id):
    """
    Return all products associated with a niche that have a snapshot
    for the specified search run.

    Results are returned as plain dictionaries.

    Joins:
        niche_products
            -> products
            -> sellers
            -> snapshots

    Parameters
    ----------
    niche_id : int
        ID of the niche.

    search_run_id : int
        ID of the search run whose point-in-time data is requested.

    Returns
    -------
    list[dict]
        One dictionary per product snapshot.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                p.id AS product_id,
                p.asin,
                p.title,
                p.brand,

                s.id AS seller_id,
                s.name AS seller_name,

                p.fulfillment_type,
                p.category_path,
                p.product_url,
                p.thumbnail_url,
                p.first_seen_at,

                np.first_associated_at,

                sn.id AS snapshot_id,
                sn.search_run_id,
                sn.parsed_at,

                sn.price,
                sn.currency,
                sn.rating,
                sn.review_count,
                sn.bsr_data,

                sn.search_rank_position,

                sn.is_sponsored,
                sn.is_amazons_choice,
                sn.is_best_seller,

                sn.images_count,
                sn.bullet_points_count,
                sn.has_a_plus_content,

                sn.variant_count,
                sn.weight_and_dimensions

            FROM niche_products AS np

            INNER JOIN products AS p
                ON p.id = np.product_id

            LEFT JOIN sellers AS s
                ON s.id = p.seller_id

            INNER JOIN snapshots AS sn
                ON sn.product_id = p.id
                AND sn.search_run_id = ?

            WHERE np.niche_id = ?

            ORDER BY
                sn.search_rank_position ASC,
                p.id ASC
            """,
            (search_run_id, niche_id)
        )

        rows = cursor.fetchall()

        return [_row_to_dict(cursor, row) for row in rows]

    finally:
        conn.close()


# ==================================================
# Latest Run
# ==================================================

def get_latest_run_for_niche(niche_id):
    """
    Return the most recent search_run_id for a niche.

    Returns None if the niche has no search runs.

    Parameters
    ----------
    niche_id : int
        ID of the niche.

    Returns
    -------
    int | None
        Most recent search run ID.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id
            FROM search_runs
            WHERE niche_id = ?
            ORDER BY run_timestamp DESC, id DESC
            LIMIT 1
            """,
            (niche_id,)
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return int(row[0])

    finally:
        conn.close()


# ==================================================
# Product Detail
# ==================================================

def get_product_detail(product_id):
    """
    Return the complete known product information together with
    its most recent snapshot.

    The most recent snapshot is determined by:
        1. parsed_at DESC
        2. snapshot id DESC as a deterministic tie-breaker

    Parameters
    ----------
    product_id : int
        ID of the product.

    Returns
    -------
    dict | None
        Product information plus its most recent snapshot.

        Returns None if the product does not exist.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                p.id AS product_id,
                p.asin,
                p.title,
                p.brand,

                s.id AS seller_id,
                s.name AS seller_name,
                s.first_seen_at AS seller_first_seen_at,

                p.fulfillment_type,
                p.category_path,
                p.product_url,
                p.thumbnail_url,
                p.first_seen_at AS product_first_seen_at,

                sn.id AS snapshot_id,
                sn.search_run_id,
                sn.parsed_at,

                sn.price,
                sn.currency,
                sn.rating,
                sn.review_count,
                sn.bsr_data,

                sn.search_rank_position,

                sn.is_sponsored,
                sn.is_amazons_choice,
                sn.is_best_seller,

                sn.images_count,
                sn.bullet_points_count,
                sn.has_a_plus_content,

                sn.variant_count,
                sn.weight_and_dimensions

            FROM products AS p

            LEFT JOIN sellers AS s
                ON s.id = p.seller_id

            LEFT JOIN snapshots AS sn
                ON sn.id = (
                    SELECT sn2.id
                    FROM snapshots AS sn2
                    WHERE sn2.product_id = p.id
                    ORDER BY
                        sn2.parsed_at DESC,
                        sn2.id DESC
                    LIMIT 1
                )

            WHERE p.id = ?

            LIMIT 1
            """,
            (product_id,)
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return _row_to_dict(cursor, row)

    finally:
        conn.close()


# ==================================================
# Row Conversion
# ==================================================

def _row_to_dict(cursor, row):
    """
    Convert a sqlite3 cursor row into a plain dictionary.

    This deliberately does not return sqlite3.Row so callers
    remain independent of SQLite's row representation.
    """

    column_names = [description[0] for description in cursor.description]

    return dict(zip(column_names, row))


# ==================================================
# Historical / Time-Series Queries
# ==================================================

def get_price_history(product_id):
    """
    Return the product's price history across all snapshots.

    Results are ordered oldest first.

    Returns
    -------
    list[tuple[str, float | None]]
        [(parsed_at, price), ...]
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                parsed_at,
                price
            FROM snapshots
            WHERE product_id = ?
            ORDER BY parsed_at ASC, id ASC
            """,
            (product_id,)
        )

        return [
            (row[0], row[1])
            for row in cursor.fetchall()
        ]

    finally:
        conn.close()


def get_review_histories(product_ids, as_of=None):
    """Fetch review histories for many ASIN records with bounded SQL batches."""
    unique_ids = list(dict.fromkeys(int(product_id) for product_id in product_ids))
    histories = {product_id: [] for product_id in unique_ids}
    if not unique_ids:
        return histories

    conn = get_connection()
    try:
        cursor = conn.cursor()
        for offset in range(0, len(unique_ids), 500):
            batch = unique_ids[offset:offset + 500]
            placeholders = ",".join("?" for _ in batch)
            cutoff_clause = " AND julianday(parsed_at) <= julianday(?)" if as_of else ""
            params = [*batch, as_of] if as_of else batch
            cursor.execute(
                f"""
                SELECT product_id, parsed_at, review_count
                FROM snapshots
                WHERE product_id IN ({placeholders}){cutoff_clause}
                ORDER BY product_id, parsed_at ASC, id ASC
                """,
                params,
            )
            for product_id, parsed_at, review_count in cursor.fetchall():
                histories[product_id].append((parsed_at, review_count))
        return histories
    finally:
        conn.close()


def get_review_velocity(product_id, as_of=None):
    """
    Return the product's review-count history across all snapshots.

    Results are ordered oldest first.

    Returns
    -------
    list[tuple[str, int | None]]
        [(parsed_at, review_count), ...]
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cutoff_clause = " AND julianday(parsed_at) <= julianday(?)" if as_of else ""
        params = (product_id, as_of) if as_of else (product_id,)
        cursor.execute(
            f"""
            SELECT
                parsed_at,
                review_count
            FROM snapshots
            WHERE product_id = ?{cutoff_clause}
            ORDER BY parsed_at ASC, id ASC
            """,
            params
        )

        return [
            (row[0], row[1])
            for row in cursor.fetchall()
        ]

    finally:
        conn.close()


def get_rank_history(product_id, niche_id):
    """
    Return the product's search-rank history for a specific niche.

    The product is first restricted to the requested niche through
    niche_products, then its snapshots are matched to search runs
    belonging to that niche.

    Results are ordered oldest first.

    Returns
    -------
    list[tuple[str, int | None]]
        [(parsed_at, search_rank_position), ...]
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                sn.parsed_at,
                sn.search_rank_position
            FROM snapshots AS sn

            INNER JOIN search_runs AS sr
                ON sr.id = sn.search_run_id

            INNER JOIN niche_products AS np
                ON np.product_id = sn.product_id

            WHERE sn.product_id = ?
              AND sr.niche_id = ?
              AND np.niche_id = ?

            ORDER BY
                sn.parsed_at ASC,
                sn.id ASC
            """,
            (
                product_id,
                niche_id,
                niche_id,
            )
        )

        return [
            (row[0], row[1])
            for row in cursor.fetchall()
        ]

    finally:
        conn.close()
def list_niches():
    """
    Return every niche that has been scraped.

    Returns:
        list[dict]: Niche ID, name, and last scraped timestamp.
    """
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                name,
                last_scraped_at
            FROM niches
            ORDER BY last_scraped_at DESC, id DESC
            """
        )

        rows = cursor.fetchall()

        return [
            _row_to_dict(cursor, row)
            for row in rows
        ]

    finally:
        conn.close()
def list_runs_for_niche(niche_id):
    """
    Return every search run belonging to a niche.

    Newest runs are returned first.

    Returns:
        list[dict]: Run ID, timestamp, status, and products found.
    """
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                run_timestamp,
                status,
                products_found
            FROM search_runs
            WHERE niche_id = ?
            ORDER BY run_timestamp DESC, id DESC
            """,
            (niche_id,),
        )

        rows = cursor.fetchall()

        return [
            _row_to_dict(cursor, row)
            for row in rows
        ]

    finally:
        conn.close()


def get_ranked_opportunities(niche_id, search_run_id):
    """
    Return all products observed in a specific niche/run,
    together with their opportunity scores.

    Scored products are ranked by final_score descending.
    Products without scores remain in the result and appear
    after scored products because SQLite sorts NULL lower
    than numeric values in DESC ordering.
    """
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                p.id AS product_id,
                p.asin,
                p.title,
                p.brand,
                s.name AS seller_name,
                p.fulfillment_type,
                sn.id AS snapshot_id,
                sn.price,
                sn.currency,
                sn.rating,
                sn.review_count,
                sn.search_rank_position,
                sn.images_count,
                sn.bullet_points_count,
                sn.has_a_plus_content,
                os.demand_score,
                os.competition_score,
                os.quality_gap_score,
                os.final_score
            FROM niche_products AS np
            JOIN products AS p
                ON np.product_id = p.id
            LEFT JOIN sellers AS s
                ON p.seller_id = s.id
            JOIN snapshots AS sn
                ON sn.product_id = p.id
                AND sn.search_run_id = ?
            LEFT JOIN opportunity_scores AS os
                ON os.snapshot_id = sn.id
            WHERE np.niche_id = ?
            ORDER BY os.final_score DESC
            """,
            (search_run_id, niche_id),
        )

        rows = cursor.fetchall()

        return [
            _row_to_dict(cursor, row)
            for row in rows
        ]

    finally:
        conn.close()
