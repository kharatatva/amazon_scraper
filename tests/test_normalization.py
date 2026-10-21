"""Offline tests for text and identifier normalization helpers."""

from bs4 import BeautifulSoup

from src.parser.normalize import (
    extract_asin,
    extract_asin_from_tile,
    parse_bsr,
    parse_price,
    parse_rating,
    parse_review_count,
)


def test_numeric_normalizers_handle_valid_and_missing_values():
    assert parse_price("₹1,299") == 1299.0
    assert parse_price("$12.99 - $15.99") == 12.99
    assert parse_price("") is None
    assert parse_rating("4.5 out of 5 stars") == 4.5
    assert parse_rating("") is None
    assert parse_review_count("(1.4K)") == 1400
    assert parse_review_count("2M") == 2_000_000
    assert parse_review_count("") is None


def test_rank_and_asin_normalizers_parse_synthetic_values():
    assert parse_bsr("#1,234 in Kitchen") == (1234, "Kitchen")
    assert parse_bsr("") == (None, None)
    assert extract_asin("https://www.amazon.in/dp/B012345678") == "B012345678"
    tile = BeautifulSoup('<div data-asin="B012345678"></div>', "html.parser").div
    assert extract_asin_from_tile(tile) == "B012345678"
