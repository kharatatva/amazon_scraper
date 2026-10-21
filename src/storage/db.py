"""Write scraper runs, products, snapshots, and errors to SQLite."""

# src/storage/db.py
import sqlite3
import json
from datetime import datetime, timezone
from src.logger import logger
from src.config import DB_FILE


def get_connection():
    """Open a SQLite connection to the configured application database."""
    return sqlite3.connect(DB_FILE)



def log_scrape_error(
    search_run_id: int,
    url: str = None,
    error_type: str = None,
    error_message: str = None,
    attempt_number: int = 1,
) -> None:
    """Append a scrape error for a search run."""
    conn = get_connection()

    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO scrape_errors
                (search_run_id, url, error_type, error_message, attempt_number, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                search_run_id,
                url,
                error_type,
                error_message,
                attempt_number,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    except Exception:
        logger.exception(
            f"Failed to record scrape error for run ID: "
            f"{search_run_id}"
        )
        raise

    finally:
        conn.close()



def create_search_run(niche_id: int, keyword_id: int) -> int:
    """
    Creates a new search_runs record.

    Returns:
        ID of the created search run.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO search_runs
            (
                niche_id,
                keyword_id,
                run_timestamp,
                pages_scraped,
                products_found,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                niche_id,
                keyword_id,
                datetime.now(timezone.utc).isoformat(),
                0,
                0,
                "running",
            ),
        )

        conn.commit()

        search_run_id = cursor.lastrowid

        logger.info(f"Created search run with ID: {search_run_id}")

        return search_run_id

    except Exception as e:
        logger.error(f"Failed to create search run: {e}")
        return None

    finally:
        conn.close()

    # def get_or_create_keyword(keyword: str) -> int:
    #     """
    #     Returns the existing keyword_id if the keyword already exists.
    #     Creates the keyword if it does not exist.
    #     """

    #     conn = get_connection()

    #     try:
    #         cursor = conn.cursor()

    #         keyword = keyword.strip().lower()

    #         cursor.execute(
    #             """
    #             SELECT id
    #             FROM keywords
    #             WHERE text = ?
    #             """,
    #             (keyword,)
    #         )

    #         row = cursor.fetchone()

    #         if row:
    #             return row[0]

    #         cursor.execute(
    #             """
    #             INSERT INTO keywords (text)
    #             VALUES (?)
    #             """,
    #             (keyword,)
    #         )

    #         conn.commit()

    #         keyword_id = cursor.lastrowid

    #         logger.info(
    #             f"Created keyword '{keyword}' with ID: {keyword_id}"
    #         )

    #         return keyword_id

    #     except Exception:
    #         logger.exception(
    #             f"Failed to get/create keyword: {keyword}"
    #         )
    #         raise

    #     finally:
    #         conn.close()



def update_search_run(
    search_run_id: int,
    pages_scraped: int = None,
    products_found: int = None,
    status: str = None,
    notes: str = None,
    current_stage: str = None,
    current_task: str = None,
    config_json: dict = None,
) -> None:
    """
    Update an existing search_runs record.

    Updates only the fields provided, leaving all other
    fields unchanged.

    config_json stores a snapshot of the run configuration.
    """

    import json

    conn = get_connection()

    try:
        fields = []
        values = []

        if pages_scraped is not None:
            fields.append("pages_scraped = ?")
            values.append(pages_scraped)

        if products_found is not None:
            fields.append("products_found = ?")
            values.append(products_found)

        if status is not None:
            fields.append("status = ?")
            values.append(status)

        if notes is not None:
            fields.append("notes = ?")
            values.append(notes)

        if current_stage is not None:
            fields.append("current_stage = ?")
            values.append(current_stage)

        if current_task is not None:
            fields.append("current_task = ?")
            values.append(current_task)

        if config_json is not None:
            fields.append("config_json = ?")
            values.append(
                json.dumps(
                    config_json,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

        if not fields:
            return

        values.append(search_run_id)

        cursor = conn.execute(
            f"""
            UPDATE search_runs
            SET {", ".join(fields)}
            WHERE id = ?
            """,
            values,
        )

        if cursor.rowcount == 0:
            raise ValueError(
                f"Search run {search_run_id} does not exist."
            )

        conn.commit()

        logger.debug(
            f"Updated search run ID: {search_run_id}"
        )

    except Exception:
        conn.rollback()

        logger.exception(
            f"Failed to update search run ID: {search_run_id}"
        )

        raise

    finally:
        conn.close()





import re


def normalize_text(text: str) -> str:
    """
    Normalize text for database comparisons.
    """

    if not isinstance(text, str):
        raise TypeError("Text must be a string.")

    text = text.strip().lower()

    # Replace punctuation with spaces
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Collapse repeated whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def get_or_create_niche(niche_name: str) -> int:
    """
    Return the niche_id for a niche, creating it if it does not exist.

    This function expects a canonical niche name, not a search keyword.

    Example:
        "speakers" -> niche
        "headphones" -> niche

    Search keywords such as:
        "bluetooth speakers"
        "wireless speakers"

    should be stored in the keywords table and linked to the
    appropriate niche through niche_keywords.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        # ---------------------------------------------------------
        # Normalize and validate niche name
        # ---------------------------------------------------------

        niche_name = normalize_text(niche_name)

        if not niche_name:
            raise ValueError("Niche name cannot be empty.")

        # ---------------------------------------------------------
        # Check whether niche already exists
        # ---------------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM niches
            WHERE name = ?
            """,
            (niche_name,),
        )

        row = cursor.fetchone()

        if row is not None:
            niche_id = row[0]

            logger.info(
                f"Existing niche found: '{niche_name}' "
                f"(ID: {niche_id})"
            )

            return niche_id

        # ---------------------------------------------------------
        # Create new niche
        # ---------------------------------------------------------

        slug = re.sub(r"\s+", "-", niche_name)

        cursor.execute(
            """
            INSERT INTO niches (
                name,
                slug,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                niche_name,
                slug,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        conn.commit()

        niche_id = cursor.lastrowid

        logger.info(
            f"Created new niche '{niche_name}' "
            f"with ID: {niche_id}"
        )

        return niche_id

    except Exception:
        logger.exception(
            f"Failed to get/create niche: {niche_name}"
        )
        raise

    finally:
        conn.close()


def get_or_create_keyword(keyword: str) -> int:
    """
    Get an existing keyword_id or create a new keyword.

    This stores the EXACT search keyword.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        keyword = normalize_text(keyword)

        if not keyword:
            raise ValueError("Keyword cannot be empty.")

        # ---------------------------------------------------------
        # Check existing keyword
        # ---------------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM keywords
            WHERE text = ?
            """,
            (keyword,),
        )

        row = cursor.fetchone()

        if row is not None:
            keyword_id = row[0]

            logger.info(f"Existing keyword found: '{keyword}' " f"(ID: {keyword_id})")

            return keyword_id

        # ---------------------------------------------------------
        # Create keyword
        # ---------------------------------------------------------

        cursor.execute(
            """
            INSERT INTO keywords
            (
                text
            )
            VALUES (?)
            """,
            (keyword,),
        )

        conn.commit()

        keyword_id = cursor.lastrowid

        logger.info(f"Created keyword '{keyword}' " f"with ID: {keyword_id}")

        return keyword_id

    except Exception:
        logger.exception(f"Failed to get/create keyword: {keyword}")
        raise

    finally:
        conn.close()


def link_niche_keyword(niche_id: int, keyword_id: int) -> None:
    """
    Link an existing niche to an existing keyword.

    Duplicate relationships are ignored.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR IGNORE INTO niche_keywords
            (
                niche_id,
                keyword_id
            )
            VALUES (?, ?)
            """,
            (niche_id, keyword_id),
        )

        conn.commit()

        logger.info(f"Linked niche_id={niche_id} " f"to keyword_id={keyword_id}")

    except Exception:
        logger.exception(
            f"Failed to link niche {niche_id} " f"with keyword {keyword_id}"
        )
        raise

    finally:
        conn.close()


def get_niches_for_keyword(keyword_id: int) -> list[int]:
    """
    Return all niche IDs associated with a keyword.

    Returns an empty list if no niche relationship exists.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT niche_id
            FROM niche_keywords
            WHERE keyword_id = ?
            """,
            (keyword_id,),
        )

        rows = cursor.fetchall()

        return [row[0] for row in rows]

    except Exception:
        logger.exception(
            f"Failed to find niches for keyword_id={keyword_id}"
        )
        raise

    finally:
        conn.close()

def get_or_create_seller(name: str) -> int:
    """
    Returns the existing seller_id if the seller exists.
    Otherwise creates the seller and returns its ID.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        name = name.strip()

        if not name:
            raise ValueError("Seller name cannot be empty.")

        # Check whether seller already exists
        cursor.execute(
            """
            SELECT id
            FROM sellers
            WHERE name = ?
            """,
            (name,),
        )

        row = cursor.fetchone()

        if row is not None:
            return row[0]

        # Seller does not exist -> create it
        cursor.execute(
            """
            INSERT INTO sellers
            (
                name,
                first_seen_at
            )
            VALUES (?, ?)
            """,
            (name, datetime.now(timezone.utc).isoformat()),
        )

        conn.commit()

        seller_id = cursor.lastrowid

        logger.info(f"Created seller '{name}' with ID: {seller_id}")

        return seller_id

    except Exception:
        logger.exception(f"Failed to get/create seller: {name}")
        raise

    finally:
        conn.close()


def upsert_product(asin: str, **fields) -> int:
    """
    Insert a new product or update an existing product by ASIN.

    Seller name, when supplied, is resolved to seller_id.

    Returns:
        product_id
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        asin = asin.strip()

        if not asin:
            raise ValueError("ASIN cannot be empty.")

        # ---------------------------------------------------------
        # Resolve seller name -> seller_id
        # ---------------------------------------------------------

        seller_id = fields.get("seller_id")

        seller_name = fields.get("seller_name")

        if seller_name:
            seller_id = get_or_create_seller(seller_name)

        # ---------------------------------------------------------
        # Prepare values
        # ---------------------------------------------------------

        title = fields.get("title")
        brand = fields.get("brand")
        fulfillment_type = fields.get("fulfillment_type")
        category_path = fields.get("category_path")
        product_url = fields.get("product_url")
        thumbnail_url = fields.get("thumbnail_url")

        first_seen_at = fields.get(
            "first_seen_at", datetime.now(timezone.utc).isoformat()
        )

        # ---------------------------------------------------------
        # Upsert product
        # ---------------------------------------------------------

        cursor.execute(
            """
            INSERT INTO products
            (
                asin,
                title,
                brand,
                seller_id,
                fulfillment_type,
                category_path,
                product_url,
                thumbnail_url,
                first_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(asin) DO UPDATE SET
                title = COALESCE(
                    excluded.title,
                    products.title
                ),
                brand = COALESCE(excluded.brand, products.brand),
                seller_id = COALESCE(
                    excluded.seller_id,
                    products.seller_id
                ),
                fulfillment_type = COALESCE(
                    excluded.fulfillment_type,
                    products.fulfillment_type
                ),
                category_path = COALESCE(
                    excluded.category_path,
                    products.category_path
                ),
                 product_url = COALESCE(
                    excluded.product_url,
                    products.product_url
                ),
                thumbnail_url = COALESCE(
                    excluded.thumbnail_url,
                    products.thumbnail_url
                )
            """,
            (
                asin,
                title,
                brand,
                seller_id,
                fulfillment_type,
                category_path,
                product_url,
                thumbnail_url,
                first_seen_at,
            ),
        )

        conn.commit()

        # ---------------------------------------------------------
        # Get product ID
        # ---------------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM products
            WHERE asin = ?
            """,
            (asin,),
        )

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(f"Product was upserted but could not be found: {asin}")

        product_id = row[0]

        logger.debug(f"Upserted product ASIN={asin}, ID={product_id}")

        return product_id

    except Exception:
        logger.exception(f"Failed to upsert product with ASIN={asin}")
        raise

    finally:
        conn.close()


def upsert_niche_product(niche_id: int, product_id: int) -> None:
    """
    Associates a product with a niche.

    The UNIQUE(niche_id, product_id) constraint prevents
    duplicate associations, so repeated calls are safe.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR IGNORE INTO niche_products
            (
                niche_id,
                product_id,
                first_associated_at
            )
            VALUES (?, ?, ?)
            """,
            (niche_id, product_id, datetime.now(timezone.utc).isoformat()),
        )

        conn.commit()

        logger.debug(f"Associated product_id={product_id} " f"with niche_id={niche_id}")

    except Exception:
        logger.exception(
            f"Failed to associate product_id={product_id} " f"with niche_id={niche_id}"
        )
        raise

    finally:
        conn.close()

def upsert_snapshot(
    product_id: int,
    search_run_id: int,
    **fields
) -> int:
    """
    Insert or update a snapshot for a product within a search run.

    Phase A:
        Inserts search-result data.

    Phase B:
        Calls this function again with the same
        product_id + search_run_id and enriches the
        existing snapshot.

    Returns:
        snapshot_id
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        # ---------------------------------------------------------
        # Prepare fields
        # ---------------------------------------------------------

        parsed_at = fields.get(
            "parsed_at",
            datetime.now(timezone.utc).isoformat()
        )

        price = fields.get("price")
        currency = fields.get("currency", "INR")
        rating = fields.get("rating")
        review_count = fields.get("review_count")

        bsr_data = fields.get("bsr_data")

        search_rank_position = fields.get(
            "search_rank_position"
        )

        is_sponsored = fields.get(
            "is_sponsored"
        )

        is_amazons_choice = fields.get(
            "is_amazons_choice"
        )

        is_best_seller = fields.get(
            "is_best_seller"
        )

        images_count = fields.get(
            "images_count"
        )

        bullet_points_count = fields.get(
            "bullet_points_count"
        )

        has_a_plus_content = fields.get(
            "has_a_plus_content"
        )

        # ---------------------------------------------------------
        # Detail-page fields
        # ---------------------------------------------------------

        variant_count = fields.get(
            "variant_count"
        )

        weight_and_dimensions = fields.get(
            "weight_and_dimensions"
        )

        # ---------------------------------------------------------
        # Insert / update snapshot
        # ---------------------------------------------------------

        cursor.execute(
            """
            INSERT INTO snapshots
            (
                product_id,
                search_run_id,
                parsed_at,
                price,
                currency,
                rating,
                review_count,
                bsr_data,
                search_rank_position,
                is_sponsored,
                is_amazons_choice,
                is_best_seller,
                images_count,
                bullet_points_count,
                has_a_plus_content,
                variant_count,
                weight_and_dimensions
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(product_id, search_run_id)
            DO UPDATE SET

                parsed_at = excluded.parsed_at,

                price = COALESCE(
                    excluded.price,
                    snapshots.price
                ),

                currency = COALESCE(
                    excluded.currency,
                    snapshots.currency
                ),

                rating = COALESCE(
                    excluded.rating,
                    snapshots.rating
                ),

                review_count = COALESCE(
                    excluded.review_count,
                    snapshots.review_count
                ),

                bsr_data = COALESCE(
                    excluded.bsr_data,
                    snapshots.bsr_data
                ),

                search_rank_position = COALESCE(
                    excluded.search_rank_position,
                    snapshots.search_rank_position
                ),

                is_sponsored = COALESCE(
                    excluded.is_sponsored,
                    snapshots.is_sponsored
                ),

                is_amazons_choice = COALESCE(
                    excluded.is_amazons_choice,
                    snapshots.is_amazons_choice
                ),

                is_best_seller = COALESCE(
                    excluded.is_best_seller,
                    snapshots.is_best_seller
                ),

                images_count = COALESCE(
                    excluded.images_count,
                    snapshots.images_count
                ),

                bullet_points_count = COALESCE(
                    excluded.bullet_points_count,
                    snapshots.bullet_points_count
                ),

                has_a_plus_content = COALESCE(
                    excluded.has_a_plus_content,
                    snapshots.has_a_plus_content
                ),

                variant_count = COALESCE(
                    excluded.variant_count,
                    snapshots.variant_count
                ),

                weight_and_dimensions = COALESCE(
                    excluded.weight_and_dimensions,
                    snapshots.weight_and_dimensions
                )
            """,
            (
                product_id,
                search_run_id,
                parsed_at,
                price,
                currency,
                rating,
                review_count,
                bsr_data,
                search_rank_position,
                is_sponsored,
                is_amazons_choice,
                is_best_seller,
                images_count,
                bullet_points_count,
                has_a_plus_content,
                variant_count,
                weight_and_dimensions
            )
        )

        conn.commit()

        # ---------------------------------------------------------
        # Retrieve snapshot ID
        # ---------------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM snapshots
            WHERE product_id = ?
              AND search_run_id = ?
            """,
            (
                product_id,
                search_run_id
            )
        )

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Snapshot was upserted but could not be found: "
                f"product_id={product_id}, "
                f"search_run_id={search_run_id}"
            )

        snapshot_id = row[0]

        logger.info(
            f"Upserted snapshot_id={snapshot_id} "
            f"for product_id={product_id}, "
            f"search_run_id={search_run_id}"
        )

        return snapshot_id

    except Exception:
        logger.exception(
            "Failed to upsert snapshot for "
            f"product_id={product_id}, "
            f"search_run_id={search_run_id}"
        )
        raise

    finally:
        conn.close()    






#         conn.close()
def get_search_run_context(search_run_id: int) -> dict:
    """
    Return the niche and keyword context for a search run.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                sr.niche_id,
                sr.keyword_id,
                n.name,
                n.slug,
                k.text
            FROM search_runs AS sr
            JOIN niches AS n
                ON n.id = sr.niche_id
            JOIN keywords AS k
                ON k.id = sr.keyword_id
            WHERE sr.id = ?
            """,
            (search_run_id,),
        )

        row = cursor.fetchone()

        if row is None:
            raise ValueError(
                f"Search run {search_run_id} does not exist."
            )

        (
            niche_id,
            keyword_id,
            niche_name,
            niche_slug,
            keyword,
        ) = row

        return {
            "niche_id": niche_id,
            "niche_name": niche_name,
            "keyword_id": keyword_id,
            "keyword": keyword,
            "niche_slug": niche_slug,
        }

    except Exception:
        logger.exception(
            f"Failed to get context for search_run_id={search_run_id}"
        )
        raise

    finally:
        conn.close()
