"""Read-only, schema-aligned queries used by the NicheScope dashboard API."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.config import DB_FILE


def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path if db_path is not None else DB_FILE).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Configured SQLite database does not exist: {path}")
    uri = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _parse_json(value: Any) -> Any:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _category(value: Any) -> list[str]:
    parsed = _parse_json(value)
    if isinstance(parsed, list):
        return [str(part) for part in parsed if part not in (None, "")]
    if isinstance(parsed, str):
        value = parsed
    if not isinstance(value, str) or not value.strip():
        return []
    return [part.strip() for part in value.split(" > ") if part.strip()]


def _bsr(value: Any) -> Any:
    parsed = _parse_json(value)
    if isinstance(parsed, dict):
        # Existing parsers may store either a list or a single structured entry.
        parsed = [parsed]
    if not isinstance(parsed, list):
        return None
    entries: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            rank = item.get("rank")
            category = item.get("category")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            rank, category = item[0], item[1]
        else:
            continue
        try:
            rank_value = int(rank)
        except (TypeError, ValueError):
            continue
        if rank_value > 0 and isinstance(category, str) and category.strip():
            entries.append({"rank": rank_value, "category": category.strip()})
    return entries or None


PRODUCT_BASE = """
    SELECT p.id, p.asin, p.title, p.brand, p.seller_id,
           se.name AS seller_name, p.fulfillment_type, p.category_path,
           p.product_url, p.thumbnail_url, p.first_seen_at,
           sn.id AS snapshot_id, sn.search_run_id, sn.parsed_at,
           sn.price, sn.currency, sn.rating, sn.review_count, sn.bsr_data,
           sn.search_rank_position, sn.is_sponsored, sn.is_amazons_choice,
           sn.is_best_seller, sn.images_count, sn.bullet_points_count,
           sn.has_a_plus_content, sn.variant_count, sn.weight_and_dimensions,
           os.demand_score, os.competition_score, os.quality_gap_score,
           os.final_score, os.computed_at
      FROM products AS p
      LEFT JOIN sellers AS se ON se.id = p.seller_id
      LEFT JOIN snapshots AS sn ON sn.id = (
          SELECT sx.id FROM snapshots AS sx
           WHERE sx.product_id = p.id
           ORDER BY sx.parsed_at DESC, sx.id DESC LIMIT 1
      )
      LEFT JOIN opportunity_scores AS os ON os.snapshot_id = sn.id
"""


def _product_from_row(row: sqlite3.Row) -> dict[str, Any]:
    snapshot_id = row["snapshot_id"]
    current = None
    if snapshot_id is not None:
        current = {
            "id": snapshot_id,
            "product_id": row["id"],
            "search_run_id": row["search_run_id"],
            "parsed_at": row["parsed_at"],
            "price": row["price"],
            "currency": row["currency"],
            "rating": row["rating"],
            "review_count": row["review_count"],
            "bsr": _bsr(row["bsr_data"]),
            "search_rank_position": row["search_rank_position"],
            "is_sponsored": row["is_sponsored"],
            "is_amazons_choice": row["is_amazons_choice"],
            "is_best_seller": row["is_best_seller"],
            "images_count": row["images_count"],
            "bullet_points_count": row["bullet_points_count"],
            "has_a_plus_content": row["has_a_plus_content"],
            "variant_count": row["variant_count"],
            "weight_and_dimensions": row["weight_and_dimensions"],
            "opportunity": None,
        }
        if row["computed_at"] is not None:
            current["opportunity"] = {
                "snapshot_id": snapshot_id,
                "demand_score": row["demand_score"],
                "competition_score": row["competition_score"],
                "quality_gap_score": row["quality_gap_score"],
                "final_score": row["final_score"],
                "computed_at": row["computed_at"],
            }
    return {
        "id": row["id"],
        "asin": row["asin"],
        "title": row["title"],
        "brand": row["brand"],
        "seller_id": row["seller_id"],
        "seller_name": row["seller_name"],
        "fulfillment_type": row["fulfillment_type"],
        "category_path": _category(row["category_path"]),
        "product_url": row["product_url"],
        "thumbnail_url": row["thumbnail_url"],
        "first_seen_at": row["first_seen_at"],
        "current": current,
    }


def _attach_niches(conn: sqlite3.Connection, products: list[dict[str, Any]]) -> None:
    if not products:
        return
    ids = [product["id"] for product in products]
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT np.product_id, n.id, n.name
              FROM niche_products AS np JOIN niches AS n ON n.id = np.niche_id
             WHERE np.product_id IN ({marks}) ORDER BY n.name, n.id""",
        ids,
    ).fetchall()
    by_product: dict[int, list[dict[str, Any]]] = {item: [] for item in ids}
    for row in rows:
        by_product[row["product_id"]].append({"id": row["id"], "name": row["name"]})
    for product in products:
        product["niches"] = by_product[product["id"]]


