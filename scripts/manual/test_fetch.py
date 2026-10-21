"""Manual Playwright fetch diagnostic; it visits Amazon and is not an automated test."""
# Manual network script: run only when you intend to contact Amazon.

import asyncio
from src.config import *
from src.scraper.fetch import fetch_page
import asyncio
from playwright.async_api import async_playwright
# For playwright_stealth >= 2.0.0, use the following import format
from playwright_stealth import Stealth 
from src.config import *
from src.logger import logger
from src.scraper.pacing import human_scroll

async def test_fetch_page():

    """Manually fetch a live Amazon page using a local browser profile."""
    async with Stealth().use_async(async_playwright()) as p:

        context = await p.chromium.launch_persistent_context(
            user_data_dir="data/manual_browser_profile",
            headless=HEADLESS,
            user_agent=USER_AGENT,
            viewport=VIEWPORT,
            locale=LOCALE,
            timezone_id=TIMEZONE,
        )
        
        page = await fetch_page(
            # "https://this-domain-does-not-exist-123456789.com"
            'https://www.amazon.in/s?k=toys&page=11',
            context,
            6
        )

        if page:
            print("Fetch successful")
            await page.close()
        else:
            print("Fetch failed but scraper continued")

        await context.close()


if __name__ == "__main__":
    asyncio.run(test_fetch_page())