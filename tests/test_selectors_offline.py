"""Offline selector tests against small hand-written HTML fixtures."""

from pathlib import Path

from bs4 import BeautifulSoup

from src.config import FIELD_CONTAINER_SELECTORS, TILE_CONTAINER_SELECTORS
from src.parser.selectors import select_all_tiles, select_first_match


FIXTURES = Path(__file__).parent / "fixtures"


def test_select_all_tiles_finds_fixture_products():
    soup = BeautifulSoup(
        (FIXTURES / "search_results.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    tiles = select_all_tiles(soup, TILE_CONTAINER_SELECTORS)

    assert [tile["data-asin"] for tile in tiles] == ["B012345678", "B098765432"]


def test_field_selectors_find_title_price_and_rating():
    soup = BeautifulSoup(
        (FIXTURES / "search_results.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    tile = select_all_tiles(soup, TILE_CONTAINER_SELECTORS)[0]

    title = select_first_match(tile, "title", FIELD_CONTAINER_SELECTORS["title"])
    price = select_first_match(tile, "price", FIELD_CONTAINER_SELECTORS["price"])
    rating = select_first_match(tile, "rating", FIELD_CONTAINER_SELECTORS["rating"])

    assert title.get_text(strip=True) == "Example travel mug"
    assert price.get_text(strip=True) == "₹1,299"
    assert rating.get_text(strip=True) == "4.5 out of 5 stars"