def dashboard_summary() -> dict[str, Any]:
    """Aggregate counts and recent run status for the dashboard overview."""
    with closing(_connect()) as conn:
        counts = conn.execute(
            """SELECT
                (SELECT COUNT(*) FROM niches) AS niches,
                (SELECT COUNT(*) FROM products) AS products,
                (SELECT COUNT(*) FROM sellers) AS sellers,
                (SELECT COUNT(*) FROM search_runs) AS search_runs,
                (SELECT COUNT(*) FROM search_runs WHERE status='success') AS successful_runs,
                (SELECT COUNT(*) FROM search_runs WHERE status='partial') AS partial_runs,
                (SELECT COUNT(*) FROM search_runs WHERE status='failed') AS failed_runs,
                (SELECT COUNT(*) FROM search_runs WHERE status='running') AS running_runs,
                (SELECT COUNT(*) FROM snapshots) AS snapshots,
                (SELECT COUNT(DISTINCT sn.product_id)
                   FROM snapshots AS sn JOIN opportunity_scores AS os
                     ON os.snapshot_id = sn.id) AS scored_products"""
        ).fetchone()
        runs_by_day = [dict(row) for row in conn.execute(
            """SELECT date(run_timestamp) AS date, COUNT(*) AS count
                 FROM search_runs GROUP BY date(run_timestamp)
                ORDER BY date(run_timestamp)"""
        )]
        status = [dict(row) for row in conn.execute(
            "SELECT status AS label, COUNT(*) AS count FROM search_runs GROUP BY status ORDER BY status"
        )]
        niche_products = [dict(row) for row in conn.execute(
            """SELECT n.id, n.name AS label, COUNT(DISTINCT np.product_id) AS count
                 FROM niches AS n LEFT JOIN niche_products AS np ON np.niche_id=n.id
                GROUP BY n.id, n.name ORDER BY count DESC, n.name, n.id"""
        )]
        latest = """WITH ranked AS (
              SELECT s.*, ROW_NUMBER() OVER(PARTITION BY product_id ORDER BY parsed_at DESC, id DESC) AS rn
                FROM snapshots AS s
            ) SELECT r.*, os.final_score FROM ranked AS r
               LEFT JOIN opportunity_scores AS os ON os.snapshot_id=r.id WHERE r.rn=1"""
        price_distribution = [dict(row) for row in conn.execute(
            f"""SELECT COALESCE(currency,'Unknown') AS currency,
                       CAST(price / 25 AS INTEGER) * 25 AS bucket, COUNT(*) AS count
                  FROM ({latest}) WHERE price IS NOT NULL
                 GROUP BY currency, bucket ORDER BY currency, bucket"""
        )]
        rating_distribution = [dict(row) for row in conn.execute(
            f"""SELECT CAST(rating * 2 AS INTEGER) / 2.0 AS bucket, COUNT(*) AS count
                  FROM ({latest}) WHERE rating IS NOT NULL
                 GROUP BY bucket ORDER BY bucket"""
        )]
        score_distribution = [dict(row) for row in conn.execute(
            f"""SELECT CAST(final_score / 10 AS INTEGER) * 10 AS bucket, COUNT(*) AS count
                  FROM ({latest}) WHERE final_score IS NOT NULL
                 GROUP BY bucket ORDER BY bucket"""
        )]
        recent_runs = [dict(row) for row in conn.execute(
            """SELECT sr.id, sr.niche_id, n.name AS niche_name, sr.keyword_id,
                      k.text AS keyword, sr.run_timestamp, sr.pages_scraped,
                      sr.products_found, sr.status, sr.current_stage, sr.current_task,
                      sr.notes, (SELECT COUNT(*) FROM scrape_errors e WHERE e.search_run_id=sr.id) AS error_count
                 FROM search_runs sr JOIN niches n ON n.id=sr.niche_id
                 LEFT JOIN keywords k ON k.id=sr.keyword_id
                ORDER BY sr.run_timestamp DESC, sr.id DESC LIMIT 10"""
        )]
        rankings = conn.execute(
            """WITH ranked AS (
                   SELECT s.product_id,s.id,ROW_NUMBER() OVER(PARTITION BY s.product_id ORDER BY s.parsed_at DESC,s.id DESC) AS rn
                     FROM snapshots s
               ) SELECT p.id,p.asin,p.title,p.brand,os.final_score
                   FROM products p JOIN ranked r ON r.product_id=p.id AND r.rn=1
                   JOIN opportunity_scores os ON os.snapshot_id=r.id
                  ORDER BY os.final_score DESC,p.id LIMIT 8"""
        ).fetchall()
        return {
            "totals": dict(counts),
            "runs_by_day": runs_by_day,
            "run_status": status,
            "products_by_niche": niche_products,
            "price_distribution": price_distribution,
            "rating_distribution": rating_distribution,
            "score_distribution": score_distribution,
            "top_opportunities": [dict(row) for row in rankings],
            "recent_runs": recent_runs,
        }


