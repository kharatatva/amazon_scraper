"""Parse saved search and product HTML for completed search runs."""

import sys
import json
from pathlib import Path

from src.config import RENDERED_HTML_DIR
from src.logger import logger

from src.parser.search_result_parser import (
    parse_search_results_page,
)

from src.parser.product_detail_parser import (
    parse_product_detail_page,
)

from src.storage.db import (
    get_search_run_context,
    upsert_product,
    upsert_niche_product,
    upsert_snapshot,
    normalize_text,
    log_scrape_error,
)


# =========================================================
# RUN ID VALIDATION
# =========================================================

def parse_run_id(value: str) -> int:
    """
    Convert the command-line run ID into a positive integer.
    """

    try:
        run_id = int(value)

    except ValueError as exc:

        raise ValueError(
            f"Invalid search_run_id: {value!r}. "
            "It must be an integer."
        ) from exc

    if run_id <= 0:

        raise ValueError(
            "search_run_id must be greater than 0."
        )

    return run_id


# =========================================================
# SEARCH HTML FILE DISCOVERY
# =========================================================

def get_search_html_files(
    search_run_id: int,
    niche_name: str,
    keyword: str,
) -> list[Path]:
    """
    Find all saved search-result HTML files for a search run.

    Expected structure:

        data/rendered_html/{niche}/{keyword}/
            {run_id}_page1.html
            {run_id}_page2.html
            ...
    """

    niche_dir_name = (
        normalize_text(niche_name)
        .replace(" ", "-")
    )

    keyword_dir_name = (
        normalize_text(keyword)
        .replace(" ", "-")
    )

    search_dir = (
        RENDERED_HTML_DIR
        / niche_dir_name
        / keyword_dir_name
    )

    if not search_dir.exists():

        raise FileNotFoundError(
            f"Search HTML directory does not exist: "
            f"{search_dir}"
        )

    files = list(
        search_dir.glob(
            f"{search_run_id}_page*.html"
        )
    )

    def page_number(path: Path) -> int:
        """
        Extract page number from:

            {run_id}_pageN.html
        """

        stem = path.stem

        prefix = f"{search_run_id}_page"

        if not stem.startswith(prefix):
            return -1

        try:

            return int(
                stem[len(prefix):]
            )

        except ValueError:

            return -1

    files = [
        path
        for path in files
        if page_number(path) >= 1
    ]

    files.sort(
        key=page_number
    )

    return files


# =========================================================
# PRODUCT DETAIL FILE
# =========================================================

def get_product_detail_file(
    search_run_id: int,
    keywords: str,
    niche_slug: str,
    asin: str,
) -> Path:
    """
    Return the expected saved product-detail HTML path.

    Actual structure created by product_detail.py:

        data/rendered_html/
            {niche_slug}/
                {keyword}/
                    products/
                        {run_id}_{asin}.html
    """

    return (
        RENDERED_HTML_DIR
        / niche_slug
        / keywords
        / "products"
        / f"{search_run_id}_{asin}.html"
    )


# =========================================================
# PHASE A INGESTION
# =========================================================

def ingest_phase_a_product(
    product: dict,
    niche_id: int,
    search_run_id: int,
) -> int:
    """
    Ingest one product that has a corresponding
    product-detail HTML file.

    Phase A writes:

        products
        niche_products
        snapshots

    Returns:

        product_id
    """

    asin = product.get("asin")

    if not asin:

        raise ValueError(
            "Cannot ingest product without ASIN."
        )

    # ---------------------------------------------------------
    # PRODUCT TABLE
    # ---------------------------------------------------------

    product_id = upsert_product(

        asin=asin,

        title=product.get(
            "title"
        ),

        product_url=product.get(
            "product_url"
        ),

        thumbnail_url=product.get(
            "thumbnail_url"
        ),
    )

    # ---------------------------------------------------------
    # NICHE-PRODUCT RELATIONSHIP
    # ---------------------------------------------------------

    upsert_niche_product(

        niche_id=niche_id,

        product_id=product_id,
    )

    # ---------------------------------------------------------
    # PHASE A SNAPSHOT
    # ---------------------------------------------------------

    upsert_snapshot(

        product_id=product_id,

        search_run_id=search_run_id,

        price=product.get(
            "price"
        ),

        currency="INR",

        rating=product.get(
            "rating"
        ),

        review_count=product.get(
            "review_count"
        ),

        search_rank_position=product.get(
            "search_rank_position"
        ),

        is_sponsored=product.get(
            "is_sponsored"
        ),

        is_amazons_choice=product.get(
            "is_amazons_choice"
        ),

        is_best_seller=product.get(
            "is_best_seller"
        ),
    )

    return product_id


