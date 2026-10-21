"""Offline tests for dashboard queries behavior."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.backend import dashboard_queries as dashboard


SCHEMA_FILE = PROJECT_ROOT / "src" / "storage" / "schema.sql"


class DashboardQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "dashboard-test.sqlite"
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.executescript(
            """
            INSERT INTO niches(id,name,slug,created_at,last_scraped_at) VALUES
                (1,'Coffee tools','coffee-tools','2024-01-01T00:00:00Z','2024-02-01T00:00:00Z'),
                (2,'Travel cups','travel-cups','2024-01-02T00:00:00Z',NULL);
            INSERT INTO keywords(id,text) VALUES (1,'coffee grinder'),(2,'travel mug');
            INSERT INTO sellers(id,name,first_seen_at) VALUES (1,'Seller One','2024-01-01T00:00:00Z');
            INSERT INTO niche_keywords(niche_id,keyword_id) VALUES (1,1),(2,2);
            INSERT INTO search_runs(id,niche_id,keyword_id,run_timestamp,pages_scraped,products_found,status,current_stage,current_task,notes)
                VALUES (1,1,1,'2024-01-01T10:00:00Z',2,2,'success','complete',NULL,'first run'),
                       (2,2,2,'2024-02-01T10:00:00Z',1,1,'running','details','ASIN B','in progress');
            INSERT INTO products(id,asin,title,brand,seller_id,fulfillment_type,category_path,product_url,thumbnail_url,first_seen_at)
                VALUES (1,'A000000001','Coffee mill','Brew Co',1,'FBA','["Home","Coffee"]','https://example.test/a',NULL,'2024-01-01T00:00:00Z'),
                       (2,'B000000002','Filter holder','Brew Co',NULL,NULL,'Kitchen > Coffee',NULL,NULL,'2024-01-02T00:00:00Z');
            INSERT INTO niche_products(niche_id,product_id,first_associated_at) VALUES
                (1,1,'2024-01-01T00:00:00Z'),(2,1,'2024-02-01T00:00:00Z'),(1,2,'2024-01-02T00:00:00Z');
            INSERT INTO snapshots(id,product_id,search_run_id,parsed_at,price,currency,rating,review_count,bsr_data,search_rank_position)
                VALUES (1,1,1,'2024-01-01T10:10:00Z',100,'INR',4.1,30,'[{"rank":12,"category":"Coffee"}]',4),
                       (2,1,2,'2024-02-01T10:10:00Z',150,'INR',4.3,45,'malformed-json',2),
                       (3,2,1,'2024-01-01T10:11:00Z',NULL,'INR',NULL,NULL,NULL,NULL);
            INSERT INTO opportunity_scores(id,snapshot_id,demand_score,competition_score,quality_gap_score,final_score,computed_at)
                VALUES (1,2,71,44,63,72,'2024-02-01T10:15:00Z');
            INSERT INTO scrape_errors(id,search_run_id,url,error_type,error_message,attempt_number,occurred_at) VALUES
                (1,2,'https://example.test/a','timeout','slow response',1,'2024-02-01T10:12:00Z'),
                (2,2,'https://example.test/b','parse','missing title',2,'2024-02-01T10:13:00Z');
            INSERT INTO scheduled_niches(id,niche_id,keyword_id,frequency,is_active,created_at)
                VALUES (1,2,2,'weekly',1,'2024-02-01T00:00:00Z');
            """
        )
        conn.commit()
        conn.close()
        self.original_db_file = dashboard.DB_FILE
        dashboard.DB_FILE = self.db_path

    def tearDown(self):
        dashboard.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_counts_and_relationships_do_not_multiply_rows(self):
        summary = dashboard.dashboard_summary()
        self.assertEqual(summary["totals"]["niches"], 2)
        self.assertEqual(summary["totals"]["products"], 2)
        self.assertEqual(summary["totals"]["snapshots"], 3)
        self.assertEqual(summary["totals"]["search_runs"], 2)
        self.assertEqual(summary["totals"]["running_runs"], 1)
        self.assertEqual(summary["totals"]["scored_products"], 1)
        niches = {niche["id"]: niche for niche in dashboard.list_niches()}
        self.assertEqual(niches[1]["product_count"], 2)
        self.assertEqual(niches[2]["product_count"], 1)
        self.assertEqual([item["text"] for item in niches[2]["keywords"]], ["travel mug"])
        self.assertEqual(dashboard.available_filters()["currencies"], ["INR"])
        market = dashboard.analytics(niche_id=1)
        self.assertEqual(market["total_returned"], 2)
        self.assertEqual(market["unique_products"], 2)
        self.assertEqual(market["bsr_by_category"][0]["label"], "Coffee")
        self.assertEqual(market["bsr_by_category"][0]["avg_rank"], 12)
        self.assertEqual(market["price_time_series"][0]["avg_price"], 100)
        self.assertEqual(dashboard.analytics()["score_distributions"]["final_score"][0]["bucket"], 70)

    def test_latest_snapshot_score_and_history_use_snapshot_ids(self):
        result = dashboard.list_products(page_size=10)
        product = next(item for item in result["items"] if item["id"] == 1)
        self.assertEqual(product["current"]["id"], 2)
        self.assertEqual(product["current"]["price"], 150)
        self.assertEqual(product["current"]["opportunity"]["snapshot_id"], 2)
        self.assertEqual(product["current"]["opportunity"]["final_score"], 72)
        self.assertIsNone(product["current"]["bsr"])
        history = dashboard.product_history(1)
        self.assertEqual([row["id"] for row in history], [1, 2])
        self.assertEqual(history[0]["bsr"], [{"rank": 12, "category": "Coffee"}])
        self.assertEqual([row["id"] for row in dashboard.product_history(1, niche_id=2)], [2])

    def test_niche_keyword_filters_runs_errors_and_schedules(self):
        niche_two_products = dashboard.list_products(niche_id=2)
        self.assertEqual(niche_two_products["total"], 1)
        self.assertEqual(niche_two_products["items"][0]["current"]["id"], 2)
        niche_one_product = next(item for item in dashboard.list_products(niche_id=1, page_size=10)["items"] if item["id"] == 1)
        self.assertEqual(niche_one_product["current"]["id"], 1)
        self.assertEqual(dashboard.list_products(niche_id=1, keyword_id=1)["total"], 2)
        self.assertEqual(dashboard.list_products(niche_id=2, keyword_id=1)["total"], 0)
        self.assertEqual(dashboard.list_products(currency="INR", price_min=140)["total"], 1)
        self.assertEqual(dashboard.list_products(currency="Unknown")["total"], 0)
        runs = dashboard.list_runs(status="running")
        self.assertEqual(runs["total"], 1)
        self.assertEqual(runs["items"][0]["error_count"], 2)
        self.assertEqual(len(dashboard.get_run(2)["errors"]), 2)
        self.assertEqual(dashboard.list_schedules()[0]["frequency"], "weekly")


if __name__ == "__main__":
    unittest.main()
