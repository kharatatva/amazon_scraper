"""Compute and store opportunity scores for completed search runs."""

import sys
from pathlib import Path


# ============================================================
# PROJECT PATH
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# IMPORTS
# ============================================================

from src.storage.db import (
    get_connection,
    upsert_opportunity_score,
    
)

from src.storage.queries import (
    get_niche_snapshot,
)

from src.analysis.scoring import (
    compute_demand_scores,
    compute_competition_scores,
    compute_quality_gap_score,
    compute_final_score,
)

from src.config import SCORE_WEIGHTS
from src.logger import logger


# ============================================================
# GET NICHE ID FROM SEARCH RUN
# ============================================================

def get_niche_id_for_run(
    search_run_id: int,
) -> int:
    """
    Return the niche_id associated with a search_run_id.
    """

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT niche_id
            FROM search_runs
            WHERE id = ?
            """,
            (search_run_id,),
        )

        row = cursor.fetchone()

        if row is None:

            raise ValueError(
                f"Search run {search_run_id} does not exist."
            )

        return int(row[0])

    finally:

        conn.close()


# ============================================================
# RUN SCORING
# ============================================================

def run_scoring(
    search_run_id: int,
) -> list[dict]:
    """
    Run the complete opportunity-scoring pipeline for one
    search run.

    Pipeline:

        search_run_id
            ↓
        niche_id
            ↓
        niche snapshot
            ↓
        competition score
            ↓
        demand + quality gap per product
            ↓
        final opportunity score
            ↓
        persist to opportunity_scores

    Returns:
        list[dict]: Products ranked by final opportunity score.
    """

    from src.storage.demand_schema import ensure_demand_schema
    ensure_demand_schema()

    logger.info(
        "=" * 70
    )

    logger.info(
        "OPPORTUNITY SCORING"
    )

    logger.info(
        f"Search Run: {search_run_id}"
    )

    # --------------------------------------------------------
    # 1. Get niche associated with this search run
    # --------------------------------------------------------

    niche_id = get_niche_id_for_run(
        search_run_id
    )

    logger.info(
        f"Niche ID: {niche_id}"
    )

    # --------------------------------------------------------
    # 2. Get all products from this run in one shot
    # --------------------------------------------------------

    niche_snapshot = get_niche_snapshot(
        niche_id=niche_id,
        search_run_id=search_run_id,
    )

    if not niche_snapshot:

        raise ValueError(
            f"No product snapshots found for "
            f"search_run_id={search_run_id}."
        )

    logger.info(
        f"Products available for scoring: "
        f"{len(niche_snapshot)}"
    )

    # --------------------------------------------------------
    # 3. Competition is calculated ONCE for the whole niche
    # --------------------------------------------------------

    competition_scores = compute_competition_scores(
        niche_snapshot
    )

    # Competition is niche-level, so every product gets
    # the same competition score.

    competition_score = next(
        iter(competition_scores.values())
    )

    # Calculate review velocity once for the run instead of querying every
    # product's full history once per target product.
    demand_scores = compute_demand_scores(niche_snapshot)

    logger.info(
        f"Competition score calculated: "
        f"{competition_score:.2f}"
    )

    # --------------------------------------------------------
    # 4. Score every product
    # --------------------------------------------------------

    ranked_results = []

    for product in niche_snapshot:

        product_id = product["product_id"]

        snapshot_id = product["snapshot_id"]

        # ----------------------------------------------------
        # Demand
        # ----------------------------------------------------

        demand_score = demand_scores.get(product_id)

        # ----------------------------------------------------
        # Quality Gap
        # ----------------------------------------------------

        quality_gap_score = compute_quality_gap_score(
            product_id=product_id,
            niche_snapshot=niche_snapshot,
        )

        # ----------------------------------------------------
        # Final Opportunity Score
        # ----------------------------------------------------

        final_score = compute_final_score(
            demand=demand_score,
            competition=competition_score,
            quality_gap=quality_gap_score,
            weights=SCORE_WEIGHTS,
        )

        # ----------------------------------------------------
        # Persist
        # ----------------------------------------------------

        upsert_opportunity_score(
            snapshot_id=snapshot_id,
            demand_score=demand_score,
            competition_score=competition_score,
            quality_gap_score=quality_gap_score,
            final_score=final_score,
        )

        # ----------------------------------------------------
        # Keep result for ranking
        # ----------------------------------------------------

        ranked_results.append(
            {
                "product_id": product_id,
                "snapshot_id": snapshot_id,
                "asin": product["asin"],
                "title": product["title"],
                "demand_score": demand_score,
                "competition_score": competition_score,
                "quality_gap_score": quality_gap_score,
                "final_score": final_score,
            }
        )

    # --------------------------------------------------------
    # 5. Rank by final score
    # --------------------------------------------------------

    ranked_results.sort(
        key=lambda product: product["final_score"],
        reverse=True,
    )

    # --------------------------------------------------------
    # 6. Log top 10
    # --------------------------------------------------------

    logger.info(
        "=" * 70
    )

    logger.info(
        "TOP 10 OPPORTUNITY SCORES"
    )

    logger.info(
        "=" * 70
    )

    for rank, product in enumerate(
        ranked_results[:10],
        start=1,
    ):

        demand_display = (
            f"{product['demand_score']:.2f}"
            if product["demand_score"] is not None
            else "None"
        )

        quality_gap_display = (
            f"{product['quality_gap_score']:.2f}"
            if product["quality_gap_score"] is not None
            else "None"
        )

        logger.debug(
            f"#{rank} | "
            f"Product ID: {product['product_id']} | "
            f"ASIN: {product['asin']} | "
            f"Demand: {demand_display} | "
            f"Competition: "
            f"{product['competition_score']:.2f} | "
            f"Quality Gap: {quality_gap_display} | "
            f"Final: {product['final_score']:.2f} | "
            f"Title: {product['title']}"
        )

    logger.info(
        "=" * 70
    )

    logger.info(
        f"SCORING COMPLETE — "
        f"{len(ranked_results)} products scored."
    )

    logger.info(
        "=" * 70
    )

    return ranked_results


# ============================================================
# CLI ENTRY POINT
# ============================================================

def main() -> None:
    """
    Standalone CLI entry point.

    Usage:

        python scripts/run_scoring.py
    """

    try:

        search_run_id = int(
            input(
                "Enter search_run_id: "
            ).strip()
        )

    except ValueError:

        logger.error(
            "search_run_id must be an integer."
        )

        raise SystemExit(1)

    try:

        run_scoring(
            search_run_id
        )

    except Exception:

        logger.exception(
            "Scoring pipeline failed."
        )

        raise SystemExit(1)


# ============================================================
# SCRIPT ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
