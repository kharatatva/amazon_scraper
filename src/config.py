"""Central defaults for storage, scraping, proxy handling, and scoring."""

from pathlib import Path
import re

# ==================================================
# PROJECT PATHS
# ==================================================

# Project paths are rooted at this source checkout; storage and API modules use
# these defaults when no explicit database path is supplied.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"

LOG_DIR = PROJECT_ROOT / "data" / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)



# ==================================================
# Project Paths
# ==================================================


MIGRATIONS_DIR = PROJECT_ROOT / "migrations"

MIGRATION_PATTERN = re.compile(r"^(\d+)_.*\.sql$")

LOG_FILE = LOG_DIR / "scraper.log"

DB_FILE = DATA_DIR / "scraper_analysis.db"

RENDERED_HTML_DIR = DATA_DIR / "rendered_html"

# ==================================================
# SCRAPING LIMITS (page/product counts and concurrent browser tasks)
# Search and product-detail stages read these limits. The raw HTML retention
# count is consumed by src.storage.lifecycle.
# ==================================================

MAX_PAGES_TO_CRAWL = 10
MAX_DETAIL_PAGES_PER_RUN = 100
PRODUCT_PAGE_CONCURRENCY = 10
SEARCH_PAGE_CONCURRENCY = 7
RAW_HTML_RETENTION_RUNS = 5

# ==================================================
# CSS selector lists are tried in order by the search and product parsers.
# Keep fallback order intact: later selectors support alternate page layouts.
# ==================================================
FIELD_CONTAINER_SELECTORS = {
    "title": [
    "h2 span",    # conversion to text required
    "a.a-text-normal h2 span",   # conversion to text required
    "h2.a-size-medium span",    # conversion to text required
    "a.a-link-normal h2 span",   # conversion to text required
    "a.s-line-clamp-2 h2 span",   # conversion to text required
    ],
    "price": [
    "span.a-price span.a-offscreen",
    ".a-price .a-offscreen",
    "span.a-price-whole", # conversion to text required
    ".a-price-whole", # conversion to text required
    ],
    "rating": [
        'span.a-icon-alt', # conversion to text required
        ".a-icon-alt", # conversion to text required
        "[aria-label*='out of 5']", # conversion to text required         
    ],

    "review_count": [
        ".a-size-mini.s-underline-text", # conversion to text required 
        "[aria-label*='ratings']", # conversion to text required 
        'span.a-size-mini.s-underline-text', # conversion to text required
    ],

    'sponsored': [
        "span:contains('Sponsored')", # conversion to text required
        'a.puis-sponsored-label-text span', # conversion to text required
        ".puis-sponsored-label-text",
        'span[aria-label*="Sponsored"]', # conversion to text required
    ],  

    'amazons_choice': [
        "span.a-badge-text", # conversion to text required
        ".a-badge-text", # conversion to text required 
    ],

    "best_seller": [
        "span[aria-label*='Best Seller']", # conversion to text required
        "span.rio-badge-style-BEST_SELLER", # conversion to text required
        '.rio-badge-style-BEST_SELLER', # conversion to text required
    ],

    "thumbnail_url": [
    "img.s-image",
    "img[data-image-source-density]"
    ],

    "product_url": [
        "a.a-link-normal",
        "a.a-link-normal.s-line-clamp-2",
        'a[href*="/dp/"]'
    ],

    "brand":[
        "td.a-span9 span.a-size-base",
        "td.prodDetAttrValue",
        'tr[role="listitem"] td[role="presentation"] span',
        'tr:has(td span:-soup-contains("Brand")) td[role="presentation"] span'
    ],

    "seller_name":[
        "a[href*='/gp/help/seller-at-a-glance']",
        'div[id="merchantInfoFeature_div"] a[href*="seller/at-a-glance"]',
        'div.offer-display-feature-text-a-size-small a.a-size-small',
        '#merchantInfoFeature_div span.a-size-small a',
        "#sellerProfileTriggerId",
        "div[data-feature-name='merchantInfoFeature'] span.offer-display-feature-text-message a",
        "span.offer-display-feature-text-message a",
        "#merchantInfoFeature_div a"
    ],

    "fulfillment_type": [
    "span.a-size-small.offer-display-feature-text-message",
    "#fulfillerInfoFeature_feature_div span.offer-display-feature-text-message",
    "[data-csa-c-content-id='fulfiller-info'] span.a-size-small.offer-display-feature-text-message",
    ],

    "category_path": [
        "#wayfinding-breadcrumbs_feature_div ul.a-unordered-list.a-horizontal.a-size-small",
        "#wayfinding-breadcrumbs_feature_div ul.a-unordered-list",
        "#wayfinding-breadcrumbs_feature_div",
    ],

    "bsr": [
        "table.a-keyvalue.prodDetTable tr th.prodDetSectionEntry + td ul.a-unordered-list.a-nostyle.a-vertical",
        "table.prodDetTable tr th.prodDetSectionEntry + td ul.a-unordered-list",
        "table.prodDetTable td ul.a-unordered-list.a-vertical",
    ],

    "images": [
     "li.imageThumbnail",
    "li[class*='imageThumbnail']",  
    "#ivThumbs.ivThumbs",
    ],


    "bullet_points": [
       "#feature-bullets > ul.a-unordered-list.a-vertical",
       "#featurebullets_feature_div #feature-bullets ul.a-unordered-list",
       "[data-feature-name='featurebullets'] #feature-bullets ul",
    ],

    "a_plus": [
        "#aplus_feature_div",
        "div[data-feature-name='aplus']",
        "div[data-csa-c-content-id='aplus']"
    ],
    "variant_count" : [
        '[data-totalvariationcount]',
        '[aria-label*="There"][aria-label*="options"]',
        'div[id^="inline-twister-expander-content-"][data-totalvariationcount]',
    ],

    "weight_dimensions" : [
    "table.prodDetTable td.prodDetAttrValue",
    "table.prodDetTable tr:has(th.prodDetSectionEntry) td.prodDetAttrValue",
    """
        table.prodDetTable tr:has(th:-soup-contains("Item Dimensions")) td,
        table.prodDetTable tr:has(th:-soup-contains("Item Weight")) td
    """
    ]
}   
    

