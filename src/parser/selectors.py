"""Apply ordered CSS selector fallbacks to parsed HTML."""

from bs4 import BeautifulSoup, Tag
from src.logger import logger


def select_first_match(
    tile: Tag,
    field_name: str,
    selector_list: list[str]
) -> Tag | None:
    """
    Return the first matching element for a field within a product tile.
    """

    for index, selector in enumerate(selector_list):

        element = tile.select_one(selector)

        if element:

            if index > 0:
                logger.warning(
                    "Fallback field selector matched | Field: %s | Priority: %d | Selector: %s",
                    field_name,
                    index + 1,
                    selector
                )

            return element

    logger.warning(
        "No selector matched | Field: %s",
        field_name
    )

    return None


def select_all_tiles(
    page_soup: BeautifulSoup,
    selector_list: list[str]
) -> list[Tag]:
    """
    Return all product tiles using the first selector that matches at least one tile.
    """

    for index, selector in enumerate(selector_list):

        tiles = page_soup.select(selector)

        if tiles:

            if index > 0:
                logger.warning(
                    "Fallback tile selector matched | Priority: %d | Selector: %s",
                    index + 1,
                    selector
                )

            return tiles

    logger.warning(
        "No tile container selector matched."
    )

    return []
    ## Specifically created for brand tag because value exists at 1 of 2 different addresses 
    ## Brand can appear in multiple locations, so each candidate must be validated against its field label before extraction.
def extract_by_label(soup, field_names):
    """Read a value adjacent to one of the supplied field labels."""
    field_names = {
        name.strip().lower()
        for name in field_names
    }

    for element in soup.find_all(["th", "td", "span", "div", "dt", "li"]):
        text = element.get_text(" ", strip=True).lower()

        if text not in field_names:
            continue

        # Look for the associated value nearby
        parent = element.parent

        if not parent:
            continue

        siblings = parent.find_all(recursive=False)

        for sibling in siblings:
            if sibling is not element:
                value = sibling.get_text(" ", strip=True)

                if value:
                    return value

    return None