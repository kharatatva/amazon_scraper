"""Offline search result parsing tests using synthetic fixture HTML."""

from pathlib import Path

from src.parser.search_result_parser import parse_search_results_page


def test_search_parser_returns_products_and_preserves_missing_values():
    html_path = Path(__file__).parent / "fixtures" / "search_results.html"
    results = parse_search_results_page(html_path.read_text(encoding="utf-8"))

    assert len(results) == 2
    assert results[0]["asin"] == "B012345678"
    assert results[0]["title"] == "Example travel mug"
    assert results[0]["price"] == 1299.0
    assert results[0]["rating"] == 4.5
    assert results[0]["review_count"] == 1400
    assert results[0]["is_sponsored"] is True
    assert results[0]["product_url"] == "https://www.amazon.in/dp/B012345678"
    assert results[1]["asin"] == "B098765432"
    assert results[1]["price"] is None
    assert results[1]["rating"] is None
