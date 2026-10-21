"""Collect product-page details for products found in a search run."""

import asyncio

from playwright_stealth import Stealth
from playwright.async_api import async_playwright

from src.config import (
    RENDERED_HTML_DIR,
    PRODUCT_PAGE_CONCURRENCY,
    MAX_DETAIL_PAGES_PER_RUN,
    MAX_RETRIES,
    PROXY_RECOVERY_ATTEMPTS,
)

from src.logger import logger

from src.parser.search_result_parser import (
    parse_search_results_page,
)
import asyncio

from playwright_stealth import Stealth
from playwright.async_api import async_playwright

from src.config import (
    RENDERED_HTML_DIR,
    PRODUCT_PAGE_CONCURRENCY,
    MAX_DETAIL_PAGES_PER_RUN,
    MAX_RETRIES,
    PROXY_RECOVERY_ATTEMPTS,
)

from src.logger import logger

from src.parser.search_result_parser import (
    parse_search_results_page,
)

from src.scraper.fetch import (
    fetch_page,
    CaptchaDetectedError,
    ProxyFailureError,
    FetchSupersededError,
)

from src.scraper.proxies import ProxyManager
from src.scraper.browser import (
    BrowserContextCreationError,
    BrowserLifecycle,
    BrowserRecoveryError,
    requires_browser_recovery,
)


async def fetch_product_url_from_search_results(
    run_id: int,
    niche_slug: str,
    keyword_slug: str,
    max_products: int = None,
):

    """Read saved search pages and collect unique product URLs and ASINs."""
    try:

        search_html_dir = (
            RENDERED_HTML_DIR
            / niche_slug
            / keyword_slug
        )

        html_files = sorted(
            search_html_dir.glob(
                f"{run_id}_page*.html"
            ),
            key=lambda path: int(
                path.stem.split("_page")[-1]
            ),
        )

        items_url_list = []
        items_asin_list = []
        items_ranked_list = []

        for html_file_path in html_files:

            with open(
                html_file_path,
                "r",
                encoding="utf-8",
            ) as f:

                html_content = f.read()

            search_results = (
                parse_search_results_page(
                    html_content
                )
            )

            for item in search_results:

                items_url_list.append(
                    item["product_url"]
                )

                items_asin_list.append(
                    item["asin"]
                )

                items_ranked_list.append(
                    item["search_rank_position"]
                )

        combined_items = list(
            zip(
                items_ranked_list,
                items_asin_list,
                items_url_list,
            )
        )

        parsed_count = len(combined_items)

        seen_asins = set()
        unique_items = []

        for item in combined_items:

            asin = item[1]

            if asin not in seen_asins:

                seen_asins.add(asin)

                unique_items.append(
                    item
                )

        combined_items = unique_items

        unique_count = len(combined_items)

        combined_items.sort(
            key=lambda item: item[0]
        )

        product_limit = MAX_DETAIL_PAGES_PER_RUN
        if max_products is not None:
            if max_products < 1:
                raise ValueError("max_products must be at least 1.")
            product_limit = min(product_limit, max_products)
        combined_items = combined_items[:product_limit]

        items_ranked_list = [
            item[0]
            for item in combined_items
        ]

        items_asin_list = [
            item[1]
            for item in combined_items
        ]

        items_url_list = [
            item[2]
            for item in combined_items
        ]

        logger.info(
            f"Collected {len(items_ranked_list)} "
            f"products for detail scraping "
            f"(parsed={parsed_count}, unique={unique_count}). "
            f"Top rank: "
            f"{items_ranked_list[0] if items_ranked_list else 'N/A'} | "
            f"Max allowed: "
            f"{product_limit}"
        )

        return (
            items_url_list,
            items_asin_list,
        )

    except Exception:

        logger.exception(
            f"Failed while extracting product URLs "
            f"for run_id={run_id}, "
            f"niche='{niche_slug}'"
        )

        raise


