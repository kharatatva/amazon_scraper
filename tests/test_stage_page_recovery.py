"""Offline tests for stage page recovery behavior."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.scraper import product_detail, search
from src.scraper.fetch import CaptchaDetectedError, ProxyFailureError


class AsyncContextManager:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


class FakeStealth:
    def use_async(self, _playwright):
        return AsyncContextManager()


class FakeProxyManager:
    pool_initialized = True
    healthy_proxies = ["http://proxy-1:80", "http://proxy-2:80"]

    def __init__(self):
        self.current_proxy = None

    def set_current_proxy(self, proxy):
        self.current_proxy = proxy


class FakeLifecycle:
    def __init__(self, _playwright, proxy, **kwargs):
        self.proxy = proxy
        self.proxy_manager = kwargs.get("proxy_manager")
        self.lock = asyncio.Lock()

    async def start(self):
        return self

    async def lease(self, *, direct=False):
        return SimpleNamespace(
            proxy=None if direct else self.proxy,
            context=object(),
            browser=object(),
            retired=False,
        )

    async def recover(self, lease, _error):
        return lease

    async def recover_proxy(self, lease, _error):
        async with self.lock:
            if self.proxy == lease.proxy:
                self.proxy = "http://proxy-2:80"
                if self.proxy_manager is not None:
                    self.proxy_manager.current_proxy = self.proxy
        return await self.lease()

    async def release(self, _lease):
        pass

    async def close(self):
        pass


class FakePage:
    def __init__(self, html):
        self.html = html

    async def content(self):
        return self.html

    async def close(self):
        pass


class StagePageRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_preserves_successful_page_when_sibling_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = FakeProxyManager()
            calls = {1: 0, 2: 0}

            async def fake_fetch(url, *args, **kwargs):
                page_number = int(url.rsplit("=", 1)[-1])
                calls[page_number] += 1
                if page_number == 2:
                    raise RuntimeError("isolated page failure")
                return FakePage("saved page one")

            with patch.object(search, "RENDERED_HTML_DIR", root), \
                 patch.object(search, "Stealth", FakeStealth), \
                 patch.object(search, "async_playwright", return_value=object()), \
                 patch.object(search, "BrowserLifecycle", FakeLifecycle), \
                 patch.object(search, "get_or_create_keyword", return_value=1), \
                 patch.object(search, "get_or_create_niche", return_value=2), \
                 patch.object(search, "link_niche_keyword"), \
                 patch.object(search, "update_search_run"), \
                 patch.object(search, "fetch_page", side_effect=fake_fetch), \
                 patch.object(search.logger, "exception"):
                result = await search.fetch_search_results(
                    "test niche", "test keyword", 2,
                    proxy=manager.healthy_proxies[0], run_id=41,
                    proxy_manager=manager,
                )

            saved = root / "test-niche" / "test-keyword" / "41_page1.html"
            self.assertEqual(result, 41)
            self.assertEqual(saved.read_text(encoding="utf-8"), "saved page one")
            self.assertEqual(calls, {1: 1, 2: 1})

    async def test_search_retries_captcha_page_once_without_proxy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = FakeProxyManager()
            attempts = []

            async def fake_fetch(url, context=None, **kwargs):
                lease = kwargs["lease"]
                attempts.append((url, lease.proxy))
                if lease.proxy is not None:
                    raise CaptchaDetectedError("CAPTCHA challenge")
                return FakePage("saved direct retry")

            with patch.object(search, "RENDERED_HTML_DIR", root), \
                 patch.object(search, "Stealth", FakeStealth), \
                 patch.object(search, "async_playwright", return_value=object()), \
                 patch.object(search, "BrowserLifecycle", FakeLifecycle), \
                 patch.object(search, "get_or_create_keyword", return_value=1), \
                 patch.object(search, "get_or_create_niche", return_value=2), \
                 patch.object(search, "link_niche_keyword"), \
                 patch.object(search, "update_search_run"), \
                 patch.object(search, "fetch_page", side_effect=fake_fetch):
                result = await search.fetch_search_results(
                    "test niche", "test keyword", 1,
                    proxy=manager.healthy_proxies[0], run_id=42,
                    proxy_manager=manager,
                )

            saved = root / "test-niche" / "test-keyword" / "42_page1.html"
            self.assertEqual(result, 42)
            self.assertEqual(attempts, [
                ("https://www.amazon.in/s?k=test-keyword&page=1", manager.healthy_proxies[0]),
                ("https://www.amazon.in/s?k=test-keyword&page=1", None),
            ])
            self.assertEqual(saved.read_text(encoding="utf-8"), "saved direct retry")

    async def test_product_transport_failure_retries_only_affected_asin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = FakeProxyManager()
            calls = {"url-1": 0, "url-2": 0}

            async def fake_fetch(url, *args, **kwargs):
                calls[url] += 1
                if url == "url-2" and calls[url] == 1:
                    raise ProxyFailureError("confirmed tunnel failure")
                return FakePage(f"saved {url}")

            with patch.object(product_detail, "RENDERED_HTML_DIR", root), \
                 patch.object(product_detail, "Stealth", FakeStealth), \
                 patch.object(product_detail, "async_playwright", return_value=object()), \
                 patch.object(product_detail, "BrowserLifecycle", FakeLifecycle), \
                 patch.object(product_detail, "fetch_page", side_effect=fake_fetch):
                count = await product_detail.fetch_product_detail(
                    asin=["ASIN1", "ASIN2"],
                    product_url=["url-1", "url-2"],
                    niche_slug="test-niche",
                    keyword="test-keyword",
                    run_id=41,
                    proxy=manager.healthy_proxies[0],
                    proxy_manager=manager,
                )

            output = root / "test-niche" / "test-keyword" / "products"
            self.assertEqual(count, 2)
            self.assertEqual(calls, {"url-1": 1, "url-2": 2})
            self.assertEqual((output / "41_ASIN1.html").read_text(encoding="utf-8"), "saved url-1")
            self.assertEqual((output / "41_ASIN2.html").read_text(encoding="utf-8"), "saved url-2")

    async def test_product_retries_captcha_asin_once_without_proxy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = FakeProxyManager()
            attempts = []

            async def fake_fetch(url, _context, **kwargs):
                lease = kwargs["lease"]
                attempts.append((url, lease.proxy))
                if lease.proxy is not None:
                    raise CaptchaDetectedError("CAPTCHA challenge")
                return FakePage("saved direct retry")

            with patch.object(product_detail, "RENDERED_HTML_DIR", root), \
                 patch.object(product_detail, "Stealth", FakeStealth), \
                 patch.object(product_detail, "async_playwright", return_value=object()), \
                 patch.object(product_detail, "BrowserLifecycle", FakeLifecycle), \
                 patch.object(product_detail, "fetch_page", side_effect=fake_fetch):
                count = await product_detail.fetch_product_detail(
                    asin=["ASIN1"],
                    product_url=["url-1"],
                    niche_slug="test-niche",
                    keyword="test-keyword",
                    run_id=42,
                    proxy=manager.healthy_proxies[0],
                    proxy_manager=manager,
                )

            output = root / "test-niche" / "test-keyword" / "products" / "42_ASIN1.html"
            self.assertEqual(count, 1)
            self.assertEqual(attempts, [("url-1", manager.healthy_proxies[0]), ("url-1", None)])
            self.assertEqual(output.read_text(encoding="utf-8"), "saved direct retry")


if __name__ == "__main__":
    unittest.main()
