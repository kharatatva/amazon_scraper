"""Orchestrate search scraping, product scraping, parsing, storage, and scoring."""

import asyncio
import argparse
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

from src.config import MAX_PAGES_TO_CRAWL
from src.logger import configure_logging, log_context, logger

from src.scraper.search_page_scraper import (
    create_search_run_for_pipeline,
    fetch_search_results,
)

from src.scraper.product_page_scraper import (
    fetch_product_url_from_search_results,
    fetch_product_detail,
)

from src.scraper.proxies import ProxyManager

from src.scraper.fetch import (
    CaptchaDetectedError,
)

from scripts.run_parser import run_parser
from scripts.run_scoring import run_scoring

from src.storage.db import (
    get_search_run_context,
    log_scrape_error,
    update_search_run,
)


# ============================================================
# PIPELINE STAGES
# ============================================================

STAGE_SEARCH = "search"
STAGE_PRODUCT_DETAIL = "product_detail"
STAGE_PARSING = "parsing"
STAGE_SCORING = "scoring"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"


# ============================================================
# STAGE UPDATE
# ============================================================

def update_stage(
    run_id: int,
    stage: str,
) -> None:
    """
    Update the current stage of a search run.
    """

    logger.info(
        f"[PIPELINE] run_id={run_id} "
        f"current_stage={stage}"
    )

    update_search_run(
        search_run_id=run_id,
        current_stage=stage,
    )


# ============================================================
# INPUT NORMALIZATION
# ============================================================

def normalize_pipeline_input(
    niche_name: str,
    keyword: str,
    num_pages: int,
) -> tuple[str, str, int]:
    """
    Normalize and validate pipeline inputs.
    """

    niche_name = (
        niche_name
        .strip()
        .lower()
        .replace(" ", "-")
    )

    keyword = (
        keyword
        .strip()
        .lower()
        .replace(" ", "-")
    )

    if not niche_name:

        raise ValueError(
            "Niche name cannot be empty."
        )

    if not keyword:

        raise ValueError(
            "Keyword cannot be empty."
        )

    if num_pages < 1:

        raise ValueError(
            "num_pages must be greater than 0."
        )

    if num_pages > MAX_PAGES_TO_CRAWL:

        logger.info(
            f"Requested pages ({num_pages}) exceed "
            f"MAX_PAGES_TO_CRAWL ({MAX_PAGES_TO_CRAWL}). "
            f"Limiting to {MAX_PAGES_TO_CRAWL} pages."
        )

        num_pages = MAX_PAGES_TO_CRAWL

    return (
        niche_name,
        keyword,
        num_pages,
    )


# ============================================================
# PROXY SELECTION
# ============================================================

def get_initial_proxy(
    proxy_manager: ProxyManager,
) -> str:
    """
    Select the proxy that will be used for the initial
    search stage.

    This proxy is passed to both search.py and
    product_detail.py.
    """

    logger.info(
        "[PIPELINE] Selecting initial proxy..."
    )

    proxy = proxy_manager.get_next_proxy()

    if proxy is None:

        raise RuntimeError(
            "No proxy is available for the pipeline."
        )

    logger.info("[PIPELINE] Initial proxy selected.")

    return proxy


# ============================================================
# SEARCH STAGE
# ============================================================

async def run_search_stage(
    niche_name: str,
    keyword: str,
    num_pages: int,
    proxy: str,
    proxy_manager: ProxyManager = None,
    run_id: int = None,
) -> int:
    """
    Run the search stage using the supplied proxy.

    The proxy is fixed for the entire search stage.
    """

    logger.info(
        "=" * 70
    )

    logger.info(
        "[PIPELINE] STARTING SEARCH STAGE"
    )

    logger.info("[PIPELINE] Search proxy selected.")

    logger.info(
        "=" * 70
    )

    search_run_id = await fetch_search_results(
        niche_name=niche_name,
        keyword=keyword,
        num_pages=num_pages,
        proxy=proxy,
        run_id=run_id,
        proxy_manager=proxy_manager,
    )

    if not search_run_id:

        raise RuntimeError(
            "Search scraper did not return a valid "
            "search_run_id."
        )

    logger.info(
        f"[PIPELINE] Search stage completed | "
        f"run_id={search_run_id}"
    )

    return search_run_id


