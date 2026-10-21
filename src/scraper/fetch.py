"""Fetch pages with CAPTCHA, timeout, and proxy recovery handling."""

from src.config import *
from src.storage.db import *

import asyncio
import re

from src.logger import logger
from src.scraper.pacing import human_scroll
from src.scraper.browser import (
    BrowserDisconnectedError,
    requires_browser_recovery,
)


# =====================================================
# CAPTCHA Exception
# =====================================================

class CaptchaDetectedError(Exception):
    """
    Raised when Amazon presents a CAPTCHA, bot-check,
    security verification, or similar blocking page.
    """

    pass


class ProxyFailureError(Exception):
    """A navigation failed because its leased proxy transport is dead."""


class FetchSupersededError(Exception):
    """The browser generation used by this fetch was retired."""


class UnexpectedHTTPResponseError(Exception):
    """Navigation completed but returned an unsuccessful HTTP status."""


PROXY_ERROR_MARKERS = (
    "err_tunnel_connection_failed",
    "tunnel connection failed",
    "err_proxy_connection_failed",
    "err_proxy_connection_refused",
    "proxy connection refused",
    "proxy connection failed",
    "err_socks_connection_failed",
)


def is_proxy_transport_error(error):
    """Only explicit tunnel/proxy failures prove that the proxy is unusable.

    Generic reset, closed, DNS, timeout, HTTP, cancellation, and browser
    lifecycle errors remain page/network/browser failures and do not cool down
    the active proxy.
    """
    error_text = f"{type(error).__name__}: {error}".lower()
    return any(marker in error_text for marker in PROXY_ERROR_MARKERS)


def classify_fetch_error(error, browser=None):
    """Return the recovery category before any retry or proxy state change."""
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if requires_browser_recovery(error, browser):
        return "browser_lifecycle"
    if is_proxy_transport_error(error):
        return "proxy_transport"
    if "timeout" in type(error).__name__.lower() or "timeout" in str(error).lower():
        return "navigation_timeout"
    message = str(error).lower()
    if "name_not_resolved" in message or "dns" in message:
        return "dns_network"
    return "page_or_unknown"


def redact_error(error):
    """Mask credentials embedded in URLs before an error is logged."""
    return re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1***@", str(error))


# =====================================================
# CAPTCHA Detection
# =====================================================

async def is_captcha_page(page):

    """Detect CAPTCHA and robot-check markers in a rendered page."""
    title = (
        await page.title()
    ).lower()

    html = (
        await page.content()
    ).lower()

    markers = [
        "captcha",
        "awswaf",
        "challenge-container",
        "enter the characters you see below",
        "type the characters you see",
        "robot check",
        "sorry, we just need to make sure you're not a robot",
        "solve this puzzle",
        "/errors/validatecaptcha",
        "i'm not a robot",
        "access denied",
        "request blocked",
        "unusual traffic",
        "verify you are human",
        "verify that you're not a robot",
        "security check",
        "javascript is disabled",
    ]

    return any(
        marker in title or marker in html
        for marker in markers
    )


# =====================================================
# Page Fetch Workflow
# =====================================================



async def fetch_page(
    url,
    context,
    run_id,
    proxy_manager=None,
    context_factory=None,
    lease=None,
):
    """Fetch one page. A lease delegates proxy rotation to its stage."""

    logger.debug("Starting fetch workflow.")

    error_type = None
    errors = None
    active_context = lease.context if lease is not None else context

    for attempt in range(1, MAX_RETRIES + 1):
        logger.debug("Fetch attempt %s/%s.", attempt, MAX_RETRIES)

        page = None

        try:
            if lease is not None and lease.retired:
                raise FetchSupersededError("Proxy generation was retired")
            page = await active_context.new_page()
            logger.debug("Fetching page.")

            response = await page.goto(
                url,
                wait_until="load",
                timeout=60000,
            )

            logger.debug("Page navigation completed.")

            if await is_captcha_page(page):
                raise CaptchaDetectedError("CAPTCHA page detected")

            if response is not None and response.status >= 400:
                raise UnexpectedHTTPResponseError(
                    f"Navigation returned HTTP {response.status}."
                )

            webdriver_status = await page.evaluate(
                "navigator.webdriver"
            )

            logger.debug("navigator.webdriver=%s", webdriver_status)

            logger.debug("Starting human-like scrolling.")

            scroll_success = await human_scroll(page)

            if scroll_success is False:
                error_type = "scroll_failed"
                errors = "Human-like scrolling failed"

                log_scrape_error(
                    search_run_id=run_id,
                    url=url,
                    error_type=error_type,
                    error_message=errors,
                    attempt_number=attempt,
                )

                await page.close()
                page = None
                return None

            logger.debug("Page fetched successfully.")
            return page

        except CaptchaDetectedError as e:
            error_type = "captcha_detected"
            errors = str(e)

            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

            log_scrape_error(
                search_run_id=run_id,
                url=url,
                error_type=error_type,
                error_message=errors,
                attempt_number=attempt,
            )

            raise

        except FetchSupersededError:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            raise

        except asyncio.CancelledError:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            raise

        except Exception as e:
            error_type = type(e).__name__
            errors = redact_error(e)

            log = logger.warning if attempt < MAX_RETRIES else logger.error
            log(
                "Page fetch failed | attempt=%s/%s | category=%s | error=%s",
                attempt,
                MAX_RETRIES,
                classify_fetch_error(e, lease.browser if lease is not None else None),
                errors,
            )

            if page is not None:
                try:
                    await page.close()
                except Exception as close_error:
                    logger.warning("Failed to close page (%s).", type(close_error).__name__)

            proxy_error = is_proxy_transport_error(e)

            if lease is not None:
                if lease.retired:
                    raise FetchSupersededError("Proxy generation was retired") from e
                category = classify_fetch_error(e, lease.browser)
                if category == "browser_lifecycle":
                    raise BrowserDisconnectedError(
                        "Chromium disconnected while fetching a page."
                    ) from e
                if category == "proxy_transport":
                    raise ProxyFailureError(redact_error(e)) from e

            # Stop if no further retry attempt remains.
            if attempt >= MAX_RETRIES:
                logger.error(
                    f"Fetch failed on final attempt "
                    f"{attempt}/{MAX_RETRIES}. No further retry."
                )
                break

            # Proxy rotation belongs to the stage's shared coordinator. This
            # legacy no-lease path must never refresh/select a candidate itself.
            if proxy_error:
                logger.error("Proxy transport failure has no shared recovery lease; stopping this fetch.")
                break

            else:
                logger.warning(
                    "Ordinary fetch error detected. "
                    "Keeping the current proxy and context."
                )

            # Sequential backoff applies before every retry:
            # after attempt 1 -> 2 seconds; after attempt 2 -> 4 seconds.
            delay = 2 ** attempt

            logger.info(
                f"Retrying attempt {attempt + 1}/{MAX_RETRIES} "
                f"in {delay} seconds..."
            )

            await asyncio.sleep(delay)

            # Retry using either the existing context or the newly
            # created context, depending on the error type.
            continue

    logger.error(
        f"Failed to fetch URL: {url} after {MAX_RETRIES} attempts."
    )

    if lease is not None and lease.retired:
        raise FetchSupersededError("Proxy generation was retired")

    log_scrape_error(
        search_run_id=run_id,
        url=url,
        error_type=error_type,
        error_message=errors,
        attempt_number=attempt,
    )

    return None

