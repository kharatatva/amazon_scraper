"""Browser creation, health classification, recovery, and shutdown."""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.config import (
    HEADLESS, LOCALE, MAX_RETRIES, TIMEZONE, USER_AGENT, VIEWPORT,
    PROXY_VALIDATION_TIMEOUT_MS, PROXY_VALIDATION_URL,
)
from src.logger import logger


class BrowserInitializationError(RuntimeError):
    """Chromium or its initial browser context could not be started."""


class BrowserDisconnectedError(RuntimeError):
    """An operation failed after Chromium disconnected unexpectedly."""


class BrowserContextCreationError(RuntimeError):
    """An isolated page context could not be created on a live browser."""


class BrowserRecoveryError(RuntimeError):
    """The browser could not be replaced within the recovery budget."""


@dataclass(frozen=True)
class ProxyValidationResult:
    """Store the outcome of validating a proxy browser session."""
    outcome: str
    category: str | None = None
    status: int | None = None
    final_url: str | None = None
    diagnostic: str | None = None


async def validate_proxy(proxy: str, playwright, *, browser=None, url=PROXY_VALIDATION_URL,
                         timeout_ms=PROXY_VALIDATION_TIMEOUT_MS) -> ProxyValidationResult:
    """Validate a proxy by navigating through a proxy-bound Playwright context.

    A caller may pass one unproxied Chromium process for a validation batch;
    each candidate gets a context with its own immutable proxy setting.
    """
    if not isinstance(proxy, str) or not proxy.strip():
        return ProxyValidationResult("failed", "invalid_proxy", diagnostic="empty proxy configuration")
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(proxy)
        if parsed.scheme not in ("http", "https", "socks5") or not parsed.hostname or not parsed.port:
            return ProxyValidationResult("failed", "invalid_proxy", diagnostic="unsupported or malformed proxy URL")
    except (TypeError, ValueError):
        return ProxyValidationResult("failed", "invalid_proxy", diagnostic="malformed proxy URL")

    context = page = None
    owns_browser = browser is None
    if owns_browser:
        try:
            browser = await playwright.chromium.launch(headless=HEADLESS)
        except Exception as exc:
            return ProxyValidationResult("failed", "browser_launch", diagnostic=type(exc).__name__)
    try:
        proxy_host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        context = await browser.new_context(
            proxy={"server": f"{parsed.scheme}://{proxy_host}:{parsed.port}",
                   **({"username": parsed.username, "password": parsed.password}
                      if parsed.username is not None else {})},
            user_agent=USER_AGENT, viewport=VIEWPORT, locale=LOCALE,
            timezone_id=TIMEZONE,
        )
        page = await context.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if response is None:
            return ProxyValidationResult("failed", "no_response", diagnostic="navigation returned no response")
        title = (await page.title()).lower()
        body = (await page.locator("body").inner_text(timeout=5000)).lower()
        challenge_markers = ("captcha", "robot check", "verify you are human", "access denied",
                             "unusual traffic", "security check", "awswaf", "challenge-container")
        if any(marker in title or marker in body for marker in challenge_markers):
            return ProxyValidationResult("failed", "challenge", response.status if response else None,
                                         page.url, "Amazon returned an access challenge")
        status = response.status
        final_host = urlsplit(page.url).hostname or ""
        if final_host.lower() != "amazon.in" and not final_host.lower().endswith(".amazon.in"):
            return ProxyValidationResult(
                "failed", "unexpected_final_url", status, page.url,
                "navigation did not finish on an Amazon India host",
            )
        if "amazon" not in title and "amazon" not in body:
            return ProxyValidationResult(
                "failed", "unexpected_page_content", status, page.url,
                "response did not contain recognizable Amazon page content",
            )
        # Amazon sometimes serves the real page with 202. Accept that status
        # only after the challenge, URL, and page-content checks have passed.
        if status not in (200, 202):
            return ProxyValidationResult(
                "failed", "unexpected_http_status", status, page.url,
                "validation returned an unexpected HTTP status",
            )
        return ProxyValidationResult("passed", status=status, final_url=page.url)
    except Exception as exc:
        message = str(exc).lower()
        if browser is not None and not browser_is_connected(browser):
            category = "browser_disconnected"
        elif any(marker in message for marker in (
            "err_tunnel_connection_failed", "tunnel connection failed",
            "err_proxy_connection_failed", "proxy connection failed",
            "err_proxy_connection_refused", "proxy connection refused",
            "err_socks_connection_failed",
        )):
            category = "proxy_tunnel"
        elif "timeout" in message:
            category = "timeout"
        elif "name_not_resolved" in message or "dns" in message:
            category = "dns_network"
        else:
            category = "navigation_error"
        diagnostic = " ".join(str(exc).split()) or type(exc).__name__
        diagnostic = re.sub(
            r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@",
            r"\1***@",
            diagnostic,
        )
        return ProxyValidationResult("failed", category, diagnostic=diagnostic[:300])
    finally:
        if page is not None:
            try: await page.close()
            except Exception: pass
        if context is not None:
            try: await context.close()
            except Exception: pass
        if owns_browser:
            try: await browser.close()
            except Exception: pass


