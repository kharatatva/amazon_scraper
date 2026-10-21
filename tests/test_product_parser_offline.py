"""Offline product detail parsing tests using synthetic fixture HTML."""

from pathlib import Path

from src.parser.product_detail_parser import parse_product_detail_page


def test_product_detail_parser_extracts_optional_listing_fields():
    html_path = Path(__file__).parent / "fixtures" / "product_detail.html"
    result = parse_product_detail_page(html_path.read_text(encoding="utf-8"))

    assert result["brand"] == "Example brand"
    assert result["fulfillment_type"] == "FBA"
    assert result["category_path"] == "Home Kitchen"
    assert result["bsr_data"] == [(12, "Kitchen")]
    assert result["images_count"] == 2
    assert result["bullet_points_count"] == 2
    assert result["has_a_plus_content"] is True
    assert result["variant_count"] == 3
    assert result["weight_and_dimensions"] == ["200 g", "10 x 5 x 3 cm"]
