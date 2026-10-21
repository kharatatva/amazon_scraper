"""Proxy API acquisition, browser validation, health state, and cooldowns."""

import asyncio
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from playwright.async_api import async_playwright

from src.config import (
    PROXY_API_URL, PROXY_API_PROXY_TIMEOUT_MS, PROXY_COOLDOWN, PROXY_HEALTHY_TARGET,
    PROXY_MIN_HEALTHY_TO_START,
    PROXY_MAX_POOL_REFRESHES, PROXY_POOL_SIZE, PROXY_TIMEOUT,
    PROXY_MAX_VALIDATION_CANDIDATES,
    PROXY_VALIDATION_CONCURRENCY,
    PROXY_VALIDATION_TIMEOUT_MS, PROXY_VALIDATION_URL,
)
from src.logger import logger
from src.scraper.browser import ProxyValidationResult, validate_proxy


def _normalize_proxy(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if "://" not in value:
        value = "http://" + value
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https", "socks5") or not parsed.hostname or not parsed.port:
            return None
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        auth = ""
        if parsed.username is not None:
            auth = f"{parsed.username}:{parsed.password or ''}@"
        return urlunsplit((parsed.scheme.lower(), f"{auth}{host}:{parsed.port}", "", "", ""))
    except (TypeError, ValueError):
        return None


def fetch_proxies(skip=0):
    """Fetch a normalized, deduplicated candidate list from the configured API."""
    logger.info(
        "Fetching candidate proxy pool from Proxy API | skip=%s limit=%s.",
        max(0, int(skip)),
        PROXY_POOL_SIZE,
    )
    try:
        response = requests.get(
            PROXY_API_URL,
            params={
                "timeout": PROXY_API_PROXY_TIMEOUT_MS,
                "limit": PROXY_POOL_SIZE,
                "skip": max(0, int(skip)),
            },
            timeout=PROXY_TIMEOUT,
        )
        response.raise_for_status()
        proxies, seen = [], set()
        lines = [line for line in response.text.splitlines() if line.strip()]
        rejected = duplicates = 0
        for line in lines:
            proxy = _normalize_proxy(line)
            if not proxy:
                rejected += 1
                continue
            if proxy in seen:
                duplicates += 1
                continue
            seen.add(proxy)
            if len(proxies) < PROXY_POOL_SIZE:
                proxies.append(proxy)
        logger.info(
            "Fetched %s unique proxy candidate(s) | response_lines=%s | rejected=%s | duplicates=%s.",
            len(proxies), len(lines), rejected, duplicates,
        )
        return proxies
    except requests.RequestException as exc:
        logger.error("Proxy API request failed (%s).", type(exc).__name__)
        return []
    except Exception as exc:
        logger.error("Unexpected proxy API error (%s).", type(exc).__name__)
        return []


class ProxyAcquisitionError(RuntimeError):
    """The required number of browser-validated proxies could not be acquired."""


class ProxyManager:
    """Own proxy validation, the recovery pool, selection, and rotation."""

    def __init__(self):
        self._next_proxy_offset = 0
        # Candidate fetching and validation run in the background after the
        # event loop starts, so manager construction does not block the run.
        self.proxies: list[str] = []
        self.healthy_proxies: list[str] = []
        self.validation_results: dict[str, ProxyValidationResult] = {}
        self.cooldown = PROXY_COOLDOWN
        self.blacklisted_proxies: dict[str, float] = {}
        self.failed_proxies = set()
        self.current_proxy = None
        self.current_proxy_index = 0
        # True means at least one validated proxy is ready for pipeline work.
        self.pool_initialized = False
        self._acquisition_lock = None
        self._validation_task = None
        self._validation_error = None
        self._healthy_available_event = None
        logger.info("Proxy Manager initialized; candidate loading will run asynchronously.")

    def _fetch_next_proxy_pool(self):
        """Fetch the next page of candidates, keeping refreshes distinct."""
        skip = getattr(self, "_next_proxy_offset", 0)
        candidates = fetch_proxies(skip=skip)
        if candidates:
            self._next_proxy_offset = skip + PROXY_POOL_SIZE
        return candidates

    def _healthy_event(self):
        if getattr(self, "_healthy_available_event", None) is None:
            self._healthy_available_event = asyncio.Event()
        return self._healthy_available_event

    def _available_healthy(self):
        return [proxy for proxy in self.healthy_proxies if not self._in_cooldown(proxy)]

    async def _ensure_validation_worker(self, target_count):
        """Start or reuse the background worker that fills the healthy pool."""
        if self._acquisition_lock is None:
            self._acquisition_lock = asyncio.Lock()
        async with self._acquisition_lock:
            if len(self._available_healthy()) >= target_count:
                return None
            task = getattr(self, "_validation_task", None)
            if task is not None and not task.done():
                return task
            self._validation_error = None
            self._validation_task = asyncio.create_task(
                self._validate_candidate_pools(target_count)
            )
            return self._validation_task

    async def ensure_initial_proxy(self):
        """Fill the reserve pool up to target, requiring the configured start minimum."""
        task = await self._ensure_validation_worker(PROXY_HEALTHY_TARGET)
        if task is not None:
            await asyncio.shield(task)
        if len(self._available_healthy()) < PROXY_MIN_HEALTHY_TO_START:
            validation_error = getattr(self, "_validation_error", None)
            if validation_error is not None:
                raise ProxyAcquisitionError(
                    f"Proxy validation failed before a usable proxy was ready: "
                    f"{type(validation_error).__name__}."
                ) from validation_error
            raise ProxyAcquisitionError(
                "Proxy acquisition failed: no validated proxy became available "
                "within the configured refresh budget."
            )
        self.pool_initialized = True
        logger.info(
            "Initial proxy ready; validation is paused while scraping runs | ready=%s.",
            len(self._available_healthy()),
        )
        return True

    async def _wait_for_available_proxy(self, task=None, required_count=1):
        event = self._healthy_event()
        while True:
            if len(self._available_healthy()) >= required_count:
                self.pool_initialized = True
                return

            event.clear()
            if len(self._available_healthy()) >= required_count:
                continue

            task = task or getattr(self, "_validation_task", None)
            if task is None or task.done():
                validation_error = getattr(self, "_validation_error", None)
                if validation_error is not None:
                    raise ProxyAcquisitionError(
                        f"Proxy validation failed before a usable proxy was ready: "
                        f"{type(validation_error).__name__}."
                    ) from validation_error
                raise ProxyAcquisitionError(
                    "Proxy acquisition failed: no validated proxy became available "
                    "within the configured refresh budget."
                )
            await event.wait()

    async def get_healthy_proxies(self, target_count=PROXY_HEALTHY_TARGET):
        """Wait for the configured number of validated proxies to be available.

        Pipeline entry points use ``ensure_initial_proxy`` so normal scraping
        starts with one validated proxy and no validation still running.
        """
        if target_count < 1 or target_count > PROXY_HEALTHY_TARGET:
            raise ValueError(
                f"target_count must be between 1 and {PROXY_HEALTHY_TARGET}"
            )
        task = await self._ensure_validation_worker(target_count)
        if task is not None:
            await asyncio.shield(task)
        available = self._available_healthy()
        if len(available) < target_count:
            validation_error = getattr(self, "_validation_error", None)
            if validation_error is not None:
                raise ProxyAcquisitionError(
                    f"Proxy validation could not fill the pool: "
                    f"{type(validation_error).__name__}."
                ) from validation_error
            proxy_word = "proxy" if target_count == 1 else "proxies"
            raise ProxyAcquisitionError(
                f"Proxy acquisition failed: required {target_count} healthy {proxy_word}, "
                f"acquired {len(available)} within the configured refresh budget."
            )
        self.pool_initialized = True
        return available

    async def _validate_candidate_batch(
        self, candidates, playwright, browser, pool_number, attempted,
        required_count=PROXY_HEALTHY_TARGET,
    ):
        """Validate one bounded wave and retain every pass from that wave."""
        unique_candidates = []
        page_seen = set()
        for candidate in candidates[:PROXY_MAX_VALIDATION_CANDIDATES]:
            proxy = _normalize_proxy(candidate)
            if not proxy or proxy in page_seen or proxy in attempted:
                continue
            page_seen.add(proxy)
            attempted.add(proxy)

            previous = self.validation_results.get(proxy)
            if previous is not None:
                if proxy in self.failed_proxies:
                    if self._in_cooldown(proxy):
                        continue
                    self.failed_proxies.discard(proxy)
                    self.validation_results.pop(proxy, None)
                elif previous.outcome == "passed" and not self._in_cooldown(proxy):
                    if proxy not in self.healthy_proxies:
                        self.healthy_proxies.append(proxy)
                        self._healthy_event().set()
                    continue
                else:
                    continue
            unique_candidates.append(proxy)

        if not unique_candidates:
            return

        semaphore = asyncio.Semaphore(max(1, PROXY_VALIDATION_CONCURRENCY))

        async def validate_one(index, proxy):
            """Validate one proxy using a controlled browser request."""
            async with semaphore:
                logger.info(
                    "Validating proxy candidate (%s/%s in wave; pool %s).",
                    index,
                    len(unique_candidates),
                    pool_number,
                )
                try:
                    result = await validate_proxy(
                        proxy,
                        playwright,
                        browser=browser,
                        url=PROXY_VALIDATION_URL,
                        timeout_ms=PROXY_VALIDATION_TIMEOUT_MS,
                    )
                except Exception as exc:
                    result = ProxyValidationResult(
                        "failed",
                        "validation_error",
                        diagnostic=type(exc).__name__,
                    )

            infrastructure_failure = result.category in (
                "browser_launch",
                "browser_disconnected",
            )
            if infrastructure_failure:
                # This says nothing about the candidate itself; allow a later
                # worker to retry it after the validation browser is healthy.
                self.validation_results.pop(proxy, None)
            else:
                self.validation_results[proxy] = result
            if result.outcome == "passed":
                self.failed_proxies.discard(proxy)
                if not self._in_cooldown(proxy):
                    if proxy not in self.healthy_proxies:
                        self.healthy_proxies.append(proxy)
                    self.pool_initialized = True
                    self._healthy_event().set()
                logger.info("Proxy validation passed | status=%s", result.status)
            else:
                logger.warning(
                    "Proxy validation failed | category=%s | status=%s | diagnostic=%s",
                    result.category,
                    result.status,
                    result.diagnostic,
                )
                if result.category in ("proxy_tunnel", "proxy_transport"):
                    self.blacklisted_proxies[proxy] = time.time()
            return result

        pending = {
            asyncio.create_task(validate_one(index, proxy))
            for index, proxy in enumerate(unique_candidates, start=1)
        }
        results = []
        while pending:
            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            results.extend(await asyncio.gather(*done))
            if len(self._available_healthy()) >= required_count:
                break
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if any(result.category in ("browser_launch", "browser_disconnected") for result in results):
            raise ProxyAcquisitionError(
                "Proxy validation stopped because the validation browser became unavailable."
            )

    async def _validate_candidate_pools(self, target_count):
        """Check candidate waves until the requested healthy count is available."""
        refreshes = 0
        pool_number = 1
        attempted = set()
        browser = None
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                candidates = list(self.proxies)
                if not candidates:
                    candidates = await asyncio.to_thread(self._fetch_next_proxy_pool)
                    self.proxies.extend(candidates)
                logger.info(
                    "Proxy validation started | candidates=%s target=%s concurrency=%s.",
                    len(candidates),
                    target_count,
                    max(1, PROXY_VALIDATION_CONCURRENCY),
                )

                while True:
                    if len(attempted) >= PROXY_MAX_VALIDATION_CANDIDATES:
                        break
                    wave_size = max(1, PROXY_VALIDATION_CONCURRENCY)
                    for start in range(0, len(candidates), wave_size):
                        if len(attempted) >= PROXY_MAX_VALIDATION_CANDIDATES:
                            break
                        wave = candidates[start:start + wave_size]
                        wave = wave[:max(0, PROXY_MAX_VALIDATION_CANDIDATES - len(attempted))]
                        if not wave:
                            break
                        await self._validate_candidate_batch(
                            wave, playwright, browser, pool_number, attempted,
                            required_count=target_count,
                        )
                        # Let the current wave settle so its other passing
                        # candidates are retained, then stop before scraping.
                        if len(self._available_healthy()) >= target_count:
                            break

                    if len(self._available_healthy()) >= target_count:
                        break
                    if len(attempted) >= PROXY_MAX_VALIDATION_CANDIDATES:
                        break
                    if refreshes >= PROXY_MAX_POOL_REFRESHES:
                        break

                    refreshes += 1
                    logger.info(
                        "Refreshing proxy pool | refresh=%s/%s",
                        refreshes,
                        PROXY_MAX_POOL_REFRESHES,
                    )
                    candidates = await asyncio.to_thread(self._fetch_next_proxy_pool)
                    known_candidates = {
                        _normalize_proxy(candidate) for candidate in self.proxies
                    }
                    new_candidates = []
                    for candidate in candidates:
                        normalized = _normalize_proxy(candidate)
                        if normalized and normalized not in known_candidates:
                            self.proxies.append(normalized)
                            known_candidates.add(normalized)
                        if normalized and normalized not in attempted:
                            new_candidates.append(normalized)
                    logger.info("Proxy refresh returned %s new candidate(s).", len(new_candidates))
                    if not new_candidates:
                        logger.info("This refreshed pool contained no untested candidates.")
                    candidates = new_candidates
                    pool_number += 1

                try:
                    await browser.close()
                except Exception:
                    pass
                browser = None

            available = self._available_healthy()
            if len(available) < target_count:
                logger.warning(
                    "Proxy pool scan ended below target | available=%s target=%s; "
                    "the active pipeline may continue with its validated proxy.",
                    len(available),
                    target_count,
                )
            else:
                logger.info(
                    "Validated proxy pool ready | available=%s target=%s",
                    len(available),
                    target_count,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._validation_error = exc
            logger.exception("Proxy validation worker stopped (%s).", type(exc).__name__)
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            self._healthy_event().set()

    async def close(self):
        """Stop background validation and release its browser resources."""
        task = getattr(self, "_validation_task", None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _in_cooldown(self, proxy):
        failed_at = self.blacklisted_proxies.get(proxy)
        if failed_at is None:
            return False
        if time.time() - failed_at < self.cooldown:
            return True
        del self.blacklisted_proxies[proxy]
        return False

    def get_next_proxy(self):
        """Select only a validated, non-cooled-down proxy."""
        pool = self.healthy_proxies
        if not pool:
            logger.warning("No browser-validated proxy is available.")
            self.current_proxy = None
            return None
        for _ in range(len(pool)):
            proxy = pool[self.current_proxy_index % len(pool)]
            self.current_proxy_index = (self.current_proxy_index + 1) % len(pool)
            if self._in_cooldown(proxy):
                continue
            self.current_proxy = proxy
            logger.info("Selected a validated proxy candidate.")
            return proxy
        self.current_proxy = None
        logger.warning("No validated proxy is available outside cooldown.")
        return None

    def get_current_proxy(self):
        """Return the proxy currently assigned to this manager."""
        return self.current_proxy

    def set_current_proxy(self, proxy):
        """Set a stage's shared active proxy after checking its validation state."""
        if proxy not in self.healthy_proxies or self._in_cooldown(proxy):
            raise ValueError("The active proxy must be present in the validated pool.")
        if self.current_proxy != proxy:
            proxy_index = self.healthy_proxies.index(proxy)
            self.current_proxy_index = (proxy_index + 1) % len(self.healthy_proxies)
        self.current_proxy = proxy
        logger.info("Using a validated proxy as the shared active proxy.")
        return proxy

    def mark_proxy_failed(self, proxy):
        """Remove a failed proxy from the healthy pool and apply cooldown."""
        if not proxy:
            return
        self.blacklisted_proxies[proxy] = time.time()
        self.failed_proxies.add(proxy)
        if self.current_proxy == proxy:
            self.current_proxy = None
        try:
            failed_index = self.healthy_proxies.index(proxy)
        except ValueError:
            failed_index = self.current_proxy_index
        self.healthy_proxies = [candidate for candidate in self.healthy_proxies if candidate != proxy]
        self.proxies = [candidate for candidate in self.proxies if candidate != proxy]
        self.pool_initialized = bool(self._available_healthy())
        self.current_proxy_index = failed_index % max(1, len(self.healthy_proxies))
        logger.warning("Proxy marked as failed and placed in cooldown (%ss).", self.cooldown)

    def clear_current_proxy(self, proxy):
        """Clear a selected proxy when its browser could not be initialized."""
        if self.current_proxy == proxy:
            self.current_proxy = None

    async def rotate_proxy(self, failed_proxy):
        """Use a validated reserve or validate until one replacement is ready.

        BrowserLifecycle calls this while recovery holds its shared lock, so page
        workers cannot resume with the retired browser until this returns.
        """
        self.mark_proxy_failed(failed_proxy)

        # A pass from an earlier validation wave is already safe to use. Avoid
        # starting another wave when a validated reserve is ready.
        replacement = self.get_next_proxy()
        if replacement:
            return replacement

        # No reserve remains. Validate with the existing configured concurrency
        # and wait for that wave/refresh cycle to finish before scraping resumes.
        task = await self._ensure_validation_worker(PROXY_MIN_HEALTHY_TO_START)
        if task is not None:
            await asyncio.shield(task)
        replacement = self.get_next_proxy()
        if not replacement:
            validation_error = getattr(self, "_validation_error", None)
            if validation_error is not None:
                raise ProxyAcquisitionError(
                    "Proxy recovery could not validate a replacement: "
                    f"{type(validation_error).__name__}."
                ) from validation_error
            raise ProxyAcquisitionError(
                "Proxy recovery failed: validation completed without a usable replacement."
            )
        return replacement