# =========================================================
# PHASE B ENRICHMENT
# =========================================================

def enrich_with_detail(
    product_id: int,
    search_run_id: int,
    detail_data: dict,
) -> None:
    """
    Enrich an existing Phase-A product and snapshot
    using parsed product-detail data.
    """

    # ---------------------------------------------------------
    # PRODUCT-LEVEL DETAIL DATA
    # ---------------------------------------------------------

    upsert_product(

        asin=detail_data["asin"],

        brand=detail_data.get(
            "brand"
        ),

        seller_name=detail_data.get(
            "seller_name"
        ),

        fulfillment_type=detail_data.get(
            "fulfillment_type"
        ),

        category_path=detail_data.get(
            "category_path"
        ),
    )

    # ---------------------------------------------------------
    # BSR
    # ---------------------------------------------------------

    bsr_data = detail_data.get(
        "bsr_data"
    )

    if bsr_data is not None:

        try:

            bsr_data = json.dumps(
                bsr_data,
                ensure_ascii=False,
            )

        except (TypeError, ValueError):

            logger.exception(
                f"Failed to serialize BSR data "
                f"for ASIN={detail_data['asin']}"
            )

            raise

    # ---------------------------------------------------------
    # WEIGHT / DIMENSIONS
    # ---------------------------------------------------------

    weight_and_dimensions = detail_data.get(
        "weight_and_dimensions"
    )

    if weight_and_dimensions is not None:

        try:

            weight_and_dimensions = json.dumps(
                weight_and_dimensions,
                ensure_ascii=False,
            )

        except (TypeError, ValueError):

            logger.exception(
                f"Failed to serialize weight/dimensions "
                f"for ASIN={detail_data['asin']}"
            )

            raise

    # ---------------------------------------------------------
    # VARIANT COUNT
    # ---------------------------------------------------------

    variant_count = detail_data.get(
        "variant_count"
    )

    if variant_count is not None:

        try:

            variant_count = int(
                variant_count
            )

        except (TypeError, ValueError):

            logger.exception(
                f"Invalid variant_count for "
                f"ASIN={detail_data['asin']} | "
                f"value={variant_count!r}"
            )

            raise

    # ---------------------------------------------------------
    # SNAPSHOT-LEVEL DETAIL DATA
    # ---------------------------------------------------------

    upsert_snapshot(

        product_id=product_id,

        search_run_id=search_run_id,

        bsr_data=bsr_data,

        images_count=detail_data.get(
            "images_count"
        ),

        bullet_points_count=detail_data.get(
            "bullet_points_count"
        ),

        has_a_plus_content=detail_data.get(
            "has_a_plus_content"
        ),

        variant_count=variant_count,

        weight_and_dimensions=weight_and_dimensions,
    )


# =========================================================
# MAIN PARSER ORCHESTRATOR
# =========================================================