TILE_CONTAINER_SELECTORS = [
    'div[data-component-type="s-search-result"][data-asin]',
    'div.s-result-item[data-asin]',
    'div[data-asin]',
]

# ==================================================
# Fetch retry attempts and browser pacing defaults. MAX_RETRIES counts total
# fetch attempts (including the first); scroll delays are seconds and scroll
# amounts are pixels. src.scraper.fetch, browser, and pacing read these values.
# ==================================================

MAX_RETRIES = 3

MIN_SCROLL_DELAY = 1.0
MAX_SCROLL_DELAY = 5.0
MAX_SCROLLS = 40
MIN_SCROLL_AMOUNT = 2500
MAX_SCROLL_AMOUNT = 3000
# ==================================================
# Browser launch and locale defaults used by src.scraper.browser and manual
# browser diagnostics. VIEWPORT dimensions are CSS pixels.
# ==================================================

HEADLESS = False

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

VIEWPORT = {
    "width": 1920,
    "height": 1080,
}

LOCALE = "en-US"



TIMEZONE = "America/New_York"



# ==================================================
# Proxy acquisition and recovery settings used by src.scraper.proxies and
# browser validation. Timeouts are seconds unless the name ends in _MS;
# PROXY_COOLDOWN is seconds and PROXY_POOL_SIZE is candidate count.
# ==================================================

PROXY_TIMEOUT = 25  # HTTP request timeout, in seconds
PROXY_API_PROXY_TIMEOUT_MS = 15000  # ProxyScrape proxy-response filter, in milliseconds
PROXY_API_URL = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies"
    "&proxy_format=protocolipport"
    "&format=text"
    "&protocol=http"
    "&ssl=yes"
)

PROXY_POOL_SIZE = 60
PROXY_COOLDOWN = 300
# Minimum healthy count required; every passing candidate is retained.
PROXY_HEALTHY_TARGET = 3
# Startup only waits for this many validated proxies before scraping begins.
PROXY_MIN_HEALTHY_TO_START = 1
# Number of additional Proxy API refreshes after the initial pool fetch.
PROXY_MAX_POOL_REFRESHES = 3
# Every unique candidate in each fetched pool is validated.
PROXY_MAX_VALIDATION_CANDIDATES = PROXY_POOL_SIZE
# Keep proxy checks concurrent without flooding the browser or Amazon.
PROXY_VALIDATION_CONCURRENCY = 10
PROXY_VALIDATION_URL = "https://www.amazon.in/"
PROXY_VALIDATION_TIMEOUT_MS = 30000
PROXY_RECOVERY_ATTEMPTS = 3

# Quality-gap model weights and targets consumed by src.analysis.scoring.
# Weights are fractions; rating thresholds use the marketplace's 0–5 scale,
# while image and bullet targets are item counts.
# ---------------------------------------------------------------------------
# Quality gap looks for established products that still have weaknesses.
#
# Higher score -> more potentially beatable
# Lower score  -> stronger / harder to beat
#
# Review count is used as the "established product" signal.
# Rating measures customer-perceived product quality.
# Listing signals measure execution quality when Phase B data exists.

QUALITY_REVIEW_WEIGHT = 0.40
QUALITY_RATING_WEIGHT = 0.35
QUALITY_LISTING_WEIGHT = 0.25

# Rating band where the product is considered established enough to sell
# but still potentially beatable.
QUALITY_RATING_LOW = 3.3
QUALITY_RATING_HIGH = 4.2
QUALITY_RATING_IDEAL = 3.75

# Expected healthy listing levels.
QUALITY_TARGET_IMAGES = 7
QUALITY_TARGET_BULLETS = 5

# Demand scoring weights consumed by src.analysis.scoring. These are fractions
# of the demand score; review velocity is measured in reviews gained per day.
# ---------------------------------------------------------------------------
# Review count represents accumulated demand, so it receives the larger weight.
# These are model assumptions and can be changed later after validating
# the scoring model against real data.
REVIEW_COUNT_WEIGHT = 0.70
REVIEW_VELOCITY_WEIGHT = 0.30


# Competition scoring settings consumed by src.analysis.scoring. The top-N
# count determines how much of the niche's review share is treated as dominant.
# ---------------------------------------------------------------------------
# Number of dominant products used to measure review concentration.
TOP_COMPETITORS_COUNT = 3

# Final opportunity score weights used by scripts/run_scoring.py. Values are
# fractions and are renormalized across available signals when a metric is None.
# ==================================================

SCORE_WEIGHTS = {
    "demand": 0.4,
    "competition": 0.3,
    "quality_gap": 0.3,
}

