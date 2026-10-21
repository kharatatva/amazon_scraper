"""Offline tests for proxy validation behavior."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.scraper.browser import ProxyValidationResult, validate_proxy
from src.scraper.proxies import ProxyAcquisitionError, ProxyManager


class FakeBrowser:
    async def close(self):
        pass


class FakeChromium:
    async def launch(self):
        return FakeBrowser()


class FakePlaywright:
    chromium = FakeChromium()


class FakePlaywrightContext:
    async def __aenter__(self):
        return FakePlaywright()

    async def __aexit__(self, *args):
        return False


class FailedChromium:
    async def launch(self, **kwargs):
        raise RuntimeError("controlled launch failure")


class FailedPlaywright:
    chromium = FailedChromium()


class FakeResponse:
    def __init__(self, status=202):
        self.status = status


class FakeLocator:
    def __init__(self, text="Amazon shopping homepage"):
        self.text = text

    async def inner_text(self, **kwargs):
        return self.text


class FakePage:
    url = "https://www.amazon.in/"

    def __init__(self, status=202, body="Amazon shopping homepage"):
        self.closed = False
        self.response = FakeResponse(status)
        self.body = body

    async def goto(self, *args, **kwargs):
        return self.response

    async def title(self):
        return "Amazon.in" if "amazon" in self.body.lower() else "Unexpected response"

    def locator(self, selector):
        return FakeLocator(self.body)

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, status=202, body="Amazon shopping homepage"):
        self.page = FakePage(status=status, body=body)
        self.closed = False

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class FakeBrowserForValidation:
    def __init__(self, status=202, body="Amazon shopping homepage"):
        self.context = FakeContext(status=status, body=body)

    async def new_context(self, **kwargs):
        return self.context


class ProxyAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(self, candidates):
        manager = ProxyManager.__new__(ProxyManager)
        manager.proxies = list(candidates)
        manager.healthy_proxies = []
        manager.validation_results = {}
        manager.cooldown = 300
        manager.blacklisted_proxies = {}
        manager.failed_proxies = set()
        manager.current_proxy = None
        manager.current_proxy_index = 0
        manager._acquisition_lock = None
        return manager

    async def test_acquires_three_validated_proxies_and_deduplicates(self):
        candidates = ["http://a.example:80", "http://a.example:80", "b.example:81", "c.example:82"]
        manager = self.make_manager(candidates)
        results = [ProxyValidationResult("passed", status=200)] * 3

        async def validate(proxy, *args, **kwargs):
            return results.pop(0)

        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", side_effect=validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=[]):
            healthy = await manager.get_healthy_proxies(target_count=3)

        self.assertEqual(healthy, ["http://a.example:80", "http://b.example:81", "http://c.example:82"])
        self.assertEqual(manager.get_next_proxy(), healthy[0])

    async def test_validation_stops_waiting_after_healthy_target_is_reached(self):
        candidates = [f"http://proxy-{index}.example:80" for index in range(10)]
        manager = self.make_manager(candidates)
        cancelled = []

        async def validate(proxy, *args, **kwargs):
            if proxy in candidates[:3]:
                return ProxyValidationResult("passed", status=200)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(proxy)
                raise

        with patch("src.scraper.proxies.PROXY_VALIDATION_CONCURRENCY", 10), \
             patch("src.scraper.proxies.validate_proxy", side_effect=validate):
            await manager._validate_candidate_batch(
                candidates, object(), object(), pool_number=1,
                attempted=set(), required_count=3,
            )

        self.assertEqual(len(manager.healthy_proxies), 3)
        self.assertEqual(len(cancelled), 7)

    async def test_browser_launch_failure_is_not_reported_as_proxy_failure(self):
        result = await validate_proxy("http://proxy.example:8080", FailedPlaywright())
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.category, "browser_launch")

    async def test_http_202_requires_real_amazon_content_and_resources_close(self):
        browser = FakeBrowserForValidation()
        result = await validate_proxy(
            "http://proxy.example:8080", FakePlaywright(), browser=browser,
        )
        self.assertEqual(result.outcome, "passed")
        self.assertEqual(result.status, 202)
        self.assertTrue(browser.context.page.closed)
        self.assertTrue(browser.context.closed)

        challenge_or_error_page = FakeBrowserForValidation(body="Temporary service response")
        rejected = await validate_proxy(
            "http://proxy.example:8080", FakePlaywright(), browser=challenge_or_error_page,
        )
        self.assertEqual(rejected.outcome, "failed")
        self.assertEqual(rejected.category, "unexpected_page_content")

    async def test_acquisition_fails_when_three_validated_candidates_are_unavailable(self):
        manager = self.make_manager(["a.example:80", "b.example:81"])
        outcomes = [
            ProxyValidationResult("passed", status=200),
            ProxyValidationResult("failed", "proxy_tunnel"),
        ]

        async def validate(proxy, *args, **kwargs):
            return outcomes.pop(0)

        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", side_effect=validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=["a.example:80", "b.example:81"]):
            with self.assertRaisesRegex(ProxyAcquisitionError, "required 3 healthy proxies"):
                await manager.get_healthy_proxies()

    async def test_failed_candidates_can_be_replenished_from_a_new_pool(self):
        manager = self.make_manager(["a.example:80", "b.example:81"])
        results = [
            ProxyValidationResult("failed", "timeout"),
            ProxyValidationResult("passed", status=200),
            ProxyValidationResult("passed", status=200),
            ProxyValidationResult("passed", status=200),
        ]

        async def validate(proxy, *args, **kwargs):
            return results.pop(0)

        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", side_effect=validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=["c.example:82", "d.example:83"]):
            healthy = await manager.get_healthy_proxies()
        self.assertEqual(healthy, ["http://b.example:81", "http://c.example:82", "http://d.example:83"])

    async def test_two_valid_candidates_are_retained_when_refresh_adds_the_third(self):
        manager = self.make_manager(["a.example:80", "b.example:81"])
        validated = []

        async def validate(proxy, *args, **kwargs):
            validated.append(proxy)
            return ProxyValidationResult("passed", status=200)

        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", side_effect=validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=["a.example:80", "b.example:81", "c.example:82"]):
            healthy = await manager.get_healthy_proxies(target_count=3)

        self.assertEqual(healthy, [
            "http://a.example:80", "http://b.example:81", "http://c.example:82",
        ])
        self.assertEqual(validated, healthy)

    async def test_duplicate_candidates_from_refresh_are_not_retested(self):
        manager = self.make_manager(["a.example:80", "b.example:81"])
        validate = AsyncMock(return_value=ProxyValidationResult("passed", status=200))

        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=[
                 "a.example:80", "b.example:81", "c.example:82",
             ]):
            healthy = await manager.get_healthy_proxies(target_count=3)

        self.assertEqual(len(healthy), 3)
        self.assertEqual(validate.await_count, 3)

    async def test_rotation_uses_next_validated_proxy_from_existing_reserve(self):
        manager = self.make_manager([
            "a.example:80", "b.example:81", "c.example:82",
        ])
        manager.healthy_proxies = [
            "http://a.example:80", "http://b.example:81", "http://c.example:82",
        ]
        manager.proxies = list(manager.healthy_proxies)
        manager.pool_initialized = True
        manager.validation_results = {
            proxy: ProxyValidationResult("passed", status=200)
            for proxy in manager.healthy_proxies
        }
        self.assertEqual(manager.get_next_proxy(), "http://a.example:80")

        replacement = await manager.rotate_proxy("http://a.example:80")

        self.assertEqual(replacement, "http://b.example:81")
        self.assertEqual(manager.healthy_proxies, [
            "http://b.example:81", "http://c.example:82",
        ])
        self.assertTrue(manager.pool_initialized)
        self.assertEqual(manager.validation_results[replacement].outcome, "passed")

    async def test_exhausted_reserve_is_refreshed_and_replacement_is_validated(self):
        manager = self.make_manager(["a.example:80"])
        manager.healthy_proxies = ["http://a.example:80"]
        manager.proxies = list(manager.healthy_proxies)
        manager.validation_results = {
            "http://a.example:80": ProxyValidationResult("passed", status=200),
        }
        manager.get_next_proxy()
        validate = AsyncMock(return_value=ProxyValidationResult("passed", status=200))

        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=[
                 "a.example:80", "b.example:81",
             ]):
            replacement = await manager.rotate_proxy("http://a.example:80")

        self.assertEqual(replacement, "http://b.example:81")
        self.assertEqual(validate.await_count, 1)
        self.assertEqual(manager.validation_results[replacement].outcome, "passed")

    async def test_candidate_attempt_limit_is_respected(self):
        manager = self.make_manager(["a.example:80", "b.example:81"])
        validate = AsyncMock(return_value=ProxyValidationResult("failed", "timeout"))
        with patch("src.scraper.proxies.PROXY_MAX_POOL_REFRESHES", 1), \
             patch("src.scraper.proxies.PROXY_MAX_VALIDATION_CANDIDATES", 2), \
             patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=["c.example:82", "d.example:83"]) as fetch:
            with self.assertRaises(ProxyAcquisitionError):
                await manager.get_healthy_proxies()

        self.assertEqual(validate.await_count, 2)
        self.assertEqual(fetch.call_count, 0)

    async def test_pool_refresh_limit_is_respected(self):
        manager = self.make_manager(["a.example:80", "b.example:81"])
        validate = AsyncMock(return_value=ProxyValidationResult("failed", "timeout"))
        with patch("src.scraper.proxies.PROXY_MAX_POOL_REFRESHES", 1), \
             patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=["c.example:82", "d.example:83"]) as fetch:
            with self.assertRaises(ProxyAcquisitionError):
                await manager.get_healthy_proxies()

        self.assertEqual(validate.await_count, 4)
        self.assertEqual(fetch.call_count, 1)

    async def test_invalid_candidates_are_rejected_and_budget_failure_is_clear(self):
        manager = self.make_manager(["not a proxy", "http://:0", "bad.example"])
        validate = AsyncMock(return_value=ProxyValidationResult("passed", status=200))

        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=[]):
            with self.assertRaisesRegex(ProxyAcquisitionError, "required 3 healthy proxies"):
                await manager.get_healthy_proxies()

        validate.assert_not_awaited()

    async def test_repeated_refresh_pool_stops_without_retesting_candidates(self):
        manager = self.make_manager(["a.example:80"])
        validate = AsyncMock(return_value=ProxyValidationResult("failed", "timeout"))
        with patch("src.scraper.proxies.PROXY_MAX_POOL_REFRESHES", 1), \
             patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", validate), \
             patch("src.scraper.proxies.fetch_proxies", return_value=["a.example:80"]) as fetch:
            with self.assertRaises(ProxyAcquisitionError):
                await manager.get_healthy_proxies(target_count=3)
        self.assertEqual(validate.await_count, 1)
        self.assertEqual(fetch.call_count, 1)

    async def test_api_failure_fails_cleanly_without_lowering_target(self):
        manager = self.make_manager([])
        with patch("src.scraper.proxies.async_playwright", FakePlaywrightContext), \
             patch("src.scraper.proxies.validate_proxy", new_callable=AsyncMock), \
             patch("src.scraper.proxies.fetch_proxies", return_value=[]):
            with self.assertRaisesRegex(ProxyAcquisitionError, "required 3 healthy proxies"):
                await manager.get_healthy_proxies()


if __name__ == "__main__":
    unittest.main()
