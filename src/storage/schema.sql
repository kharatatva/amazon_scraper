PRAGMA foreign_keys = ON;

-- ==================================================
-- Niches
-- ==================================================

CREATE TABLE IF NOT EXISTS niches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_scraped_at TEXT
);


-- ==================================================
-- Keywords
-- ==================================================

CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL UNIQUE
);


-- ==================================================
-- Sellers
-- ==================================================

CREATE TABLE IF NOT EXISTS sellers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL
);


-- ==================================================
-- Search Runs
-- ==================================================

CREATE TABLE search_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche_id INTEGER NOT NULL REFERENCES niches(id),
                keyword_id INTEGER REFERENCES keywords(id),
                run_timestamp TEXT NOT NULL,
                pages_scraped INTEGER DEFAULT 0,
                products_found INTEGER DEFAULT 0,
                status TEXT CHECK(status IN ('success','partial','failed','running')) NOT NULL,
                current_stage TEXT,
                current_task TEXT,
                notes TEXT,
                config_json TEXT
);

-- ==================================================
-- Products
-- ==================================================

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT NOT NULL UNIQUE,
    title TEXT,
    brand TEXT,
    seller_id INTEGER REFERENCES sellers(id),
    fulfillment_type TEXT CHECK(
        fulfillment_type IN ('FBA', 'FBM', 'Unknown')
    ),
    category_path TEXT,
    product_url TEXT,
    thumbnail_url TEXT,
    first_seen_at TEXT NOT NULL
);


-- ==================================================
-- Niche Products
-- ==================================================

CREATE TABLE IF NOT EXISTS niche_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche_id INTEGER NOT NULL REFERENCES niches(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    first_associated_at TEXT NOT NULL,
    UNIQUE(niche_id, product_id)
);


-- ==================================================
-- Snapshots
-- ==================================================

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    search_run_id INTEGER NOT NULL REFERENCES search_runs(id),
    parsed_at TEXT NOT NULL,

    price REAL,
    currency TEXT DEFAULT 'INR',

    rating REAL,
    review_count INTEGER,

    bsr_data TEXT,

    search_rank_position INTEGER,

    is_sponsored INTEGER DEFAULT 0,
    is_amazons_choice INTEGER DEFAULT 0,
    is_best_seller INTEGER DEFAULT 0,

    images_count INTEGER,
    bullet_points_count INTEGER,
    has_a_plus_content INTEGER DEFAULT 0,

    variant_count INTEGER,
    weight_and_dimensions TEXT,

    UNIQUE(product_id, search_run_id)
);


-- ==================================================
-- Opportunity Scores
-- ==================================================

CREATE TABLE IF NOT EXISTS opportunity_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    demand_score REAL,
    competition_score REAL,
    quality_gap_score REAL,
    final_score REAL,
    computed_at TEXT NOT NULL,
    demand_score_version INTEGER NOT NULL DEFAULT 0
);


-- ==================================================
-- Scrape Errors
-- ==================================================

CREATE TABLE IF NOT EXISTS scrape_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_run_id INTEGER REFERENCES search_runs(id),
    url TEXT,
    error_type TEXT,
    error_message TEXT,
    attempt_number INTEGER,
    occurred_at TEXT NOT NULL
);


-- ==================================================
-- Niche Keywords
-- ==================================================

CREATE TABLE IF NOT EXISTS niche_keywords (
    niche_id INTEGER NOT NULL REFERENCES niches(id),
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    PRIMARY KEY (niche_id, keyword_id)
);

-- ==================================================
-- Schema Migrations
-- ==================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);


-- ==================================================
-- Indexes
-- ==================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunity_scores_snapshot_id
ON opportunity_scores(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_snapshots_product
ON snapshots(product_id);

CREATE INDEX IF NOT EXISTS idx_snapshots_run
ON snapshots(search_run_id);

CREATE INDEX IF NOT EXISTS idx_niche_products_niche
ON niche_products(niche_id);

-- ==================================================
-- Scheduled Niches
-- ==================================================

CREATE TABLE IF NOT EXISTS scheduled_niches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    niche_id INTEGER NOT NULL
        REFERENCES niches(id),

    keyword_id INTEGER
        REFERENCES keywords(id),

    frequency TEXT NOT NULL
        CHECK (frequency IN ('daily', 'weekly')),

    is_active INTEGER NOT NULL DEFAULT 1,

    last_triggered_at TEXT,

    pages INTEGER NOT NULL DEFAULT 10,

    products INTEGER NOT NULL DEFAULT 100,

    run_times TEXT NOT NULL DEFAULT '08:00,20:00',

    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',

    last_slot_key TEXT,

    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_niches_active
ON scheduled_niches(is_active, id);

CREATE TABLE IF NOT EXISTS demand_backfill_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    total_runs INTEGER NOT NULL DEFAULT 0,
    processed_runs INTEGER NOT NULL DEFAULT 0,
    products_scored INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT
);