def list_niches(search: str | None = None, keyword_id: int | None = None) -> list[dict[str, Any]]:
    """List niches with matching keywords, runs, and product totals."""
    clauses: list[str] = []
    params: list[Any] = []
    if search:
        clauses.append("(n.name LIKE ? ESCAPE '\\' OR n.slug LIKE ? ESCAPE '\\')")
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.extend([f"%{escaped}%", f"%{escaped}%"])
    if keyword_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM niche_keywords nk WHERE nk.niche_id=n.id AND nk.keyword_id=?)")
        params.append(keyword_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"""SELECT n.id, n.name, n.slug, n.created_at, n.last_scraped_at,
                      (SELECT COUNT(*) FROM niche_keywords nk WHERE nk.niche_id=n.id) AS keyword_count,
                      (SELECT COUNT(DISTINCT np.product_id) FROM niche_products np WHERE np.niche_id=n.id) AS product_count,
                      (SELECT COUNT(DISTINCT p.seller_id) FROM niche_products np JOIN products p ON p.id=np.product_id
                        WHERE np.niche_id=n.id AND p.seller_id IS NOT NULL) AS seller_count
                 FROM niches n {where} ORDER BY n.name, n.id""",
            params,
        ).fetchall()
        result = [dict(row) for row in rows]
        if result:
            marks = ",".join("?" for _ in result)
            keyword_rows = conn.execute(
                f"""SELECT nk.niche_id, k.id, k.text FROM niche_keywords nk
                      JOIN keywords k ON k.id=nk.keyword_id WHERE nk.niche_id IN ({marks})
                     ORDER BY k.text, k.id""", [row["id"] for row in result]
            ).fetchall()
            by_id: dict[int, list[dict[str, Any]]] = {row["id"]: [] for row in result}
            for row in keyword_rows:
                by_id[row["niche_id"]].append({"id": row["id"], "text": row["text"]})
            for niche in result:
                niche["keywords"] = by_id[niche["id"]]
        return result


