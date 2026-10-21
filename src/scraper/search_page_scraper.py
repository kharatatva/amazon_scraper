"""Collect and persist paginated niche search results."""


import asyncio
from urllib.parse import quote_plus

from playwright_stealth import Stealth
from playwright.async_api import async_playwright

from src.config import (
    RENDERED_HTML_DIR,
    SEARCH_PAGE_CONCURRENCY,
    MAX_PAGES_TO_CRAWL,
    MAX_RETRIES,
    PROXY_RECOVERY_ATTEMPTS,
)
from src.logger import logger

from src.scraper.fetch import fetch_page
from src.scraper.fetch import (
    CaptchaDetectedError,
    FetchSupersededError,
    ProxyFailureError,
    is_proxy_transport_error,
    redact_error,
)

from src.scraper.proxies import ProxyManager
from src.scraper.browser import (
    BrowserDisconnectedError,
    BrowserContextCreationError,
    BrowserRecoveryError,
    BrowserLifecycle,
    requires_browser_recovery,
)

from src.storage.db import (
    create_search_run,
    update_search_run,
    get_or_create_keyword,
    get_or_create_niche,
    link_niche_keyword,
)


def build_search_url(
    keyword: str,
    page: int,
) -> str:

    """Build a marketplace search URL for a keyword and page number."""
    encoded_keyword = quote_plus(
        keyword
    )

    return (
        f"https://www.amazon.in/s?"
        f"k={encoded_keyword}&page={page}"
    )