# ============================================================
# PRODUCT DETAIL STAGE
# ============================================================

async def run_product_detail_stage(
    search_run_id: int,
    niche_name: str,
    keyword: str,
    product_urls: list[str],
    asins: list[str],
    proxy: str,
    proxy_manager: ProxyManager = None,
) -> int:
    """
    Run the product-detail stage with one shared active proxy.
    BrowserLifecycle coordinates a replacement only after a confirmed
    proxy transport failure.

    Returns:
        Number of successfully scraped products.
    """

    logger.info(
        "=" * 70
    )

    logger.info(
        "[PIPELINE] STARTING PRODUCT DETAIL STAGE"
    )

    logger.info(
        f"[PIPELINE] run_id={search_run_id}"
    )

    logger.info("[PIPELINE] Product proxy selected.")

    logger.info(
        f"[PIPELINE] Products to scrape: "
        f"{len(asins)}"
    )

    logger.info(
        "=" * 70
    )

    products_scraped = await fetch_product_detail(
        asin=asins,
        product_url=product_urls,
        niche_slug=niche_name,
        keyword=keyword,
        run_id=search_run_id,
        proxy=proxy,
        proxy_manager=proxy_manager,
    )

    logger.info(
        f"[PIPELINE] Product-detail stage finished | "
        f"run_id={search_run_id} | "
        f"products_scraped={products_scraped}/"
        f"{len(asins)}"
    )

    return products_scraped


# ============================================================
# SCRAPING PIPELINE
# ============================================================

async def run_scraping_pipeline(
    niche_name: str,
    keyword: str,
    num_pages: int,
    proxy_manager: ProxyManager,
    run_id: int = None,
    max_products: int = None,
) -> int:
    """
    Run:

        SEARCH
          ↓
        PRODUCT URL EXTRACTION
          ↓
        PRODUCT DETAIL

    Each scraping stage owns one shared browser and active proxy. Proxy
    recovery happens inside that stage; exhausted recovery propagates to the
    pipeline so the run is recorded as failed.
    """

    # --------------------------------------------------------
    # 1. Select initial proxy
    # --------------------------------------------------------

    if not proxy_manager.pool_initialized:
        await proxy_manager.ensure_initial_proxy()

    proxy = get_initial_proxy(
        proxy_manager
    )

    # --------------------------------------------------------
    # 2. Search stage
    # --------------------------------------------------------
    logger.info(
    "[PIPELINE] Starting search stage."
    )
    # update_stage(
    #     # run_id does not exist yet, so stage cannot be
    #     # written to DB before create_search_run().
    #     #
    #     # The search scraper itself creates the run.
    #     #
    #     # Therefore this log is intentionally handled
    #     # through logging until the run_id exists.
    #     run_id=0,
    #     stage=STAGE_SEARCH,
    # )

    with log_context(run_id=run_id, stage=STAGE_SEARCH):
        search_run_id = await run_search_stage(
            niche_name=niche_name,
            keyword=keyword,
            num_pages=num_pages,
            proxy=proxy,
            proxy_manager=proxy_manager,
            run_id=run_id,
        )

    # Search recovery may have advanced the shared manager to a validated
    # replacement. Carry that active proxy into the product-detail stage.
    proxy = proxy_manager.get_current_proxy()
    if proxy is None:
        raise RuntimeError("Search stage completed without an active validated proxy.")

    # --------------------------------------------------------
    # 3. Product-detail stage
    # --------------------------------------------------------

    update_stage(
        search_run_id,
        STAGE_PRODUCT_DETAIL,
    )

    # --------------------------------------------------------
    # 4. Extract product URLs once before the product-detail stage.
    # --------------------------------------------------------

    logger.info(
        f"[PIPELINE] Extracting product URLs | "
        f"run_id={search_run_id}"
    )

    product_urls, asins = (
        await fetch_product_url_from_search_results(
            run_id=search_run_id,
            niche_slug=niche_name,
            keyword_slug=keyword,
            max_products=max_products,
        )
    )

    logger.info(
        f"[PIPELINE] Product extraction complete | "
        f"run_id={search_run_id} | "
        f"products={len(asins)}"
    )

    if not asins:

        raise RuntimeError(
            f"No products were extracted for "
            f"search_run_id={search_run_id}."
        )

    # --------------------------------------------------------
    # 5. Product-detail stage
    # --------------------------------------------------------

    logger.info("[PIPELINE] Starting product-detail stage.")
    with log_context(run_id=search_run_id, stage=STAGE_PRODUCT_DETAIL):
        products_scraped = await run_product_detail_stage(
            search_run_id=search_run_id,
            niche_name=niche_name,
            keyword=keyword,
            product_urls=product_urls,
            asins=asins,
            proxy=proxy,
            proxy_manager=proxy_manager,
        )

    if products_scraped <= 0:
        raise RuntimeError("Product-detail stage completely failed.")

    logger.info(
        "[PIPELINE] Product stage accepted | %s/%s products scraped.",
        products_scraped,
        len(asins),
    )

    return search_run_id