def browser_is_connected(browser) -> bool:
    """Return Playwright's structured browser-process health signal."""
    if browser is None:
        return False
    is_connected = getattr(browser, "is_connected", None)
    if is_connected is None:
        # Small test doubles and third-party browser wrappers may not expose it.
        return True
    try:
        return bool(is_connected())
    except Exception:
        return False


def requires_browser_recovery(error: BaseException, browser) -> bool:
    """Only classify lifecycle failures or a confirmed disconnection."""
    return isinstance(error, (BrowserDisconnectedError, BrowserInitializationError)) or (
        browser is not None and not browser_is_connected(browser)
    )


async def _close_resources(browser, context) -> None:
    if context is not None:
        try:
            await context.close()
        except Exception as exc:
            logger.debug("Could not close browser context cleanly: %s", type(exc).__name__)
    if browser is not None:
        try:
            await browser.close()
        except Exception as exc:
            logger.debug("Could not close browser cleanly: %s", type(exc).__name__)


async def initialize_browser(p, proxy: str = None):
    """Launch Chromium and a verified context; keep the legacy tuple API."""
    logger.info("Initializing browser environment.")
    launch_kwargs = {"headless": HEADLESS}
    if proxy:
        parsed_proxy = urlsplit(proxy)
        proxy_host = f"[{parsed_proxy.hostname}]" if parsed_proxy.hostname and ":" in parsed_proxy.hostname else parsed_proxy.hostname
        proxy_server = f"{parsed_proxy.scheme}://{proxy_host}:{parsed_proxy.port}"
        launch_kwargs["proxy"] = {
            "server": proxy_server,
            **({"username": parsed_proxy.username, "password": parsed_proxy.password or ""}
               if parsed_proxy.username is not None else {}),
        }
        logger.info("Launching Chromium with configured proxy.")
    else:
        logger.warning("Launching Chromium without a proxy.")

    browser = None
    context = None
    try:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport=VIEWPORT,
            locale=LOCALE,
            timezone_id=TIMEZONE,
        )
        if not browser_is_connected(browser):
            raise BrowserDisconnectedError("Chromium disconnected during startup.")
        probe = await context.new_page()
        await probe.close()
    except BaseException as exc:
        await _close_resources(browser, context)
        if not isinstance(exc, Exception):
            raise
        if isinstance(exc, BrowserInitializationError):
            raise
        raise BrowserInitializationError(
            f"Could not initialize Chromium and its browser context ({type(exc).__name__})."
        ) from exc

    logger.info("Browser and context initialized successfully.")
    return browser, context


@dataclass(frozen=True)
class BrowserLease:
    """A snapshot of the browser generation used by one scraping task."""

    lifecycle: "BrowserLifecycle"
    generation: int
    proxy: str | None
    browser: object
    context: object

    @property
    def retired(self) -> bool:
        """Report whether this browser generation has been retired."""
        return self.lifecycle.is_retired(self.generation)


