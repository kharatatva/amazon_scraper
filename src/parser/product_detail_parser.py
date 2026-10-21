"""Extract structured listing fields from product-page HTML."""

from bs4 import BeautifulSoup

from src.config import FIELD_CONTAINER_SELECTORS

from src.parser.selectors import select_first_match, select_all_tiles, extract_by_label

from src.parser.normalize import (
    parse_bsr,
)


def parse_product_detail_page(html: str) -> dict:
    """
    Parses the HTML of an Amazon product detail page and returns
    a dictionary containing the relevant product detail information.
    """

    soup = BeautifulSoup(html, "html.parser")

    # ---------------------------------------------------------
    # LOCATE RAW ELEMENTS
    # ---------------------------------------------------------

    brand_tag = extract_by_label(
        soup,
        ["brand", "brand name"],
        # FIELD_CONTAINER_SELECTORS["brand"]
    )

    seller_name_tag = extract_by_label(
        soup,
        ["sold by"],
        # FIELD_CONTAINER_SELECTORS["seller_name"]
    )

    fulfillment_type_tag = select_first_match(
        soup, "fulfillment_type", FIELD_CONTAINER_SELECTORS["fulfillment_type"]
    )

    category_path_tag = select_first_match(
        soup, "category_path", FIELD_CONTAINER_SELECTORS["category_path"]
    )

    bsr_tag = select_all_tiles(
        soup,
        # "bsr",
        FIELD_CONTAINER_SELECTORS["bsr"],
    )

    images_tag = select_all_tiles(
        soup,
        # "images",
        FIELD_CONTAINER_SELECTORS["images"],
    )

    bullet_points_tag = select_first_match(
        soup, "bullet_points", FIELD_CONTAINER_SELECTORS["bullet_points"]
    )

    a_plus_tag = select_first_match(
        soup, "a_plus_content", FIELD_CONTAINER_SELECTORS["a_plus"]
    )

    variants_tag = select_all_tiles(soup, FIELD_CONTAINER_SELECTORS["variant_count"])

    weight_dimensions_tag = select_all_tiles(
        soup,
        # "weight_and_dimensions",
        FIELD_CONTAINER_SELECTORS["weight_dimensions"],
    )

    # ---------------------------------------------------------
    # EXTRACT RAW VALUES
    # ---------------------------------------------------------

    brand = brand_tag.strip() if brand_tag and brand_tag.strip() else None

    seller_name = seller_name_tag.split("Sold by", 1)[1].strip() if seller_name_tag else None

    fulfillment_type = "Unknown"

    if fulfillment_type_tag:
        fulfillment_text = fulfillment_type_tag.get_text(" ", strip=True).lower()

        if "amazon" in fulfillment_text:
            fulfillment_type = "FBA"
        else:
            fulfillment_type = "FBM"
            
    category_path = (
        category_path_tag.get_text(" ", strip=True) if category_path_tag else None
    )
    # ---------------------------------------------------------
    # NORMALIZE VALUES THAT REQUIRE PARSING
    # ---------------------------------------------------------
    bsr = [
        parse_bsr(li.get_text(" ", strip=True))
        for b in bsr_tag
        for li in b.select("li")
    ]

    # ---------------------------------------------------------
    # COUNTS
    # ---------------------------------------------------------

    images_count = len(images_tag)

    if images_tag:
        last_tile_text = images_tag[-1].get_text(" ", strip=True)

        if "+" in last_tile_text:
            import re

            match = re.search(r"(\d+)\+", last_tile_text)

            if match:
                additional_images = int(match.group(1))

                # The "+" tile itself is not an image.
                images_count = (images_count - 1) + additional_images
    bullet_points_count = (
        len(bullet_points_tag.find_all("li")) if bullet_points_tag else 0
    )

    # ---------------------------------------------------------
    # BOOLEAN / OPTIONAL SECTIONS
    # ---------------------------------------------------------

    has_a_plus_content = (
        a_plus_tag is not None and a_plus_tag.select_one(".aplus-module") is not None
    )

    # ---------------------------------------------------------
    # VARIANTS
    # ---------------------------------------------------------

    variant_count = 1

    for variant in variants_tag:
        count = variant.get("data-totalvariationcount")

        if count:
            variant_count *= int(count)

    # ---------------------------------------------------------
    # WEIGHT / DIMENSIONS
    # ---------------------------------------------------------
    import re

    text = " ".join(tag.get_text(" ", strip=True) for tag in weight_dimensions_tag)

    dimension_pattern = r"""
    \b
    \d+(?:\.\d+)?
    \s*(?:D\s*)?
    x
    \s*\d+(?:\.\d+)?
    \s*(?:W\s*)?
    x
    \s*\d+(?:\.\d+)?
    \s*(?:H\s*)?
    (?:millimeters?|mm|
    centimeters?|cm|
    meters?|m|
    inches?|in|
    feet|ft)
    \b
    """

    weight_pattern = r"""
    \b
    \d+(?:\.\d+)?
    \s*
    (?:micrograms?|mcg|µg|
    milligrams?|mg|
    grams?|g|
    kilograms?|kg|
    ounces?|oz|
    pounds?|lbs?|lb)
    \b
    """

    dimension_match = re.search(dimension_pattern, text, re.IGNORECASE | re.VERBOSE)

    weight_match = re.search(weight_pattern, text, re.IGNORECASE | re.VERBOSE)

    weight_dimensions = [
        match.group(0).strip() for match in (weight_match, dimension_match) if match
    ][:2]

    # ---------------------------------------------------------
    # FINAL RESULT
    # ---------------------------------------------------------

    result = {
        "brand": brand,
        "seller_name": seller_name,
        "fulfillment_type": fulfillment_type,
        "category_path": category_path,
        "bsr_data": bsr,
        "images_count": images_count,
        "bullet_points_count": bullet_points_count,
        "has_a_plus_content": has_a_plus_content,
        "variant_count": variant_count,
        "weight_and_dimensions": weight_dimensions,
    }
    return result