# ============================================================
# COMPLETE PIPELINE
# ============================================================

async def run_pipeline(
    niche_name: str,
    keyword: str,
    num_pages: int,
    run_id: int = None,
    max_products: int = None,
) -> int:
    """
    Execute the complete Amazon niche-analysis pipeline.

    Pipeline:

        SEARCH
          ↓
        PRODUCT DETAIL
          ↓
        PARSING
          ↓
        SCORING
          ↓
        COMPLETED

    Confirmed proxy failures are recovered inside the
    shared browser lifecycle. Exhausted recovery marks
    the search run failed and stops the pipeline.
    """

    search_run_id = run_id
    configure_logging()

    try:
        if search_run_id is None:
            niche_name, keyword, num_pages = normalize_pipeline_input(
                niche_name=niche_name,
                keyword=keyword,
                num_pages=num_pages,
            )
            search_run_id = create_search_run_for_pipeline(niche_name, keyword)

        with log_context(run_id=search_run_id, stage="pipeline"):
            return await _run_pipeline(
                niche_name, keyword, num_pages, search_run_id, max_products
            )

    except Exception as exc:
        with log_context(run_id=search_run_id, stage="pipeline"):
            logger.exception("[PIPELINE] Fatal pipeline failure: %s", exc)

        if search_run_id is not None:
            try:
                with log_context(run_id=search_run_id, stage="pipeline"):
                    log_scrape_error(
                        search_run_id=search_run_id,
                        url="PIPELINE",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
            except Exception:
                logger.exception("[PIPELINE] Failed to record scrape error | run_id=%s", search_run_id)
            try:
                update_search_run(
                    search_run_id=search_run_id,
                    status="failed",
                    current_stage=STAGE_FAILED,
                    current_task="Pipeline failed",
                    notes=str(exc),
                )
            except Exception:
                logger.exception("[PIPELINE] Failed to update failed stage | run_id=%s", search_run_id)
        raise


async def _run_pipeline(
    niche_name: str,
    keyword: str,
    num_pages: int,
    run_id: int,
    max_products: int,
) -> int:
    search_run_id = run_id
    proxy_manager = None

    try:

        logger.info(
            "=" * 70
        )

        logger.info(
            "STARTING COMPLETE AMAZON PIPELINE"
        )

        logger.info(
            "=" * 70
        )

        # ----------------------------------------------------
        # INPUT NORMALIZATION
        # ----------------------------------------------------

        (
            niche_name,
            keyword,
            num_pages,
        ) = normalize_pipeline_input(
            niche_name=niche_name,
            keyword=keyword,
            num_pages=num_pages,
        )

        logger.info(
            f"[PIPELINE] Normalized input | "
            f"niche={niche_name} | "
            f"keyword={keyword} | "
            f"pages={num_pages}"
        )

        # ----------------------------------------------------
        # PROXY MANAGER
        # ----------------------------------------------------

        proxy_manager = ProxyManager()

        logger.info(
            "[PIPELINE] Proxy Manager initialized."
        )

        # ----------------------------------------------------
        # SEARCH + PRODUCT DETAIL
        # ----------------------------------------------------

        search_run_id = (
            await run_scraping_pipeline(
                niche_name=niche_name,
                keyword=keyword,
                num_pages=num_pages,
                proxy_manager=proxy_manager,
                run_id=run_id,
                max_products=max_products,
            )
        )
        await proxy_manager.close()

        # ----------------------------------------------------
        # PARSING
        # ----------------------------------------------------

        update_stage(
            search_run_id,
            STAGE_PARSING,
        )

        logger.info(
            f"[PIPELINE] Starting parser | "
            f"run_id={search_run_id}"
        )

        with log_context(run_id=search_run_id, stage=STAGE_PARSING):
            parser_result = run_parser(search_run_id)

        logger.info(
            f"[PIPELINE] Parsing complete | "
            f"run_id={search_run_id} | "
            f"status={parser_result.get('status')} | "
            f"products_found="
            f"{parser_result.get('products_found', 0)} | "
            f"products_enriched="
            f"{parser_result.get('products_enriched', 0)} | "
            f"errors={parser_result.get('errors', 0)}"
        )

        if parser_result.get(
            "products_found",
            0,
        ) == 0:

            raise RuntimeError(
                f"Parser produced no usable products "
                f"for search_run_id={search_run_id}."
            )

        # ----------------------------------------------------
        # SCORING
        # ----------------------------------------------------

        update_stage(
            search_run_id,
            STAGE_SCORING,
        )

        logger.info(
            f"[PIPELINE] Starting scoring | "
            f"run_id={search_run_id}"
        )

        with log_context(run_id=search_run_id, stage=STAGE_SCORING):
            scoring_result = run_scoring(search_run_id)

        logger.info(
            f"[PIPELINE] Scoring complete | "
            f"run_id={search_run_id} | "
            f"products_scored="
            f"{len(scoring_result)}"
        )

        if not scoring_result:

            raise RuntimeError(
                f"Scoring produced no results "
                f"for search_run_id={search_run_id}."
            )

        # ----------------------------------------------------
        # COMPLETED
        # ----------------------------------------------------

        update_stage(
            search_run_id,
            STAGE_COMPLETED,
        )

        logger.info(
            "=" * 70
        )

        logger.info(
            f"PIPELINE COMPLETED SUCCESSFULLY | "
            f"run_id={search_run_id}"
        )

        logger.info(
            "=" * 70
        )

        return search_run_id

    except Exception:
        raise
    finally:
        if proxy_manager is not None:
            await proxy_manager.close()


# ============================================================
# CLI
# ============================================================

def main() -> None:
    """Standalone and backend subprocess entry point."""
    parser = argparse.ArgumentParser(description="Run the niche analysis pipeline.")
    parser.add_argument("--run-id", type=int, help="Reuse an existing search run.")
    parser.add_argument("--pages", type=int, help="Number of search pages to scrape.")
    parser.add_argument("--products", type=int, help="Maximum products to detail scrape.")
    parser.add_argument("--niche", help="Niche name.")
    parser.add_argument("--keyword", help="Search keyword.")
    args = parser.parse_args()

    try:
        if args.run_id is not None:
            if args.pages is None:
                parser.error("--pages is required with --run-id.")
            context = get_search_run_context(args.run_id)
            niche_name = context["niche_slug"]
            keyword = context["keyword"]
            pages = args.pages
        elif args.niche and args.keyword and args.pages is not None:
            niche_name, keyword, pages = args.niche, args.keyword, args.pages
        else:
            print("=" * 70)
            print("AMAZON NICHE FINDER")
            print("=" * 70)
            niche_name = input("Enter niche: ").strip()
            keyword = input("Enter keyword: ").strip()
            pages = int(input("Enter number of pages to scrape: ").strip())

        asyncio.run(run_pipeline(
            niche_name=niche_name,
            keyword=keyword,
            num_pages=pages,
            run_id=args.run_id,
            max_products=args.products,
        ))
    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user.")
        raise SystemExit(1)
    except Exception:
        logger.exception("Pipeline execution failed.")
        raise SystemExit(1)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
