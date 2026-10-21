"""Export stored snapshots and prune expired raw HTML files."""

import csv
import re
from pathlib import Path

from src.config import (
    RENDERED_HTML_DIR,
    RAW_HTML_RETENTION_RUNS,
)
from src.storage.db import get_connection
from src.storage.queries import get_niche_snapshot


def export_niche_to_csv(
    niche_id,
    search_run_id,
    output_path,
):
    """
    Export one niche/search-run snapshot to a CSV file.

    Data is retrieved through get_niche_snapshot() so this
    function does not duplicate the storage-layer SQL logic.

    Args:
        niche_id: ID of the niche.
        search_run_id: ID of the search run.
        output_path: Destination path for the CSV file.

    Returns:
        Path to the created CSV file.
    """

    rows = get_niche_snapshot(
        niche_id=niche_id,
        search_run_id=search_run_id,
    )

    output_path = Path(output_path)

    # Create the parent directory if it does not exist.
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # If there is no data, create an empty CSV file.
    if not rows:
        output_path.touch()
        return output_path

    # Use the dictionary keys returned by get_niche_snapshot()
    # as the CSV columns.
    fieldnames = list(rows[0].keys())

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)

    return output_path


def cleanup_old_raw_html(niche_slug):
    """
    Delete raw HTML belonging to runs older than the
    RAW_HTML_RETENTION_RUNS most recent runs for a niche.

    Retention policy:
        RAW_HTML_RETENTION_RUNS = 5

    means the five newest runs are retained and all older
    run HTML files are deleted.

    Only raw HTML files are deleted.
    Database records are never modified.

    Expected directory structure:

        data/rendered_html/
        └── <niche_slug>/
            └── <keyword>/
                ├── <run_id>_page1.html
                ├── <run_id>_page2.html
                └── products/
                    ├── <run_id>_<asin>.html
                    └── ...

    Args:
        niche_slug: Slug/name of the niche whose raw HTML
                    should be cleaned.

    Returns:
        Number of deleted HTML files.
    """

    if RAW_HTML_RETENTION_RUNS < 1:
        raise ValueError(
            "RAW_HTML_RETENTION_RUNS must be at least 1."
        )

    niche_dir = RENDERED_HTML_DIR / niche_slug

    if not niche_dir.exists():
        return 0

    if not niche_dir.is_dir():
        raise NotADirectoryError(
            f"Raw HTML niche path is not a directory: {niche_dir}"
        )

    # --------------------------------------------------
    # Find the niche ID from the database.
    #
    # The project stores the canonical niche in the DB,
    # while the raw HTML is organized by niche directory.
    # --------------------------------------------------

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id
            FROM niches
            WHERE slug = ?
               OR name = ?
            LIMIT 1
            """,
            (
                niche_slug,
                niche_slug,
            ),
        )

        niche_row = cursor.fetchone()

        if niche_row is None:
            return 0

        niche_id = niche_row[0]

        # --------------------------------------------------
        # Get runs newest → oldest.
        #
        # run_timestamp determines chronological order.
        # id is the tie-breaker.
        # --------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM search_runs
            WHERE niche_id = ?
            ORDER BY
                run_timestamp DESC,
                id DESC
            """,
            (niche_id,),
        )

        run_ids = [
            row[0]
            for row in cursor.fetchall()
        ]

    finally:
        conn.close()

    # If the niche has no runs, there is nothing to clean.
    if not run_ids:
        return 0

    # --------------------------------------------------
    # Keep the N newest runs.
    # Everything after them is considered old.
    # --------------------------------------------------

    old_run_ids = set(
        run_ids[RAW_HTML_RETENTION_RUNS:]
    )

    if not old_run_ids:
        return 0

    deleted_count = 0

    # --------------------------------------------------
    # A raw HTML filename always begins with its run ID:
    #
    #   1_page1.html
    #   12_page2.html
    #   5_B08D6GDPQZ.html
    #
    # Extract only the numeric run ID at the beginning.
    # --------------------------------------------------

    run_id_pattern = re.compile(
        r"^(\d+)_"
    )

    # Search recursively so both:
    #
    #   niche/<keyword>/*.html
    #
    # and:
    #
    #   niche/<keyword>/products/*.html
    #
    # are handled.
    for html_file in niche_dir.rglob("*.html"):

        if not html_file.is_file():
            continue

        match = run_id_pattern.match(
            html_file.name
        )

        if match is None:
            # Ignore files that do not follow the project's
            # run-ID filename convention.
            continue

        file_run_id = int(match.group(1))

        if file_run_id not in old_run_ids:
            continue

        html_file.unlink()
        deleted_count += 1

    return deleted_count