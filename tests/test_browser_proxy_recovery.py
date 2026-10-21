"""Offline tests for browser proxy recovery behavior."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.scraper.browser import (
    BrowserDisconnectedError,
    BrowserLifecycle,
    BrowserRecoveryError,
)
from src.scraper.fetch import (
    CaptchaDetectedError, classify_fetch_error, fetch_page,
    is_proxy_transport_error, redact_error,
)


class FakeResource:
    def __init__(self, options=None):
        self.closed = False
        self.connected = True
        self.options = options or {}
        self.contexts = []

    async def close(self):
        self.closed = True
        self.connected = False

    def is_connected(self):
        return self.connected

    async def new_page(self):
        return FakeResource()

    async def new_context(self, **kwargs):
        context = FakeResource(kwargs)
        self.contexts.append(context)
        return context


class FakeProxyManager:
    def __init__(self, replacement="http://proxy-2:8080", error=None):
        self.replacement = replacement
        self.error = error
        self.rotations = []
        self.cleared = []

    async def rotate_proxy(self, failed_proxy):
        self.rotations.append(failed_proxy)
        if self.error:
            raise self.error
        return self.replacement

    def clear_current_proxy(self, proxy):
        self.cleared.append(proxy)


class BrowserProxyRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def make_lifecycle(self, manager=None):
        manager = manager or FakeProxyManager()
        launched = []

        async def launch(_playwright, proxy):
            browser, context = FakeResource(), FakeResource()
            launched.append((proxy, browser, context))
            return browser, context

        lifecycle = BrowserLifecycle(
            object(),
            proxy="http://proxy-1:8080",
            browser_factory=launch,
            proxy_manager=manager,
            max_attempts=3,
        )
        await lifecycle.start()
        return lifecycle, manager, launched

    async def test_page_leases_share_one_proxy_context_and_release_independently(self):
        lifecycle, manager, launched = await self.make_lifecycle()
        leases = await asyncio.gather(*(lifecycle.lease() for _ in range(12)))

        self.assertEqual(len(launched), 1)
        self.assertEqual({lease.proxy for lease in leases}, {"http://proxy-1:8080"})
        self.assertEqual(len({id(lease.browser) for lease in leases}), 1)
        self.assertEqual(len({id(lease.context) for lease in leases}), 1)
        self.assertTrue(all(
            lease.context.options["proxy"]["server"] == "http://proxy-1:8080"
            for lease in leases
        ))
        self.assertEqual(manager.rotations, [])
        await lifecycle.release(leases[0])
        self.assertFalse(leases[0].context.closed)
        self.assertFalse(leases[1].context.closed)
        await lifecycle.close()
        self.assertTrue(all(lease.context.closed for lease in leases))

    async def test_concurrent_proxy_failures_rotate_once_without_closing_sibling_contexts(self):
        lifecycle, manager, launched = await self.make_lifecycle()
        failed_lease = await lifecycle.lease()

        replacements = await asyncio.gather(*[
            lifecycle.recover_proxy(failed_lease, RuntimeError("proxy tunnel failure"))
            for _ in range(12)
        ])

        self.assertEqual(manager.rotations, ["http://proxy-1:8080"])
        self.assertEqual([proxy for proxy, _, _ in launched], [None])
        self.assertFalse(failed_lease.retired)
        self.assertTrue(all(lease.generation == 0 for lease in replacements))
        self.assertEqual(len({id(lease.browser) for lease in replacements}), 1)
        self.assertEqual((await lifecycle.lease()).proxy, "http://proxy-2:8080")
        self.assertFalse(failed_lease.context.closed)
        replacement_lease = await lifecycle.lease()
        self.assertIsNot(replacement_lease.context, failed_lease.context)
        self.assertFalse(failed_lease.context.closed)
        await lifecycle.release(failed_lease)
        self.assertTrue(failed_lease.context.closed)
        await lifecycle.close()

    async def test_browser_disconnect_recovers_same_proxy_without_rotation(self):
        lifecycle, manager, launched = await self.make_lifecycle()
        failed_lease = await lifecycle.lease()
        failed_lease.browser.connected = False

        recovered = await lifecycle.recover(
            failed_lease,
            BrowserDisconnectedError("controlled browser disconnect"),
        )

        self.assertEqual(manager.rotations, [])
        self.assertEqual([proxy for proxy, _, _ in launched], [None, None])
        self.assertEqual(recovered.proxy, "http://proxy-1:8080")
        self.assertEqual(recovered.generation, 1)
        await lifecycle.close()

    async def test_exhausted_proxy_recovery_propagates_a_stage_failure(self):
        manager = FakeProxyManager(error=RuntimeError("no validated replacement"))
        lifecycle, _, _ = await self.make_lifecycle(manager)
        failed_lease = await lifecycle.lease()

        with self.assertRaisesRegex(BrowserRecoveryError, "Proxy recovery failed"):
            await lifecycle.recover_proxy(
                failed_lease,
                RuntimeError("confirmed proxy tunnel failure"),
            )
        with self.assertRaises(BrowserRecoveryError):
            await lifecycle.lease()
        await lifecycle.close()

    async def test_captcha_still_stops_fetch_without_proxy_rotation(self):
        class CaptchaPage:
            async def goto(self, *args, **kwargs):
                return None

            async def title(self):
                return "Robot Check"

            async def content(self):
                return "captcha challenge"

            async def close(self):
                pass

        class CaptchaContext:
            async def new_page(self):
                return CaptchaPage()

        with patch("src.scraper.fetch.log_scrape_error"):
            with self.assertRaises(CaptchaDetectedError):
                await fetch_page(
                    "https://www.amazon.in/",
                    CaptchaContext(),
                    run_id=1,
                )

    async def test_timeout_and_ambiguous_network_errors_do_not_classify_proxy_failed(self):
        self.assertEqual(classify_fetch_error(TimeoutError("slow navigation")), "navigation_timeout")
        self.assertFalse(is_proxy_transport_error(RuntimeError("net::ERR_CONNECTION_RESET")))
        self.assertFalse(is_proxy_transport_error(RuntimeError("net::ERR_CONNECTION_CLOSED")))
        self.assertTrue(is_proxy_transport_error(RuntimeError("net::ERR_TUNNEL_CONNECTION_FAILED")))
        self.assertNotIn("secret", redact_error("failed through https://user:secret@proxy.example:80"))

        class TimeoutPage:
            calls = 0

            async def goto(self, *args, **kwargs):
                self.calls += 1
                raise TimeoutError("Navigation timeout of 60000 ms exceeded")

            async def close(self):
                pass

        class TimeoutContext:
            def __init__(self):
                self.page = TimeoutPage()

            async def new_page(self):
                return self.page

        timeout_context = TimeoutContext()
        with patch("src.scraper.fetch.MAX_RETRIES", 2), \
             patch("src.scraper.fetch.asyncio.sleep", new_callable=AsyncMock), \
             patch("src.scraper.fetch.log_scrape_error") as log_error:
            result = await fetch_page(
                "https://www.amazon.in/", timeout_context, run_id=1,
            )
        self.assertIsNone(result)
        self.assertEqual(timeout_context.page.calls, 2)
        log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
