"""Normalize prices, ratings, review counts, ranks, and ASINs."""

import re

from bs4 import Tag
from src.logger import logger


def parse_price(raw: str) -> float | None:
    """
    Convert price strings like:
        "₹1,299"
        "$12.99 - $15.99"
    into float values.

    Returns None if parsing fails.
    """
    if not raw or not raw.strip():
        logger.debug("parse_price received empty optional input.")
        return None

    try:
        # Take lower bound if it's a range
        raw = raw.split("-")[0]

        # Keep only digits and decimal point
        cleaned = re.sub(r"[^\d.]", "", raw)

        if not cleaned:
            logger.warning(f"Unable to parse price from: {raw}")
            return None

        price = float(cleaned)
        logger.debug(f"Parsed price: {price}")
        return price

    except Exception as e:
        logger.error(f"parse_price failed: {e}")
        return None


def parse_rating(raw: str) -> float | None:
    """
    Convert:
        "4.5 out of 5 stars"
    into:
        4.5
    """
    if not raw or not raw.strip():
        logger.debug("parse_rating received empty optional input.")
        return None

    try:
        match = re.search(r"(\d+(?:\.\d+)?)", raw)

        if match:
            rating = float(match.group(1))
            logger.debug(f"Parsed rating: {rating}")
            return rating

        logger.warning(f"Unable to parse rating from: {raw}")
        return None

    except Exception as e:
        logger.error(f"parse_rating failed: {e}")
        return None



def parse_review_count(raw: str) -> int | None:
    """
    Convert:
        "1,234"  -> 1234
        "(114)"  -> 114
        "3.7K"   -> 3700
        "(1.4K)" -> 1400
        "2M"     -> 2000000
    """

    if not raw or not raw.strip():
        logger.debug("parse_review_count received empty optional input.")
        return None

    try:
        cleaned = raw.strip().replace(",", "")
        cleaned = cleaned.replace("(", "").replace(")", "")

        match = re.search(r"(\d+(?:\.\d+)?)([KM]?)", cleaned, re.IGNORECASE)

        if not match:
            logger.warning(f"Unable to parse review count from: {raw}")
            return None

        number = float(match.group(1))
        suffix = match.group(2).upper()

        if suffix == "K":
            number *= 1_000
        elif suffix == "M":
            number *= 1_000_000

        reviews = int(number)
        logger.debug(f"Parsed review count: {reviews}")
        return reviews

    except Exception as e:
        logger.error(f"parse_review_count failed: {e}")
        return None


def parse_bsr(raw: str) -> tuple[int | None, str | None]:
    """
    Convert:
        "#1,234 in Sports & Outdoors (See Top 100...)"

    into:
        (1234, "Sports & Outdoors")
    """
    if not raw or not raw.strip():
        logger.debug("parse_bsr received empty optional input.")
        return (None, None)

    try:
        match = re.search(
            r"([\d,]+)\s+in\s+([^\(\n]+)",
            raw
        )

        if not match:
            logger.warning(f"Unable to parse BSR from: {raw}")
            return (None, None)

        rank = int(match.group(1).replace(",", ""))
        category = match.group(2).strip()

        logger.debug(f"Parsed BSR: rank={rank}, category={category}")

        return (rank, category)

    except Exception as e:
        logger.error(f"parse_bsr failed: {e}")
        return (None, None)


def extract_asin(url_or_text: str) -> str | None:
    """
    Extract ASIN from:

    - https://amazon.in/dp/B0DXYZ123
    - https://amazon.in/gp/product/B0DXYZ123
    - Raw ASIN: B0DXYZ123
    """

    if not url_or_text or not url_or_text.strip():
        logger.warning("extract_asin received empty input.")
        return None

    try:
        url_or_text = url_or_text.strip()

        # Check if the input is already a valid ASIN
        match = re.fullmatch(
            r"[A-Z0-9]{10}",
            url_or_text,
            re.IGNORECASE
        )

        if match:
            asin = match.group(0).upper()
            logger.debug(f"Validated ASIN: {asin}")
            return asin

        # Otherwise, try extracting ASIN from an Amazon URL
        match = re.search(
            r"/(?:dp|gp/product)/([A-Z0-9]{10})\b",
            url_or_text,
            re.IGNORECASE
        )

        if match:
            asin = match.group(1).upper()
            logger.debug(f"Extracted ASIN: {asin}")
            return asin

        logger.warning(f"Unable to extract ASIN from: {url_or_text}")
        return None

    except Exception as e:
        logger.error(f"extract_asin failed: {e}")
        return None
    # Not added Into SELECTORS DUE TO SINGLE SELECTORS FOR PARSING AND EXTRACTION FROM PRODUCT URLS IN SEARCH RESULTS AND PRODUCT PAGES.
def extract_asin_from_tile(tile: Tag) -> str | None:
    """
    Extract the ASIN from a product tile's data-asin attribute.

    Example:
        <div data-asin="B0D7ZQS7Y6">
    """

    if tile is None:
        logger.warning("extract_asin_from_tile received None.")
        return None

    try:
        asin = tile.get("data-asin")

        if asin:
            asin = asin.strip().upper()

            if len(asin) == 10:
                logger.debug(f"Extracted ASIN from data-asin: {asin}")
                return asin

        logger.warning("No valid data-asin attribute found.")
        return None

    except Exception as e:
        logger.error(f"extract_asin_from_tile failed: {e}")
        return None