def run_parser(
    search_run_id: int,
) -> dict:
    """
    Orchestrate Phase A and Phase B ingestion.

    IMPORTANT:

    Only products with an existing product-detail HTML
    file are inserted into the database.

    Search-result products without corresponding detail
    HTML are skipped completely.

    The parser does NOT finalize search_runs.status.
    The top-level pipeline owns the overall run status.
    """

    logger.info(
        f"Starting parser orchestration | "
        f"search_run_id={search_run_id}"
    )

    # =========================================================
    # 1. GET SEARCH RUN CONTEXT
    # =========================================================

    context = get_search_run_context(
        search_run_id
    )

    if not context:

        raise ValueError(
            f"No search-run context found for "
            f"search_run_id={search_run_id}"
        )

    niche_id = context["niche_id"]
    keyword_id = context["keyword_id"]
    niche_name = context["niche_name"]
    niche_slug = context["niche_slug"]
    keyword = context["keyword"]

    logger.info(
        f"Search run context loaded | "
        f"run_id={search_run_id} | "
        f"niche_id={niche_id} | "
        f"keyword_id={keyword_id} | "
        f"niche_name={niche_name} | "
        f"niche_slug={niche_slug} | "
        f"keyword={keyword}"
    )

    # =========================================================
    # 2. LOCATE SEARCH HTML
    # =========================================================

    search_files = get_search_html_files(

        search_run_id=search_run_id,

        niche_name=niche_name,

        keyword=keyword,
    )

    if not search_files:

        raise FileNotFoundError(
            f"No search-result HTML files found for "
            f"search_run_id={search_run_id}, "
            f"niche_name='{niche_name}', "
            f"keyword='{keyword}'"
        )

    # =========================================================
    # 3. PHASE A + DETAIL FILE VALIDATION
    # =========================================================

    product_ids_by_asin: dict[str, int] = {}

    ingested_asins: set[str] = set()

    pages_parsed = 0

    phase_a_errors: list[str] = []

    products_without_detail: list[str] = []

    # ---------------------------------------------------------
    # Process every search-result HTML file
    # ---------------------------------------------------------

    for html_file in search_files:

        logger.debug(
            f"Parsing search-result file: "
            f"{html_file.name}"
        )

        try:

            with html_file.open(
                "r",
                encoding="utf-8",
            ) as file:

                html = file.read()

            products = parse_search_results_page(
                html
            )

            pages_parsed += 1

            logger.debug(
                f"Parsed {len(products)} products from "
                f"{html_file.name}"
            )

            # -------------------------------------------------
            # Process every product
            # -------------------------------------------------

            for product in products:

                asin = product.get(
                    "asin"
                )

                if not asin:

                    logger.warning(
                        f"Skipping product without ASIN "
                        f"in {html_file.name}"
                    )

                    continue

                # -------------------------------------------------
                # Cross-page deduplication
                # -------------------------------------------------

                if asin in ingested_asins:

                    logger.debug(
                        f"Skipping duplicate ASIN={asin} "
                        f"from {html_file.name}"
                    )

                    continue

                # =================================================
                # Check for product-detail HTML BEFORE DB INSERT
                # =================================================

                detail_file = get_product_detail_file(

                    search_run_id=search_run_id,

                    keywords=normalize_text(
                        keyword
                    ).replace(
                        " ",
                        "-"
                    ),

                    niche_slug=normalize_text(
                        niche_slug
                    ).replace(
                        " ",
                        "-"
                    ),

                    asin=asin,
                )

                if not detail_file.exists():

                    products_without_detail.append(
                        asin
                    )

                    logger.debug(
                        f"Skipping ASIN={asin} | "
                        f"No product-detail HTML found at "
                        f"{detail_file}"
                    )

                    continue

                # -------------------------------------------------
                # Only products with detail HTML reach the DB.
                # -------------------------------------------------

                try:

                    product_id = ingest_phase_a_product(

                        product=product,

                        niche_id=niche_id,

                        search_run_id=search_run_id,
                    )

                    product_ids_by_asin[
                        asin
                    ] = product_id

                    ingested_asins.add(
                        asin
                    )

                    logger.debug(
                        f"Phase A ingestion successful | "
                        f"ASIN={asin} | "
                        f"product_id={product_id} | "
                        f"detail_file={detail_file.name}"
                    )

                except Exception:

                    error_message = (
                        f"Phase A failed for "
                        f"ASIN={asin} "
                        f"in {html_file.name}"
                    )

                    phase_a_errors.append(
                        error_message
                    )

                    logger.exception(
                        error_message
                    )

        except Exception:

            error_message = (
                f"Failed to parse search HTML file "
                f"{html_file}"
            )

            phase_a_errors.append(
                error_message
            )

            logger.exception(
                error_message
            )

    logger.info(
        f"Phase A completed | "
        f"pages_parsed={pages_parsed} | "
        f"products_with_detail="
        f"{len(ingested_asins)} | "
        f"products_without_detail="
        f"{len(products_without_detail)}"
    )

    # =========================================================
    # 4. PHASE B
    # =========================================================

    detail_files_found = 0

    detail_products_enriched = 0

    phase_b_errors: list[str] = []

    # ---------------------------------------------------------
    # Every product here should have a detail file.
    # ---------------------------------------------------------

    for asin, product_id in product_ids_by_asin.items():

        detail_file = get_product_detail_file(

            search_run_id=search_run_id,

            keywords=normalize_text(
                keyword
            ).replace(
                " ",
                "-"
            ),

            niche_slug=normalize_text(
                niche_slug
            ).replace(
                " ",
                "-"
            ),

            asin=asin,
        )

        # -----------------------------------------------------
        # Safety check
        # -----------------------------------------------------

        if not detail_file.exists():

            logger.error(
                f"INTERNAL CONSISTENCY ERROR | "
                f"ASIN={asin} was ingested but its "
                f"detail file no longer exists: "
                f"{detail_file}"
            )

            phase_b_errors.append(
                f"Detail file disappeared for ASIN={asin}"
            )

            continue

        detail_files_found += 1

        logger.debug(
            f"Parsing detail HTML for ASIN={asin}: "
            f"{detail_file.name}"
        )

        try:

            with detail_file.open(
                "r",
                encoding="utf-8",
            ) as file:

                html = file.read()

            detail_data = parse_product_detail_page(
                html
            )

            if not isinstance(
                detail_data,
                dict,
            ):

                raise TypeError(
                    f"Product detail parser returned "
                    f"{type(detail_data).__name__} "
                    f"instead of dict for ASIN={asin}"
                )

            # -------------------------------------------------
            # Keep the authoritative ASIN from the search result.
            # -------------------------------------------------

            detail_data["asin"] = asin

            enrich_with_detail(

                product_id=product_id,

                search_run_id=search_run_id,

                detail_data=detail_data,
            )

            detail_products_enriched += 1

            logger.debug(
                f"Phase B enrichment successful | "
                f"ASIN={asin} | "
                f"product_id={product_id}"
            )

        except Exception as e:

            error_message = (
                f"Phase B failed for "
                f"ASIN={asin}: "
                f"{e}"
            )

            phase_b_errors.append(
                error_message
            )

            logger.exception(
                error_message
            )

            try:

                log_scrape_error(

                    search_run_id=search_run_id,

                    url=str(detail_file),

                    error_type="phase_b_parse_error",

                    error_message=error_message,
                )

                logger.info(
                    f"Phase B error logged to scrape_errors | "
                    f"ASIN={asin}"
                )

            except Exception as log_error:

                logger.exception(
                    f"Failed to log Phase B error to "
                    f"scrape_errors | "
                    f"ASIN={asin} | "
                    f"error={log_error}"
                )

    logger.info(
        f"Phase B completed | "
        f"detail_files_found={detail_files_found} | "
        f"products_enriched={detail_products_enriched}"
    )

    # =========================================================
    # 5. BUILD PARSER SUMMARY
    # =========================================================

    products_found = len(
        ingested_asins
    )

    all_errors = (
        phase_a_errors
        + phase_b_errors
    )

    if pages_parsed == 0:

        parser_status = "failed"

    elif all_errors:

        parser_status = "partial"

    else:

        parser_status = "success"

    notes_parts = [

        f"Parsed search pages: "
        f"{pages_parsed}/{len(search_files)}",

        f"Products with detail HTML: "
        f"{products_found}",

        f"Products skipped without detail HTML: "
        f"{len(products_without_detail)}",

        f"Detail files found: "
        f"{detail_files_found}",

        f"Products enriched: "
        f"{detail_products_enriched}",
    ]

    if all_errors:

        notes_parts.append(
            f"Errors: {len(all_errors)}"
        )

    notes = " | ".join(
        notes_parts
    )

    logger.info(
        f"Parser orchestration completed | "
        f"search_run_id={search_run_id} | "
        f"status={parser_status} | "
        f"products_found={products_found}"
    )

    # =========================================================
    # IMPORTANT:
    #
    # Do NOT update search_runs here.
    #
    # run_pipeline.py is the authoritative owner of the
    # complete search-run lifecycle.
    # =========================================================

    return {
        "search_run_id": search_run_id,
        "status": parser_status,
        "pages_parsed": pages_parsed,
        "pages_found": len(search_files),
        "products_found": products_found,
        "products_without_detail": len(
            products_without_detail
        ),
        "detail_files_found": detail_files_found,
        "products_enriched": detail_products_enriched,
        "errors": len(all_errors),
        "notes": notes,
    }


# =========================================================
# CLI
# =========================================================

def main() -> None:
    """
    Standalone CLI entry point.

    Usage:

        python scripts/run_parser.py <search_run_id>
    """

    if len(sys.argv) != 2:

        print(
            "Usage: python scripts/run_parser.py "
            "<search_run_id>"
        )

        raise SystemExit(1)

    try:

        search_run_id = parse_run_id(
            sys.argv[1]
        )

        result = run_parser(
            search_run_id
        )

        logger.info(
            f"Standalone parser completed | "
            f"result={result}"
        )

    except Exception:

        logger.exception(
            "Parser orchestration failed."
        )

        raise SystemExit(1)


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