def get_niche(niche_id: int) -> dict[str, Any] | None:
    """Return one niche and its related keyword and run information."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id,name,slug,created_at,last_scraped_at FROM niches WHERE id=?", (niche_id,)
        ).fetchone()
        if row is None:
            return None
        niche = dict(row)
        niche["keywords"] = [dict(item) for item in conn.execute(
            """SELECT k.id,k.text FROM niche_keywords nk JOIN keywords k ON k.id=nk.keyword_id
                WHERE nk.niche_id=? ORDER BY k.text,k.id""", (niche_id,)
        )]
        niche["product_count"] = conn.execute(
            "SELECT COUNT(DISTINCT product_id) FROM niche_products WHERE niche_id=?", (niche_id,)
        ).fetchone()[0]
        niche["run_count"] = conn.execute(
            "SELECT COUNT(*) FROM search_runs WHERE niche_id=?", (niche_id,)
        ).fetchone()[0]
        return niche


def _product_filters(
    *, search: str | None, niche_id: int | None, keyword_id: int | None,
    seller_id: int | None, brand: str | None, fulfillment_type: str | None,
    currency: str | None,
    price_min: float | None, price_max: float | None, rating_min: float | None,
    reviews_min: int | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if search:
        clauses.append("(p.asin LIKE ? OR p.title LIKE ? OR p.brand LIKE ? OR se.name LIKE ?)")
        like = f"%{search.strip()}%"
        params.extend([like] * 4)
    if niche_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM niche_products np WHERE np.product_id=p.id AND np.niche_id=?)")
        params.append(niche_id)
    if keyword_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM niche_products np JOIN niche_keywords nk ON nk.niche_id=np.niche_id WHERE np.product_id=p.id AND nk.keyword_id=?" + (" AND np.niche_id=?" if niche_id is not None else "") + ")")
        params.append(keyword_id)
        if niche_id is not None:
            params.append(niche_id)
    if seller_id is not None:
        clauses.append("p.seller_id=?")
        params.append(seller_id)
    if brand:
        clauses.append("p.brand=?")
        params.append(brand)
    if fulfillment_type:
        clauses.append("p.fulfillment_type=?")
        params.append(fulfillment_type)
    if currency:
        if currency == "Unknown":
            clauses.append("sn.currency IS NULL")
        else:
            clauses.append("sn.currency=?")
            params.append(currency)
    for col, op, value in (("sn.price", ">=", price_min), ("sn.price", "<=", price_max),
                           ("sn.rating", ">=", rating_min), ("sn.review_count", ">=", reviews_min)):
        if value is not None:
            clauses.append(f"{col} {op} ?")
            params.append(value)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", params)


def list_products(
    *, page: int = 1, page_size: int = 50, search: str | None = None,
    niche_id: int | None = None, keyword_id: int | None = None,
    seller_id: int | None = None, brand: str | None = None,
    fulfillment_type: str | None = None, currency: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None, rating_min: float | None = None,
    reviews_min: int | None = None, sort: str = "first_seen_at", order: str = "desc",
) -> dict[str, Any]:
    """Return a filtered and paginated product listing."""
    sort_columns = {
        "first_seen_at": "p.first_seen_at", "title": "p.title", "asin": "p.asin",
        "price": "sn.price", "rating": "sn.rating", "review_count": "sn.review_count",
        "search_rank_position": "sn.search_rank_position", "final_score": "os.final_score",
    }
    sort_col = sort_columns[sort]
    direction = "ASC" if order == "asc" else "DESC"
    product_base = PRODUCT_BASE
    snapshot_scope_params: list[Any] = []
    snapshot_scope: list[str] = []
    if niche_id is not None:
        snapshot_scope.append("EXISTS (SELECT 1 FROM search_runs scope_run WHERE scope_run.id=sx.search_run_id AND scope_run.niche_id=?)")
        snapshot_scope_params.append(niche_id)
    if keyword_id is not None:
        snapshot_scope.append("EXISTS (SELECT 1 FROM search_runs scope_run WHERE scope_run.id=sx.search_run_id AND scope_run.keyword_id=?)")
        snapshot_scope_params.append(keyword_id)
    if snapshot_scope:
        product_base = product_base.replace(
            "WHERE sx.product_id = p.id",
            "WHERE sx.product_id = p.id AND " + " AND ".join(snapshot_scope),
        )
    where, params = _product_filters(
        search=search, niche_id=niche_id, keyword_id=keyword_id, seller_id=seller_id,
        brand=brand, fulfillment_type=fulfillment_type, currency=currency, price_min=price_min,
        price_max=price_max, rating_min=rating_min, reviews_min=reviews_min,
    )
    with closing(_connect()) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM ({product_base} {where}) AS filtered_products",
            [*snapshot_scope_params, *params],
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"{product_base} {where} ORDER BY ({sort_col} IS NULL) ASC, {sort_col} {direction}, p.id ASC LIMIT ? OFFSET ?",
            [*snapshot_scope_params, *params, page_size, offset],
        ).fetchall()
        products = [_product_from_row(row) for row in rows]
        _attach_niches(conn, products)
        return {"items": products, "total": total, "page": page, "page_size": page_size}


def get_product(product_id: int) -> dict[str, Any] | None:
    """Return one product with its current snapshot and opportunity score."""
    with closing(_connect()) as conn:
        row = conn.execute(f"{PRODUCT_BASE} WHERE p.id=?", (product_id,)).fetchone()
        if row is None:
            return None
        product = _product_from_row(row)
        _attach_niches(conn, [product])
        return product


def run_opportunities(niche_id: int, run_id: int) -> list[dict[str, Any]]:
    """List opportunity scores for products in a selected run."""
    with closing(_connect()) as conn:
        run = conn.execute("SELECT id FROM search_runs WHERE id=? AND niche_id=?", (run_id, niche_id)).fetchone()
        if run is None:
            return []
        rows = conn.execute(
            """SELECT p.id,p.asin,p.title,p.brand,p.seller_id,se.name AS seller_name,
                      p.fulfillment_type,p.category_path,p.product_url,p.thumbnail_url,p.first_seen_at,
                      sn.id AS snapshot_id,sn.search_run_id,sn.parsed_at,sn.price,sn.currency,sn.rating,
                      sn.review_count,sn.bsr_data,sn.search_rank_position,sn.is_sponsored,
                      sn.is_amazons_choice,sn.is_best_seller,sn.images_count,sn.bullet_points_count,
                      sn.has_a_plus_content,sn.variant_count,sn.weight_and_dimensions,
                      os.demand_score,os.competition_score,os.quality_gap_score,os.final_score,os.computed_at
                 FROM niche_products np JOIN products p ON p.id=np.product_id
                 JOIN snapshots sn ON sn.product_id=p.id AND sn.search_run_id=?
                 LEFT JOIN sellers se ON se.id=p.seller_id
                 LEFT JOIN opportunity_scores os ON os.snapshot_id=sn.id
                WHERE np.niche_id=?
                ORDER BY (os.final_score IS NULL),os.final_score DESC,p.id""", (run_id, niche_id)
        ).fetchall()
        products = [_product_from_row(row) for row in rows]
        _attach_niches(conn, products)
        return products


def product_history(product_id: int, *, niche_id: int | None = None, start_date: str | None = None,
                    end_date: str | None = None) -> list[dict[str, Any]]:
    """Return a product?s snapshots in chronological order."""
    clauses = ["sn.product_id=?"]
    params: list[Any] = [product_id]
    if niche_id is not None:
        clauses.extend(["sr.niche_id=?", "EXISTS (SELECT 1 FROM niche_products np WHERE np.product_id=sn.product_id AND np.niche_id=sr.niche_id)"])
        params.append(niche_id)
    if start_date:
        clauses.append("date(sn.parsed_at)>=date(?)")
        params.append(start_date)
    if end_date:
        clauses.append("date(sn.parsed_at)<=date(?)")
        params.append(end_date)
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"""SELECT sn.id,sn.product_id,sn.search_run_id,sn.parsed_at,sr.niche_id,n.name AS niche_name,
                       sr.run_timestamp,sn.price,sn.currency,sn.rating,sn.review_count,sn.bsr_data,
                       sn.search_rank_position,sn.is_sponsored,sn.is_amazons_choice,sn.is_best_seller,
                       sn.images_count,sn.bullet_points_count,sn.has_a_plus_content,sn.variant_count,
                       sn.weight_and_dimensions,os.demand_score,os.competition_score,os.quality_gap_score,
                       os.final_score,os.computed_at
                  FROM snapshots sn JOIN search_runs sr ON sr.id=sn.search_run_id
                  JOIN niches n ON n.id=sr.niche_id
                  LEFT JOIN opportunity_scores os ON os.snapshot_id=sn.id
                 WHERE {' AND '.join(clauses)} ORDER BY sn.parsed_at,sn.id""", params
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["bsr"] = _bsr(item.pop("bsr_data"))
            item["opportunity"] = None
            if item["computed_at"] is not None:
                item["opportunity"] = {
                    "snapshot_id": item["id"], "demand_score": item["demand_score"],
                    "competition_score": item["competition_score"], "quality_gap_score": item["quality_gap_score"],
                    "final_score": item["final_score"], "computed_at": item["computed_at"],
                }
            result.append(item)
        return result


def _list_runs_conn(conn: sqlite3.Connection, *, niche_id: int | None = None,
                    keyword_id: int | None = None, status: str | None = None,
                    start_date: str | None = None, end_date: str | None = None,
                    page: int = 1, page_size: int = 50) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    for col, value in (("sr.niche_id", niche_id), ("sr.keyword_id", keyword_id), ("sr.status", status)):
        if value is not None:
            clauses.append(f"{col}=?")
            params.append(value)
    if start_date:
        clauses.append("date(sr.run_timestamp)>=date(?)")
        params.append(start_date)
    if end_date:
        clauses.append("date(sr.run_timestamp)<=date(?)")
        params.append(end_date)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM search_runs sr {where}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT sr.id,sr.niche_id,n.name AS niche_name,sr.keyword_id,k.text AS keyword,
                  sr.run_timestamp,sr.pages_scraped,sr.products_found,sr.status,
                  sr.current_stage,sr.current_task,sr.notes,
                  (SELECT COUNT(*) FROM scrape_errors e WHERE e.search_run_id=sr.id) AS error_count
             FROM search_runs sr JOIN niches n ON n.id=sr.niche_id
             LEFT JOIN keywords k ON k.id=sr.keyword_id {where}
            ORDER BY sr.run_timestamp DESC,sr.id DESC LIMIT ? OFFSET ?""",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def list_runs(**filters: Any) -> dict[str, Any]:
    """List search runs matching the supplied filters."""
    with closing(_connect()) as conn:
        return _list_runs_conn(conn, **filters)