def upsert_opportunity_score(
    snapshot_id: int,
    demand_score,
    competition_score,
    quality_gap_score,
    final_score,
) -> int:
    """
    Insert or update the opportunity score for a snapshot.

    There must be only one opportunity_scores row per snapshot_id.

    Returns:
        opportunity_scores row ID.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO opportunity_scores
            (
                snapshot_id,
                demand_score,
                competition_score,
                quality_gap_score,
                final_score,
                computed_at,
                demand_score_version
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)

            ON CONFLICT(snapshot_id)
            DO UPDATE SET
                demand_score = excluded.demand_score,
                competition_score = excluded.competition_score,
                quality_gap_score = excluded.quality_gap_score,
                final_score = excluded.final_score,
                computed_at = excluded.computed_at,
                demand_score_version = excluded.demand_score_version
            """,
            (
                snapshot_id,
                demand_score,
                competition_score,
                quality_gap_score,
                final_score,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        conn.commit()

        cursor.execute(
            """
            SELECT id
            FROM opportunity_scores
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        )

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Opportunity score was upserted but could not be found: "
                f"snapshot_id={snapshot_id}"
            )

        opportunity_score_id = row[0]

        logger.info(
            f"Upserted opportunity score for "
            f"snapshot_id={snapshot_id}, "
            f"id={opportunity_score_id}"
        )

        return opportunity_score_id

    except Exception:
        logger.exception(
            "Failed to upsert opportunity score "
            f"for snapshot_id={snapshot_id}"
        )
        raise

    finally:
        conn.close()
        
