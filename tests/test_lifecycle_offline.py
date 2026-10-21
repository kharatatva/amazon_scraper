"""CSV export and raw HTML retention tests using temporary paths."""

import csv

from src.storage import lifecycle


def test_export_niche_to_csv_writes_seeded_snapshot(temp_database, tmp_path):
    output_path = tmp_path / "exports" / "snapshot.csv"

    result = lifecycle.export_niche_to_csv(1, 1, output_path)

    with result.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert result == output_path
    assert len(rows) == 1
    assert rows[0]["asin"] == "B012345678"
    assert rows[0]["title"] == "Test product"


def test_cleanup_removes_only_files_for_runs_outside_retention_window(
    temp_database, tmp_path, monkeypatch
):
    niche_dir = tmp_path / "rendered_html" / "test-niche"
    keyword_dir = niche_dir / "test-keyword"
    products_dir = keyword_dir / "products"
    products_dir.mkdir(parents=True)
    monkeypatch.setattr(lifecycle, "RENDERED_HTML_DIR", tmp_path / "rendered_html")
    monkeypatch.setattr(lifecycle, "RAW_HTML_RETENTION_RUNS", 1)

    old_page = keyword_dir / "1_page1.html"
    middle_page = keyword_dir / "2_page1.html"
    old_product = products_dir / "2_B012345678.html"
    latest_page = keyword_dir / "3_page1.html"
    unrelated = keyword_dir / "notes.txt"
    for path in (old_page, middle_page, old_product, latest_page, unrelated):
        path.write_text("synthetic test data", encoding="utf-8")

    deleted = lifecycle.cleanup_old_raw_html("test-niche")

    assert deleted == 3
    assert not old_page.exists()
    assert not middle_page.exists()
    assert not old_product.exists()
    assert latest_page.exists()
    assert unrelated.exists()