def create_search_run_for_pipeline(
    niche_name: str,
    keyword: str,
) -> int:
    """
    Create exactly one search run for the complete pipeline.

    The returned run_id is reused across search proxy
    attempts and all downstream pipeline stages.
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

    keyword_id = get_or_create_keyword(
        keyword
    )

    niche_id = get_or_create_niche(
        niche_name
    )

    if niche_id is None:

        raise ValueError(
            f"No niche is associated with keyword "
            f"'{keyword}'."
        )

    link_niche_keyword(
        niche_id,
        keyword_id,
    )

    search_run_id = create_search_run(
        niche_id=niche_id,
        keyword_id=keyword_id,
    )

    logger.info(
        f"[SEARCH] Created pipeline search run | "
        f"run_id={search_run_id}"
    )

    return search_run_id


async def fetch_search_results(
    niche_name: str,
    keyword: str,
    num_pages: int,
    proxy: str = None,
    run_id: int = None,
    proxy_manager: ProxyManager = None,
) -> int:
    """Scrape Amazon search pages with centralized proxy retries."""

    niche_name = niche_name.strip().lower().replace(" ", "-")
    keyword = keyword.strip().lower().replace(" ", "-")
    requested_num_pages = num_pages

    num_pages = min(num_pages, MAX_PAGES_TO_CRAWL)

    if num_pages < 1:
        raise ValueError("num_pages must be at least 1.")

    owns_proxy_manager = proxy_manager is None
    proxy_manager = proxy_manager or ProxyManager()
    if not proxy_manager.pool_initialized:
        await proxy_manager.ensure_initial_proxy()
    if proxy is not None and proxy not in proxy_manager.healthy_proxies:
        raise ValueError("The supplied search proxy is not in the validated healthy pool.")

    # Configuration snapshot for this search run.
    run_config = {
        "niche_name": niche_name,
        "keyword": keyword,
        "requested_num_pages": requested_num_pages,
        "effective_num_pages": num_pages,
        "max_pages_to_crawl": MAX_PAGES_TO_CRAWL,
        "search_page_concurrency": SEARCH_PAGE_CONCURRENCY,
        "search_url_template": (
            "https://www.amazon.in/s?k={keyword}&page={page}"
        ),
    }

    raw_html_dir = RENDERED_HTML_DIR / niche_name / keyword
    raw_html_dir.mkdir(parents=True, exist_ok=True)

    keyword_id = get_or_create_keyword(keyword)
    niche_id = get_or_create_niche(niche_name)

    if niche_id is None:
        raise ValueError(
            f"No niche is associated with keyword '{keyword}'."
        )

    link_niche_keyword(niche_id, keyword_id)

    if run_id is None:
        run_id = create_search_run(
            niche_id=niche_id,
            keyword_id=keyword_id,
        )
        logger.info(f"Created standalone search run ID: {run_id}")

    search_run_id = run_id

    # Stage: scrape_search
    update_search_run(
        search_run_id=search_run_id,
        pages_scraped=0,
        products_found=0,
        status="running",
        current_stage="scrape_search",
        current_task="Initializing search scraping",
        config_json=run_config
    )

    # One lifecycle shares the active proxy and browser across all page workers.
    if proxy is None:
        proxy = proxy_manager.get_next_proxy()

        if proxy is None:
            raise RuntimeError(
                "No proxy available for the search stage."
            )
    else:
        # Respect a proxy supplied by the pipeline.
        proxy_manager.set_current_proxy(proxy)

    logger.info("[SEARCH] Starting with the pipeline proxy.")

    pages_scraped = 0
    products_found = 0

    async with Stealth().use_async(async_playwright()) as p:
        logger.info("Playwright started successfully.")
        lifecycle = BrowserLifecycle(
            p,
            proxy,
            proxy_manager=proxy_manager,
            max_attempts=PROXY_RECOVERY_ATTEMPTS,
        )
        try:
            await lifecycle.start()
            completed_pages = set()
            failed_pages = set()
            completed_lock = asyncio.Lock()
            semaphore = asyncio.Semaphore(max(1, SEARCH_PAGE_CONCURRENCY))

            async def scrape_page(page_number):
                """Fetch and persist one search result page for the current run."""
                nonlocal pages_scraped
                html_file = raw_html_dir / f"{search_run_id}_page{page_number}.html"
                async with semaphore:
                    browser_recoveries = 0
                    direct_captcha_retry = False
                    logger.info(
                        "[SEARCH] Started page task | niche=%s | keyword=%s | run_id=%s | page=%s/%s",
                        niche_name,
                        keyword,
                        search_run_id,
                        page_number,
                        num_pages,
                    )
                    while page_number not in completed_pages:
                        try:
                            lease = await lifecycle.lease(direct=direct_captcha_retry)
                        except BrowserContextCreationError as exc:
                            logger.warning(
                                "Search page %s failed: isolated context creation exhausted (%s).",
                                page_number,
                                type(exc).__name__,
                            )
                            failed_pages.add(page_number)
                            return
                        result = None
                        try:
                            update_search_run(
                                search_run_id=search_run_id,
                                current_task=f"Fetching search page {page_number}/{num_pages}",
                            )
                            result = await fetch_page(
                                url=build_search_url(keyword, page_number),
                                context=lease.context,
                                run_id=search_run_id,
                                lease=lease,
                            )
                            if result is None:
                                failed_pages.add(page_number)
                                return
                            page_html = await result.content()
                            if lease.retired:
                                raise FetchSupersededError("Proxy generation retired before save")
                            html_file.write_text(page_html, encoding="utf-8")
                            async with completed_lock:
                                if page_number not in completed_pages:
                                    completed_pages.add(page_number)
                                    pages_scraped = len(completed_pages)
                            update_search_run(
                                search_run_id=search_run_id,
                                pages_scraped=pages_scraped,
                            )
                            logger.info(
                                "[SEARCH] Page scraped successfully | niche=%s | keyword=%s | run_id=%s | page=%s/%s | completed=%s/%s | route=%s | file=%s",
                                niche_name,
                                keyword,
                                search_run_id,
                                page_number,
                                num_pages,
                                pages_scraped,
                                num_pages,
                                "direct" if lease.proxy is None else "proxy",
                                html_file,
                            )
                            return
                        except CaptchaDetectedError:
                            if lease.proxy is not None and not direct_captcha_retry:
                                direct_captcha_retry = True
                                logger.warning(
                                    "Search page %s received a CAPTCHA through the active proxy; retrying this page once directly.",
                                    page_number,
                                )
                                continue
                            raise
                        except BrowserDisconnectedError as exc:
                            if browser_recoveries >= MAX_RETRIES:
                                raise BrowserRecoveryError(
                                    f"Browser recovery retry budget exhausted for search page {page_number}."
                                ) from exc
                            browser_recoveries += 1
                            await lifecycle.recover(lease, exc)
                            continue
                        except FetchSupersededError:
                            logger.debug("Retrying page %s on the current proxy generation", page_number)
                            continue
                        except ProxyFailureError as exc:
                            logger.warning("Proxy failed for search page %s: %s", page_number, redact_error(exc))
                            await lifecycle.recover_proxy(lease, exc)
                        except Exception as exc:
                            if lease.retired:
                                logger.debug("Retrying page %s after its browser generation retired", page_number)
                                continue
                            if requires_browser_recovery(exc, lease.browser):
                                if browser_recoveries >= MAX_RETRIES:
                                    raise BrowserRecoveryError(
                                        f"Browser recovery retry budget exhausted for search page {page_number}."
                                    ) from exc
                                browser_recoveries += 1
                                await lifecycle.recover(lease, exc)
                                continue
                            if is_proxy_transport_error(exc):
                                await lifecycle.recover_proxy(lease, exc)
                                continue
                            logger.exception("Search page %s failed: %s", page_number, exc)
                            failed_pages.add(page_number)
                            return
                        finally:
                            if result is not None:
                                try:
                                    await result.close()
                                except Exception:
                                    pass
                            await lifecycle.release(lease)

            page_tasks = [
                asyncio.create_task(scrape_page(n))
                for n in range(1, num_pages + 1)
            ]
            logger.info(
                "[SEARCH] Created concurrent page tasks | niche=%s | keyword=%s | run_id=%s | tasks=%s | concurrency_limit=%s",
                niche_name,
                keyword,
                search_run_id,
                len(page_tasks),
                max(1, SEARCH_PAGE_CONCURRENCY),
            )
            try:
                await asyncio.gather(*page_tasks)
            except BaseException:
                for task in page_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*page_tasks, return_exceptions=True)
                raise
            pages_scraped = len(completed_pages)

            if pages_scraped == num_pages:
                status = "success"
            elif pages_scraped > 0:
                status = "partial"
            else:
                status = "failed"

            update_search_run(
                search_run_id=search_run_id,
                pages_scraped=pages_scraped,
                products_found=products_found,
                status=status,
                notes=(
                    None
                    if pages_scraped
                    else "No search pages were scraped."
                ),
                current_stage="scrape_search",
                current_task="Search scraping completed",

            )

            logger.info(
                f"[SEARCH] Complete | run_id={search_run_id} | "
                f"pages={pages_scraped}/{num_pages} | status={status}"
            )

            if pages_scraped == 0:
                raise RuntimeError(
                    "Search stage failed: no search pages were scraped."
                )

        except Exception as e:
            logger.error("Search workflow failed (%s): %s", type(e).__name__, redact_error(e))

            update_search_run(
                search_run_id=search_run_id,
                pages_scraped=pages_scraped,
                products_found=products_found,
                status="failed",
                notes=redact_error(e),
                current_stage="scrape_search",
                current_task="Search scraping failed",
            )

            raise

        finally:
            await lifecycle.close()
            if owns_proxy_manager:
                await proxy_manager.close()

    return search_run_id


def main():

    """Run search collection for the supplied niche and keyword."""
    print("=" * 52)
    print(
        "Welcome to the Amazon search scraping function"
    )
    print("=" * 52)

    niche_name = (
        input("Enter niche: ")
        .strip()
        .lower()
    )

    keyword = (
        input("Enter keyword: ")
        .strip()
        .lower()
    )

    num_pages = int(
        input(
            "Enter the number of pages to scrape: "
        )
    )

    if num_pages > MAX_PAGES_TO_CRAWL:

        logger.info(
            f"Number of pages: {num_pages} "
            f"exceeds MAX_PAGES_TO_CRAWL "
            f"({MAX_PAGES_TO_CRAWL}). "
            f"Limiting to {MAX_PAGES_TO_CRAWL} pages."
        )

        num_pages = MAX_PAGES_TO_CRAWL

    search_run_id = asyncio.run(
        fetch_search_results(
            niche_name=niche_name,
            keyword=keyword,
            num_pages=num_pages,
        )
    )

    logger.info(
        f"Search scraping completed. "
        f"Search run ID: {search_run_id}"
    )


if __name__ == "__main__":
    main()


