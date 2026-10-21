"""Provide human-like pauses and scrolling for browser sessions."""

from src.config import *
from src.logger import logger
import asyncio
import random
from playwright.async_api import Error as PlaywrightError

# async def human_scroll(page):
#     logger.info(
#         f"Starting human-like scrolling with delays between "
#         f"{MIN_SCROLL_DELAY} and {MAX_SCROLL_DELAY} seconds."
#     )
#     try:
#         for _ in range(MAX_SCROLLS):
#             # Remember current scroll position
#             previous_scroll = await page.evaluate("window.scrollY")


#             # Scroll by a random amount
#             scroll_amount = random.randint(300, 800)
#             await page.bring_to_front()
#             await page.mouse.move(random.randint(50, 300), random.randint(50, 300))
#             await page.evaluate(
#             "scroll_amount => window.scrollBy(0, scroll_amount)",
#             scroll_amount
#             )
        

#             # Give the browser a moment to apply the scroll
#             await page.wait_for_timeout(3000)

#             # Human-like pause
#             delay = random.uniform(MIN_SCROLL_DELAY, MAX_SCROLL_DELAY)
#             logger.info(
#                 f"Scrolled {scroll_amount}px. Waiting {delay:.2f}s..."
#             )
#             await asyncio.sleep(delay)

#             # Check the new scroll position
#             current_scroll = await page.evaluate("window.scrollY") 
#             logger.info(
#                 f"Previous: {previous_scroll} | Current: {current_scroll}"
#             )

#             # If we couldn't move any further, we're at the bottom
#             if current_scroll == previous_scroll:
#                 logger.info("Reached the bottom of the page.")
#                 break
#             if current_scroll > previous_scroll +scroll_amount+50:
#                 logger.info("Unexpected scroll behavior detected. Stopping.")
#                 break
#         else:
#             logger.info("Reached max scroll limit without hitting bottom.")
#     except PlaywrightError as e:
#         logger.error(f"Playwright error during scrolling: {e}")








async def human_scroll(page):
    """Scroll a page in short steps with human-like pauses."""
    logger.debug(
        f"Starting human-like scrolling with delays between "
        f"{MIN_SCROLL_DELAY} and {MAX_SCROLL_DELAY} seconds."
    )
    try:
        for _ in range(MAX_SCROLLS):
            previous_scroll = await page.evaluate("window.scrollY")

            scroll_amount = random.randint(MIN_SCROLL_AMOUNT, MAX_SCROLL_AMOUNT)
            await page.bring_to_front()
            await page.mouse.move(random.randint(50, 300), random.randint(50, 300))
            await page.evaluate(
                "scroll_amount => window.scrollBy(0, scroll_amount)",
                scroll_amount
            )

            await page.wait_for_timeout(3000)

            delay = random.uniform(MIN_SCROLL_DELAY, MAX_SCROLL_DELAY)
            logger.debug("Scrolled %spx; waiting %.2fs.", scroll_amount, delay)
            await asyncio.sleep(delay)

            current_scroll = await page.evaluate("window.scrollY")
            logger.debug("Scroll position: %s -> %s", previous_scroll, current_scroll)

            if current_scroll == previous_scroll:
                logger.debug("Reached the bottom of the page.")
                break
            if current_scroll > previous_scroll + scroll_amount + 50:
                logger.warning("Unexpected scroll behavior detected; stopping scroll.")
                return False
        else:
            logger.debug("Reached max scroll limit without hitting bottom.")
    except PlaywrightError as e:
        logger.error(f"Playwright error during scrolling: {e}")