async def fetch_product_detail(
    asin: list[str],
    product_url: list[str],
    niche_slug: str,
    keyword: str,
    run_id: int,
    proxy: str = None,
    proxy_manager: ProxyManager = None,
):
    """
    Scrape product-detail pages using one fixed proxy
    for the entire product-detail stage.

    A single browser lifecycle shares the active proxy across all product
    workers and coordinates failure-driven recovery with the proxy manager.

    Returns:
        int:
            Number of successfully scraped products.
    """

    # zip() silently creates no tasks when either input is empty, and
    # truncates to the shorter list when their lengths differ. Validate
    # the work items before starting a proxy/browser session.
    if not asin or not product_url:
        raise ValueError(
            "Product-detail stage received no work: "
            f"{len(asin or [])} ASIN(s), {len(product_url or [])} URL(s). "
            "Check that the search stage saved product results and that "
            "they were parsed successfully."
        )

    if len(asin) != len(product_url):
        raise ValueError(
            "Product-detail input mismatch: "
            f"{len(asin)} ASIN(s) but {len(product_url)} URL(s)."
        )

    invalid_indexes = [
        index
        for index, (asin_value, url) in enumerate(zip(asin, product_url))
        if not isinstance(asin_value, str)
        or not asin_value.strip()
        or not isinstance(url, str)
        or not url.strip()
    ]
    if invalid_indexes:
        raise ValueError(
            "Product-detail input contains an empty ASIN or URL at "
            f"item index/indices: {invalid_indexes[:10]}"
        )

    logger.info("[DETAIL] Starting product fetch | run_id=%s | products=%s", run_id, len(asin))

    niche_slug = (
        niche_slug
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

    product_dir = (
        RENDERED_HTML_DIR
        / niche_slug
        / keyword
        / "products"
    )

    product_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # Standalone mode
    # ---------------------------------------------------------

    owns_proxy_manager = proxy_manager is None
    if proxy is None:

        proxy_manager = proxy_manager or ProxyManager()
        if not proxy_manager.pool_initialized:
            await proxy_manager.ensure_initial_proxy()
        proxy = proxy_manager.get_next_proxy()

        if proxy is None:

            raise RuntimeError(
                "No proxy available for "
                "product-detail stage."
            )

    logger.info("[DETAIL] Using configured proxy for this stage.")

    proxy_manager = proxy_manager or ProxyManager()
    if not proxy_manager.pool_initialized:
        await proxy_manager.ensure_initial_proxy()
    if proxy not in proxy_manager.healthy_proxies:
        raise ValueError("The supplied product proxy is not in the validated healthy pool.")
    proxy_manager.set_current_proxy(proxy)

    async with Stealth().use_async(
        async_playwright()
    ) as p:

        lifecycle = BrowserLifecycle(
            p,
            proxy,
            proxy_manager=proxy_manager,
            max_attempts=PROXY_RECOVERY_ATTEMPTS,
        )

        try:
            await lifecycle.start()

            products_scraped = 0
            completed_asins = set()

            semaphore = asyncio.Semaphore(
                PRODUCT_PAGE_CONCURRENCY
            )

            counter_lock = asyncio.Lock()

            active_tasks = 0
            active_tasks_lock = asyncio.Lock()

            logger.info(
                f"Detail concurrency configured: "
                f"{PRODUCT_PAGE_CONCURRENCY} "
                f"concurrent tasks."
            )

            async def scrape_product(
                asin_value,
                url,
            ):

                """Fetch, parse, and persist product-page details for one ASIN."""
                nonlocal products_scraped
                nonlocal active_tasks

                async with semaphore:

                    async with active_tasks_lock:

                        active_tasks += 1

                        logger.debug(
                            f"[DETAIL CONCURRENCY] "
                            f"Started {asin_value} | "
                            f"Active: {active_tasks}/"
                            f"{PRODUCT_PAGE_CONCURRENCY}"
                        )

                    try:

                        logger.debug(
                            f"Fetching product: "
                            f"{asin_value}"
                        )

                        browser_recoveries = 0
                        direct_captcha_retry = False
                        while True:
                            try:
                                lease = await lifecycle.lease(direct=direct_captcha_retry)
                            except BrowserContextCreationError as exc:
                                logger.warning(
                                    "Product context creation failed | ASIN=%s | error=%s",
                                    asin_value,
                                    type(exc).__name__,
                                )
                                break
                            result = None
                            try:
                                result = await fetch_page(
                                    url,
                                    lease.context,
                                    run_id=run_id,
                                    lease=lease,
                                )
                                if result is None:
                                    logger.warning("No page returned for %s", asin_value)
                                    break

                                page_html = await result.content()
                                if lease.retired:
                                    continue

                                html_file = product_dir / f"{run_id}_{asin_value}.html"
                                async with counter_lock:
                                    if asin_value not in completed_asins and not lease.retired:
                                        html_file.write_text(page_html, encoding="utf-8")
                                        completed_asins.add(asin_value)
                                        products_scraped = len(completed_asins)
                                logger.debug(
                                    "Saved product HTML | ASIN=%s | run_id=%s",
                                    asin_value,
                                    run_id,
                                )
                                break
                            except CaptchaDetectedError:
                                if lease.proxy is not None and not direct_captcha_retry:
                                    direct_captcha_retry = True
                                    logger.warning(
                                        "Product %s received a CAPTCHA through the active proxy; retrying this product once directly.",
                                        asin_value,
                                    )
                                    continue
                                logger.error("CAPTCHA detected while scraping product %s after direct retry.", asin_value)
                                raise
                            except FetchSupersededError:
                                continue
                            except Exception as exc:
                                if isinstance(exc, ProxyFailureError):
                                    await lifecycle.recover_proxy(lease, exc)
                                    logger.warning(
                                        "Coordinated proxy recovery; retrying unfinished product | ASIN=%s",
                                        asin_value,
                                    )
                                    continue
                                if requires_browser_recovery(exc, lease.browser):
                                    if browser_recoveries >= MAX_RETRIES:
                                        raise BrowserRecoveryError(
                                            f"Browser recovery retry budget exhausted for ASIN {asin_value}."
                                        ) from exc
                                    browser_recoveries += 1
                                    await lifecycle.recover(lease, exc)
                                    logger.warning(
                                        "Retrying unfinished product after browser recovery | ASIN=%s | attempt=%s/%s",
                                        asin_value,
                                        browser_recoveries,
                                        MAX_RETRIES,
                                    )
                                    continue
                                logger.error(
                                    "Failed scraping product %s: %s",
                                    asin_value,
                                    type(exc).__name__,
                                )
                                break
                            finally:
                                if result is not None:
                                    try:
                                        await result.close()
                                    except Exception:
                                        pass
                                await lifecycle.release(lease)

                    finally:

                        async with active_tasks_lock:

                            active_tasks -= 1

                            logger.debug(
                                f"[DETAIL CONCURRENCY] "
                                f"Finished {asin_value} | "
                                f"Active: {active_tasks}/"
                                f"{PRODUCT_PAGE_CONCURRENCY}"
                            )

            tasks = [
                asyncio.create_task(
                    scrape_product(
                        asin_value,
                        url,
                    )
                )
                for asin_value, url in zip(
                    asin,
                    product_url,
                )
            ]

            logger.info(
                f"[DETAIL CONCURRENCY] "
                f"Created {len(tasks)} product tasks. "
                f"Maximum concurrent tasks: "
                f"{PRODUCT_PAGE_CONCURRENCY}"
            )

            try:
                await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

            logger.info(
                f"Successfully scraped "
                f"{products_scraped} products."
            )

            # -------------------------------------------------
            # Entire product stage failed
            # -------------------------------------------------

            if products_scraped == 0:

                raise RuntimeError(
                    "Product-detail stage failed: "
                    "zero product pages were scraped."
                )

            return products_scraped

        except Exception:

            logger.exception(
                "Fatal error while fetching "
                "product details."
            )

            raise

        finally:

            await lifecycle.close()
            if owns_proxy_manager:
                await proxy_manager.close()
            logger.info("Browser lifecycle closed.")


def main():

    """Run the product-detail scraping stage from its command-line arguments."""
    print("=" * 52)
    print(
        "Welcome to the product scraping "
        "and storing function"
    )
    print("=" * 52)

    run_id = int(
        input(
            "What is the run_id??\n>>> "
        )
    )

    niche = (
        input(
            "What is the niche or category?\n>>> "
        )
        .strip()
        .lower()
        .replace(" ", "-")
    )

    keyword = (
        input(
            "What is the product or the keyword?\n>>> "
        )
        .strip()
        .lower()
        .replace(" ", "-")
    )

    product_url, asin = asyncio.run(
        fetch_product_url_from_search_results(
            run_id=run_id,
            keyword_slug=keyword,
            niche_slug=niche,
        )
    )

    products_scraped = asyncio.run(
        fetch_product_detail(
            asin=asin,
            product_url=product_url,
            niche_slug=niche,
            keyword=keyword,
            run_id=run_id,
        )
    )

    logger.info(
        f"Product detail scraping completed. "
        f"Products scraped: {products_scraped}"
    )


if __name__ == "__main__":
    main()