class BrowserLifecycle:
    """Own one shared browser and coordinate single-flight recovery."""

    def __init__(
        self,
        playwright,
        proxy=None,
        browser_factory=None,
        max_attempts=MAX_RETRIES,
        proxy_manager=None,
    ):
        self.playwright = playwright
        self.proxy = proxy
        self.browser_factory = browser_factory or initialize_browser
        self.max_attempts = max(1, int(max_attempts))
        self.proxy_manager = proxy_manager
        self.proxy_recoveries = 0
        self.browser_recoveries = 0
        self.browser = None
        self.context = None
        self.generation = 0
        self.retired_generations = set()
        self.terminal_error = None
        self._lock = asyncio.Lock()
        self._closed = False
        # One context is shared by all page leases using a given browser
        # generation and active proxy. Pages become tabs in that context.
        self._lease_contexts = {}

    async def start(self):
        """Launch a browser generation and prepare its proxy context."""
        async with self._lock:
            if self.browser is not None and browser_is_connected(self.browser):
                return self
            self._closed = False
            await self._launch_with_retries()
        return self

    async def lease(self, *, direct=False) -> BrowserLease:
        """Lease the shared proxy context, or the direct context for one fallback."""
        recoveries = 0
        while True:
            async with self._lock:
                recover = False
                if self.terminal_error is not None:
                    raise self.terminal_error
                if self._closed:
                    raise BrowserRecoveryError("Browser lifecycle is closed.")
                if self.browser is not None and browser_is_connected(self.browser):
                    browser = self.browser
                    generation = self.generation
                    proxy = None if direct else self.proxy
                    key = (generation, proxy)
                    entry = self._lease_contexts.get(key)
                    if entry is None:
                        context = None
                        context_error = None
                        for _ in range(self.max_attempts):
                            try:
                                context = await browser.new_context(**self._context_options(proxy))
                                break
                            except Exception as exc:
                                context_error = exc
                                if not browser_is_connected(browser):
                                    recover = True
                                    break
                        if context is None:
                            if not recover:
                                raise BrowserContextCreationError(
                                    f"Could not create an isolated page context after {self.max_attempts} attempts."
                                ) from context_error
                        elif generation != self.generation or browser is not self.browser:
                            await context.close()
                            continue
                        else:
                            entry = [context, 0]
                            self._lease_contexts[key] = entry
                    if entry is not None:
                        context = entry[0]
                        entry[1] += 1
                        return BrowserLease(self, generation, proxy, browser, context)
                else:
                    recover = True
                if recoveries >= self.max_attempts:
                    self.terminal_error = BrowserRecoveryError(
                        "Browser disconnected repeatedly before a page lease was issued."
                    )
                    raise self.terminal_error
                stale_lease = self._current_lease()
                recoveries += 1
            await self.recover(
                stale_lease,
                BrowserDisconnectedError("Chromium disconnected before a page lease was issued."),
            )

    def is_retired(self, generation: int) -> bool:
        """Check whether the current browser generation is retired."""
        return generation in self.retired_generations

    @staticmethod
    def _context_options(proxy):
        options = {
            "user_agent": USER_AGENT, "viewport": VIEWPORT, "locale": LOCALE,
            "timezone_id": TIMEZONE,
        }
        if proxy:
            parsed = urlsplit(proxy)
            host = f"[{parsed.hostname}]" if parsed.hostname and ":" in parsed.hostname else parsed.hostname
            options["proxy"] = {
                "server": f"{parsed.scheme}://{host}:{parsed.port}",
                **({"username": parsed.username, "password": parsed.password or ""}
                   if parsed.username is not None else {}),
            }
        return options

    async def release(self, lease: BrowserLease):
        """Release a page lease and retire its old proxy context when unused."""
        key = (lease.generation, lease.proxy)
        entry = self._lease_contexts.get(key)
        if entry is not None and entry[0] is lease.context:
            entry[1] = max(0, entry[1] - 1)
            if entry[1] == 0 and key != (self.generation, self.proxy):
                self._lease_contexts.pop(key, None)
                context = entry[0]
                try:
                    await context.close()
                except Exception as exc:
                    logger.debug("Could not close retired proxy context (%s).", type(exc).__name__)

    async def recover(self, lease: BrowserLease, cause: BaseException) -> BrowserLease:
        """Replace a disconnected generation once, then share it with waiters."""
        if not requires_browser_recovery(cause, lease.browser):
            raise ValueError("Browser recovery requested for a request-level failure.")

        async with self._lock:
            if self.terminal_error is not None:
                raise self.terminal_error
            if lease.generation != self.generation:
                return self._current_lease()
            if self.browser_recoveries >= self.max_attempts:
                self.terminal_error = BrowserRecoveryError(
                    f"Browser recovery exhausted {self.max_attempts} attempt(s)."
                )
                raise self.terminal_error

            self.browser_recoveries += 1
            self.retired_generations.add(self.generation)
            contexts = [entry[0] for entry in self._lease_contexts.values()]
            self._lease_contexts.clear()
            for context in contexts:
                try:
                    await context.close()
                except Exception:
                    pass
            old_browser, old_context = self.browser, self.context
            self.browser = self.context = None
            await _close_resources(old_browser, old_context)

            try:
                await self._launch_with_retries(attempts=1)
            except Exception as exc:
                self.terminal_error = BrowserRecoveryError(
                    f"Browser recovery exhausted {self.max_attempts} startup attempts."
                )
                raise self.terminal_error from exc

            self.generation += 1
            logger.warning("Replaced disconnected browser with generation %s.", self.generation)
            return self._current_lease()

    async def recover_proxy(self, lease: BrowserLease, cause: BaseException) -> BrowserLease:
        """Rotate one failed shared proxy and replace its browser generation once."""
        if self.proxy_manager is None:
            raise BrowserRecoveryError("Proxy recovery requires a proxy manager.")

        async with self._lock:
            if self.terminal_error is not None:
                raise self.terminal_error
            # A second worker may report the same failed proxy after the first
            # has already committed the replacement. Reuse that transition.
            if lease.proxy != self.proxy:
                return self._current_lease()

            logger.warning(
                "Confirmed proxy transport failure; rotating shared proxy | category=proxy_transport | error_type=%s",
                type(cause).__name__,
            )
            try:
                # Another worker may already have rotated this exact lease.
                # Context proxying lets in-flight sibling pages keep using their
                # existing contexts while new leases use the replacement.
                if self.proxy_recoveries >= self.max_attempts:
                    self.proxy_manager.mark_proxy_failed(lease.proxy)
                    raise BrowserRecoveryError(
                        f"Proxy recovery exhausted {self.max_attempts} attempt(s)."
                    )
                self.proxy_recoveries += 1
                replacement = await self.proxy_manager.rotate_proxy(lease.proxy)
                if not replacement:
                    raise BrowserRecoveryError(
                        "Proxy manager could not provide a validated replacement."
                    )
                self.proxy = replacement
            except Exception as exc:
                self.terminal_error = BrowserRecoveryError(
                    f"Proxy recovery failed after {self.proxy_recoveries} attempt(s): {type(exc).__name__}."
                )
                raise self.terminal_error from exc
            logger.warning(
                "Selected replacement proxy for new page leases | browser_generation=%s.",
                self.generation,
            )
            return self._current_lease()

    async def close(self):
        """Close the browser resources owned by this generation."""
        async with self._lock:
            self._closed = True
            contexts = [entry[0] for entry in self._lease_contexts.values()]
            self._lease_contexts.clear()
            for context in contexts:
                try:
                    await context.close()
                except Exception:
                    pass
            browser, context = self.browser, self.context
            self.browser = self.context = None
            await _close_resources(browser, context)

    def _current_lease(self) -> BrowserLease:
        return BrowserLease(self, self.generation, self.proxy, self.browser, self.context)

    async def _launch_with_retries(self, attempts=None):
        last_error = None
        attempt_limit = max(1, self.max_attempts if attempts is None else attempts)
        for attempt in range(1, attempt_limit + 1):
            browser = context = None
            try:
                # Proxy settings are bound to each isolated BrowserContext.
                # A single Chromium process therefore serves the current proxy
                # across concurrent pages and can rotate without closing siblings.
                browser, context = await self.browser_factory(self.playwright, None)
                if not browser_is_connected(browser):
                    raise BrowserInitializationError("Chromium disconnected during startup.")
                probe_factory = getattr(context, "new_page", None)
                if probe_factory is not None:
                    probe = await probe_factory()
                    await probe.close()
                self.browser, self.context = browser, context
                self.terminal_error = None
                return
            except Exception as exc:
                last_error = exc
                await _close_resources(browser, context)
                logger.warning(
                    "Browser startup attempt %s/%s failed (%s).",
                    attempt,
                    attempt_limit,
                    type(exc).__name__,
                )
        raise BrowserInitializationError(
            f"Browser startup failed after {attempt_limit} attempt(s)."
        ) from last_error