def get_run(run_id: int) -> dict[str, Any] | None:
    """Return one run together with its errors and counters."""
    with closing(_connect()) as conn:
        # Fetch the selected run independently to keep its errors at one-to-many cardinality.
        row = conn.execute(
            """SELECT sr.id,sr.niche_id,n.name AS niche_name,sr.keyword_id,k.text AS keyword,
                      sr.run_timestamp,sr.pages_scraped,sr.products_found,sr.status,
                      sr.current_stage,sr.current_task,sr.notes
                 FROM search_runs sr JOIN niches n ON n.id=sr.niche_id
                 LEFT JOIN keywords k ON k.id=sr.keyword_id WHERE sr.id=?""", (run_id,)
        ).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["error_count"] = conn.execute("SELECT COUNT(*) FROM scrape_errors WHERE search_run_id=?", (run_id,)).fetchone()[0]
        run["errors"] = [dict(item) for item in conn.execute(
            "SELECT id,search_run_id,url,error_type,error_message,attempt_number,occurred_at FROM scrape_errors WHERE search_run_id=? ORDER BY occurred_at DESC,id DESC",
            (run_id,),
        )]
        return run


def list_errors(*, run_id: int | None = None, error_type: str | None = None,
                page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """List scrape errors with optional run and type filters."""
    clauses: list[str] = []
    params: list[Any] = []
    if run_id is not None:
        clauses.append("e.search_run_id=?")
        params.append(run_id)
    if error_type:
        clauses.append("e.error_type=?")
        params.append(error_type)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(_connect()) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM scrape_errors e {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT e.id,e.search_run_id,e.url,e.error_type,e.error_message,e.attempt_number,e.occurred_at,
                       sr.niche_id,n.name AS niche_name,k.text AS keyword
                  FROM scrape_errors e LEFT JOIN search_runs sr ON sr.id=e.search_run_id
                  LEFT JOIN niches n ON n.id=sr.niche_id LEFT JOIN keywords k ON k.id=sr.keyword_id
                  {where} ORDER BY e.occurred_at DESC,e.id DESC LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def list_schedules() -> list[dict[str, Any]]:
    """Return the configured niche schedules."""
    with closing(_connect()) as conn:
        return [dict(row) for row in conn.execute(
            """SELECT sn.id,sn.niche_id,n.name AS niche_name,sn.keyword_id,k.text AS keyword,
                      sn.frequency,sn.is_active,sn.pages,sn.products,sn.run_times,sn.timezone,
                      sn.last_triggered_at,sn.last_slot_key,sn.created_at
                 FROM scheduled_niches sn JOIN niches n ON n.id=sn.niche_id
                 JOIN keywords k ON k.id=sn.keyword_id ORDER BY sn.is_active DESC,n.name,k.text,sn.id"""
        )]


def demand_tracker(niche_id: int | None = None, *, page: int = 1, page_size: int = 100) -> dict[str, Any]:
    """Return latest demand scores and backfill status for products."""
    with closing(_connect()) as conn:
        niches = [dict(row) for row in conn.execute(
            """SELECT n.id,n.name,COUNT(DISTINCT np.product_id) AS product_count,
                      MAX(CASE WHEN sr.id IS NOT NULL THEN sn.parsed_at END) AS latest_observation
                 FROM niches n LEFT JOIN niche_products np ON np.niche_id=n.id
                 LEFT JOIN snapshots sn ON sn.product_id=np.product_id
                 LEFT JOIN search_runs sr ON sr.id=sn.search_run_id AND sr.niche_id=n.id
                GROUP BY n.id,n.name ORDER BY n.name,n.id"""
        )]
        selected_id = niche_id if niche_id is not None else (niches[0]["id"] if niches else None)
        if selected_id is None:
            return {"niches": niches, "selected_niche": None, "summary": None,
                    "items": [], "time_series": [], "page": page, "page_size": page_size, "total": 0}

        selected = next((item for item in niches if item["id"] == selected_id), None)
        if selected is None:
            return {"niches": niches, "selected_niche": None, "summary": None,
                    "items": [], "time_series": [], "page": page, "page_size": page_size, "total": 0}

        latest_cte = """WITH ranked AS (
            SELECT p.id AS product_id,p.asin,p.title,p.brand,sn.id AS snapshot_id,
                   sn.parsed_at,sn.review_count,sr.id AS search_run_id,
                   os.demand_score,os.computed_at,
                   SUM(CASE WHEN sn.review_count IS NOT NULL THEN 1 ELSE 0 END)
                     OVER (PARTITION BY p.id) AS review_observations,
                   ROW_NUMBER() OVER (PARTITION BY p.id ORDER BY sn.parsed_at DESC,sn.id DESC) AS row_num
              FROM niche_products np JOIN products p ON p.id=np.product_id
              JOIN snapshots sn ON sn.product_id=p.id
              JOIN search_runs sr ON sr.id=sn.search_run_id AND sr.niche_id=np.niche_id
              LEFT JOIN opportunity_scores os ON os.snapshot_id=sn.id
             WHERE np.niche_id=?
        )"""
        total = conn.execute(
            """SELECT COUNT(DISTINCT np.product_id) FROM niche_products np
                 WHERE np.niche_id=?""", (selected_id,)
        ).fetchone()[0]
        items = [dict(row) for row in conn.execute(
            latest_cte + """ SELECT product_id,asin,title,brand,snapshot_id,parsed_at,review_count,
                                  search_run_id,demand_score,computed_at,review_observations,
                                  CASE WHEN review_observations < 2 THEN 'Awaiting observations'
                                       WHEN demand_score IS NULL THEN 'No usable review history'
                                       ELSE 'Scored' END AS score_status
                             FROM ranked WHERE row_num=1
                            ORDER BY demand_score IS NULL ASC,demand_score DESC,review_count DESC,asin
                            LIMIT ? OFFSET ?""",
            (selected_id, page_size, (page - 1) * page_size),
        )]
        latest_rows = [dict(row) for row in conn.execute(
            latest_cte + """ SELECT SUM(CASE WHEN row_num=1 THEN 1 ELSE 0 END) AS products_with_snapshots,
                                  SUM(CASE WHEN row_num=1 AND demand_score IS NOT NULL THEN 1 ELSE 0 END) AS scored_products,
                                  MAX(CASE WHEN row_num=1 THEN parsed_at END) AS latest_observation
                             FROM ranked""", (selected_id,)
        )]
        summary = latest_rows[0] if latest_rows else {}
        summary["product_count"] = total
        summary["coverage_percent"] = round((summary.get("scored_products") or 0) * 100 / total, 1) if total else 0.0

        time_series = [dict(row) for row in conn.execute(
            """SELECT sr.id AS run_id,sr.run_timestamp AS label,
                      COUNT(DISTINCT sn.product_id) AS observed_products,
                      COUNT(DISTINCT CASE WHEN os.demand_score IS NOT NULL THEN sn.product_id END) AS scored_products,
                      AVG(os.demand_score) AS average_demand_score
                 FROM search_runs sr JOIN snapshots sn ON sn.search_run_id=sr.id
                 LEFT JOIN opportunity_scores os ON os.snapshot_id=sn.id
                WHERE sr.niche_id=? AND sr.status IN ('success','partial')
                GROUP BY sr.id,sr.run_timestamp ORDER BY sr.run_timestamp DESC,sr.id DESC LIMIT 60""",
            (selected_id,),
        )]
        time_series.reverse()
        return {"niches": niches, "selected_niche": selected, "summary": summary,
                "items": items, "time_series": time_series, "page": page,
                "page_size": page_size, "total": total}


def list_sellers(search: str | None = None, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """List sellers matching the search and pagination options."""
    clause = "WHERE se.name LIKE ?" if search else ""
    params: list[Any] = [f"%{search.strip()}%"] if search else []
    with closing(_connect()) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM sellers se {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT se.id,se.name,se.first_seen_at,
                       COUNT(DISTINCT p.id) AS product_count,
                       COUNT(DISTINCT np.niche_id) AS niche_count
                  FROM sellers se LEFT JOIN products p ON p.seller_id=se.id
                  LEFT JOIN niche_products np ON np.product_id=p.id {clause}
                 GROUP BY se.id,se.name,se.first_seen_at ORDER BY product_count DESC,se.name,se.id
                 LIMIT ? OFFSET ?""", [*params, page_size, (page-1)*page_size]
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def get_seller(seller_id: int, *, page: int = 1, page_size: int = 50) -> dict[str, Any] | None:
    """Return a seller and a page of its associated products."""
    with closing(_connect()) as conn:
        seller_row = conn.execute("SELECT id,name,first_seen_at FROM sellers WHERE id=?", (seller_id,)).fetchone()
        if seller_row is None:
            return None
        seller = dict(seller_row)
        seller["products"] = list_products(seller_id=seller_id, page=page, page_size=page_size)
        seller["product_count"] = seller["products"]["total"]
        return seller


def analytics(niche_id: int | None = None, start_date: str | None = None,
              end_date: str | None = None, limit: int = 5000,
              currency: str | None = None) -> dict[str, Any]:
    """Aggregate product, price, review, and score analytics."""
    clauses: list[str] = []
    params: list[Any] = []
    if niche_id is not None:
        clauses.extend(["sr.niche_id=?", "EXISTS (SELECT 1 FROM niche_products np WHERE np.product_id=sn.product_id AND np.niche_id=sr.niche_id)"])
        params.append(niche_id)
    if start_date:
        clauses.append("date(sn.parsed_at)>=date(?)")
        params.append(start_date)
    if end_date:
        clauses.append("date(sn.parsed_at)<=date(?)")
        params.append(end_date)
    if currency:
        if currency == "Unknown":
            clauses.append("sn.currency IS NULL")
        else:
            clauses.append("sn.currency=?")
            params.append(currency)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    latest_partition = "product_id,niche_id" if niche_id is not None else "product_id"
    cte = f"""WITH filtered AS (
            SELECT sn.id AS snapshot_id,sn.product_id,p.asin,p.title,p.brand,p.seller_id,se.name AS seller_name,
                   p.fulfillment_type,sn.search_run_id,sr.niche_id,n.name AS niche_name,
                   sn.parsed_at,sn.price,sn.currency,sn.rating,sn.review_count,sn.bsr_data,
                   sn.search_rank_position,sn.is_sponsored,sn.is_amazons_choice,sn.is_best_seller,
                   sn.images_count,sn.bullet_points_count,sn.has_a_plus_content,sn.variant_count,
                   os.demand_score,os.competition_score,os.quality_gap_score,os.final_score
              FROM snapshots sn JOIN products p ON p.id=sn.product_id
              JOIN search_runs sr ON sr.id=sn.search_run_id JOIN niches n ON n.id=sr.niche_id
              LEFT JOIN sellers se ON se.id=p.seller_id
              LEFT JOIN opportunity_scores os ON os.snapshot_id=sn.id
              {where}
        ), latest AS (
            SELECT filtered.*,ROW_NUMBER() OVER(PARTITION BY {latest_partition} ORDER BY parsed_at DESC,snapshot_id DESC) AS rn
              FROM filtered
        )"""
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"{cte} SELECT * FROM filtered ORDER BY parsed_at,snapshot_id LIMIT ?", [*params, limit + 1]
        ).fetchall()
        items = [dict(row) for row in rows[:limit]]
        for item in items:
            item["bsr"] = _bsr(item.pop("bsr_data"))
        totals = conn.execute(
            f"""{cte} SELECT COUNT(*) AS snapshots,COUNT(DISTINCT product_id) AS products,
                       COUNT(DISTINCT CASE WHEN final_score IS NOT NULL THEN product_id END) AS scored_products
                  FROM filtered""",
            params,
        ).fetchone()
        currencies = [row[0] for row in conn.execute(
            f"{cte} SELECT DISTINCT COALESCE(currency,'Unknown') FROM filtered WHERE price IS NOT NULL ORDER BY COALESCE(currency,'Unknown')", params
        )]
        time_series = [dict(row) for row in conn.execute(
            f"""{cte} SELECT date(parsed_at) AS label,COUNT(*) AS observations,
                       AVG(rating) AS avg_rating,
                       AVG(review_count) AS avg_review_count,AVG(search_rank_position) AS avg_search_rank,
                       AVG(final_score) AS avg_final_score
                  FROM filtered GROUP BY date(parsed_at) ORDER BY date(parsed_at)""", params
        )]
        price_time_series = [dict(row) for row in conn.execute(
            f"""{cte} SELECT date(parsed_at) AS label,currency,COUNT(price) AS price_observations,
                       AVG(price) AS avg_price FROM filtered WHERE price IS NOT NULL
                  GROUP BY date(parsed_at),currency ORDER BY date(parsed_at),currency""", params
        )]
        score_distributions: dict[str, list[dict[str, Any]]] = {}
        for key in ("demand_score", "competition_score", "quality_gap_score", "final_score"):
            score_distributions[key] = [
                {"label": f"{row['bucket']}–{row['bucket'] + 9}", "bucket": row["bucket"], "count": row["count"]}
                for row in conn.execute(
                    f"{cte} SELECT CAST({key}/10 AS INTEGER)*10 AS bucket,COUNT(*) AS count FROM filtered WHERE {key} IS NOT NULL GROUP BY bucket ORDER BY bucket",
                    params,
                )
            ]
        fulfillment = [dict(row) for row in conn.execute(
            f"{cte} SELECT COALESCE(fulfillment_type,'Unknown') AS label,COUNT(DISTINCT product_id) AS count FROM latest WHERE rn=1 GROUP BY fulfillment_type ORDER BY count DESC,label",
            params,
        )]
        brands = [dict(row) for row in conn.execute(
            f"{cte} SELECT COALESCE(brand,'Brand unavailable') AS label,COUNT(DISTINCT product_id) AS count FROM latest WHERE rn=1 GROUP BY brand ORDER BY count DESC,label LIMIT 25",
            params,
        )]
        sellers = [dict(row) for row in conn.execute(
            f"{cte} SELECT COALESCE(seller_name,'Seller unavailable') AS label,COUNT(DISTINCT product_id) AS count FROM latest WHERE rn=1 GROUP BY seller_name ORDER BY count DESC,label LIMIT 25",
            params,
        )]
        badges: list[dict[str, Any]] = []
        for column, label in (("is_sponsored", "Sponsored"), ("is_amazons_choice", "Amazon’s Choice"), ("is_best_seller", "Best Seller")):
            row = conn.execute(
                f"{cte} SELECT SUM(CASE WHEN {column}=1 THEN 1 ELSE 0 END) AS yes_count,SUM(CASE WHEN {column}=0 THEN 1 ELSE 0 END) AS no_count,SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END) AS unknown_count,COUNT(*) AS total FROM latest WHERE rn=1",
                params,
            ).fetchone()
            badges.append({"label": label, **dict(row)})
        image_quality = [dict(row) for row in conn.execute(
            f"{cte} SELECT images_count AS label,COUNT(*) AS count,AVG(rating) AS avg_rating,AVG(final_score) AS avg_final_score FROM latest WHERE rn=1 AND images_count IS NOT NULL GROUP BY images_count ORDER BY images_count LIMIT 25",
            params,
        )]
        bullet_quality = [dict(row) for row in conn.execute(
            f"{cte} SELECT bullet_points_count AS label,COUNT(*) AS count,AVG(rating) AS avg_rating,AVG(final_score) AS avg_final_score FROM latest WHERE rn=1 AND bullet_points_count IS NOT NULL GROUP BY bullet_points_count ORDER BY bullet_points_count LIMIT 25",
            params,
        )]
        rank_distribution = [dict(row) for row in conn.execute(
            f"{cte} SELECT CAST(search_rank_position/10 AS INTEGER)*10 AS bucket,COUNT(*) AS count FROM filtered WHERE search_rank_position IS NOT NULL GROUP BY bucket ORDER BY bucket LIMIT 50",
            params,
        )]
        price_distribution = [dict(row) for row in conn.execute(
            f"{cte} SELECT COALESCE(currency,'Unknown') AS currency,CAST(price/25 AS INTEGER)*25 AS bucket,COUNT(*) AS count FROM latest WHERE rn=1 AND price IS NOT NULL GROUP BY currency,bucket ORDER BY currency,bucket",
            params,
        )]
        rating_distribution = [dict(row) for row in conn.execute(
            f"{cte} SELECT CAST(rating*2 AS INTEGER)/2.0 AS bucket,COUNT(*) AS count FROM latest WHERE rn=1 AND rating IS NOT NULL GROUP BY bucket ORDER BY bucket",
            params,
        )]
        review_distribution = [dict(row) for row in conn.execute(
            f"""{cte} SELECT CASE
                       WHEN review_count < 10 THEN '0–9'
                       WHEN review_count < 100 THEN '10–99'
                       WHEN review_count < 1000 THEN '100–999'
                       WHEN review_count < 10000 THEN '1,000–9,999'
                       ELSE '10,000+'
                   END AS label,COUNT(*) AS count
                  FROM latest WHERE rn=1 AND review_count IS NOT NULL
                 GROUP BY label ORDER BY MIN(review_count)""", params
        )]
        bsr_distribution: dict[str, dict[str, Any]] = {}
        bsr_rows_source = conn.execute(
            f"{cte} SELECT bsr_data FROM filtered WHERE bsr_data IS NOT NULL", params
        )
        for source_row in bsr_rows_source:
            for entry in _bsr(source_row["bsr_data"]) or []:
                category = entry["category"]
                aggregate = bsr_distribution.setdefault(category, {"label": category, "count": 0, "rank_sum": 0, "min_rank": None, "max_rank": None})
                aggregate["count"] += 1
                aggregate["rank_sum"] += entry["rank"]
                aggregate["min_rank"] = entry["rank"] if aggregate["min_rank"] is None else min(aggregate["min_rank"], entry["rank"])
                aggregate["max_rank"] = entry["rank"] if aggregate["max_rank"] is None else max(aggregate["max_rank"], entry["rank"])
        bsr_rows = sorted(({
            **item, "avg_rank": item["rank_sum"] / item["count"]
        } for item in bsr_distribution.values()), key=lambda row: (row["avg_rank"], row["label"]))[:50]
        return {
            "items": items, "total_returned": totals["snapshots"], "unique_products": totals["products"],
            "scored_products": totals["scored_products"], "truncated": totals["snapshots"] > limit,
            "limit": limit, "currencies": currencies,
            "filters": {"niche_id": niche_id, "start_date": start_date, "end_date": end_date, "currency": currency},
            "time_series": time_series, "price_time_series": price_time_series,
            "score_distributions": score_distributions,
            "fulfillment_distribution": fulfillment, "products_by_brand": brands, "products_by_seller": sellers,
            "badges": badges, "images_vs_quality": image_quality, "bullets_vs_quality": bullet_quality,
            "search_rank_distribution": rank_distribution, "bsr_by_category": bsr_rows,
            "price_distribution": price_distribution, "rating_distribution": rating_distribution,
            "review_distribution": review_distribution,
        }


def available_filters() -> dict[str, Any]:
    """Return the filter values currently present in the database."""
    with closing(_connect()) as conn:
        return {
            "brands": [row[0] for row in conn.execute("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL ORDER BY brand")],
            "fulfillment_types": [row[0] for row in conn.execute("SELECT DISTINCT fulfillment_type FROM products WHERE fulfillment_type IS NOT NULL ORDER BY fulfillment_type")],
            "sellers": [dict(row) for row in conn.execute("SELECT id,name FROM sellers ORDER BY name,id")],
            "keywords": [dict(row) for row in conn.execute("SELECT id,text FROM keywords ORDER BY text,id")],
            "currencies": [row[0] for row in conn.execute(
                """WITH ranked AS (SELECT s.currency,s.price,ROW_NUMBER() OVER(PARTITION BY product_id ORDER BY parsed_at DESC,id DESC) AS rn FROM snapshots s)
                     SELECT DISTINCT COALESCE(currency,'Unknown') FROM ranked WHERE rn=1 AND price IS NOT NULL ORDER BY 1"""
            )],
        }
