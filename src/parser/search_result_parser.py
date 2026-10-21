"""Extract product candidates and metrics from search-page HTML."""

from bs4 import BeautifulSoup
from src.config import TILE_CONTAINER_SELECTORS, FIELD_CONTAINER_SELECTORS
from src.parser.selectors import select_all_tiles, select_first_match
from src.parser.normalize import (
    parse_price,
    parse_rating,
    parse_review_count,
    extract_asin,
    extract_asin_from_tile
)
def parse_search_results_page(html: str) -> list[dict]:
    """  Parses the HTML of a search results page and returns a list of dictionaries containing the relevant information for each search result.
    """
    soup = BeautifulSoup(html, 'html.parser')
    tiles= select_all_tiles(soup, TILE_CONTAINER_SELECTORS)
    results=[]
    seen_asin=set()
    for position, tile in enumerate(tiles,start=1):

        title_tag = select_first_match(tile, "title", FIELD_CONTAINER_SELECTORS["title"])
        price_tag = select_first_match(tile, "price", FIELD_CONTAINER_SELECTORS["price"])
        rating_tag = select_first_match(tile, "rating", FIELD_CONTAINER_SELECTORS["rating"])
        review_count_tag = select_first_match(tile, "review_count", FIELD_CONTAINER_SELECTORS["review_count"])
        is_sponsored_tag = select_first_match(tile, "sponsored", FIELD_CONTAINER_SELECTORS["sponsored"])
        is_amazons_choice=select_first_match(tile, "amazons_choice", FIELD_CONTAINER_SELECTORS["amazons_choice"])
        is_best_seller=select_first_match(tile, "best_seller", FIELD_CONTAINER_SELECTORS["best_seller"])
        search_rank_position = position 
        thumbnail_url_tag = select_first_match(tile, "thumbnail_url", FIELD_CONTAINER_SELECTORS["thumbnail_url"])
        product_url_tag = select_first_match(tile, "product_url", FIELD_CONTAINER_SELECTORS["product_url"])

        parsed_price=parse_price(price_tag.get_text(strip=True)) if price_tag else None
        parsed_rating=parse_rating(rating_tag.get_text(strip=True)) if rating_tag else None
        parsed_review_count=parse_review_count(review_count_tag.get_text(strip=True)) if review_count_tag else None
        parsed_title=title_tag.get_text(strip=True) if title_tag else None
        parsed_is_sponsored_tag=is_sponsored_tag is not None
        parsed_is_amazons_choice=is_amazons_choice is not None
        parsed_is_best_seller=is_best_seller is not None
        parsed_thumbnail_url=thumbnail_url_tag.get('src') if thumbnail_url_tag else None
        parsed_product_url="https://www.amazon.in" + product_url_tag.get('href') if product_url_tag else None
        parsed_asin = extract_asin_from_tile(tile)

        if parsed_asin is None:
            parsed_asin = extract_asin(parsed_product_url) if parsed_product_url else None
        if parsed_asin is None:
            continue
        if parsed_asin in seen_asin:
            continue

        seen_asin.add(parsed_asin)
        result = {
            "search_rank_position": search_rank_position,
            "asin": parsed_asin,
            "title": parsed_title,
            "price": parsed_price,
            "rating": parsed_rating,
            "review_count": parsed_review_count,
            "is_sponsored": parsed_is_sponsored_tag,
            "is_best_seller": parsed_is_best_seller,
            "is_amazons_choice": parsed_is_amazons_choice,
            "product_url": parsed_product_url,
            "thumbnail_url": parsed_thumbnail_url
        }
        results.append(result)
    return results