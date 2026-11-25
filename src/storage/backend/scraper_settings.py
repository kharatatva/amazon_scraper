"""Read and persist scraper and scoring controls managed by the dashboard."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from src import config

_settings_lock = threading.Lock()

_FIELDS: list[dict[str, Any]] = [
    {"key": "MAX_PAGES_TO_CRAWL", "label": "Maximum search pages", "group": "Scraping limits", "description": "Upper limit accepted for one scrape run.", "minimum": 1, "maximum": 100},
    {"key": "MAX_DETAIL_PAGES_PER_RUN", "label": "Maximum product pages", "group": "Scraping limits", "description": "Upper limit for product detail pages in one run.", "minimum": 1, "maximum": 10000},
    {"key": "PRODUCT_PAGE_CONCURRENCY", "label": "Product page concurrency", "group": "Scraping limits", "description": "Number of product detail tasks allowed at once.", "minimum": 1, "maximum": 100},
    {"key": "SEARCH_PAGE_CONCURRENCY", "label": "Search page concurrency", "group": "Scraping limits", "description": "Number of search page tasks allowed at once.", "minimum": 1, "maximum": 100},
    {"key": "RAW_HTML_RETENTION_RUNS", "label": "Raw HTML runs to keep", "group": "Scraping limits", "description": "Number of recent runs whose captured HTML is retained.", "minimum": 1, "maximum": 10000},
    {"key": "MAX_RETRIES", "label": "Fetch attempts", "group": "Browser and pacing", "description": "Total attempts per fetch, including the first attempt.", "minimum": 1, "maximum": 20},
    {"key": "MIN_SCROLL_DELAY", "label": "Minimum scroll delay", "group": "Browser and pacing", "description": "Minimum seconds to wait between browser scrolls.", "minimum": 0, "maximum": 120},
    {"key": "MAX_SCROLL_DELAY", "label": "Maximum scroll delay", "group": "Browser and pacing", "description": "Maximum seconds to wait between browser scrolls.", "minimum": 0, "maximum": 120},
    {"key": "MAX_SCROLLS", "label": "Maximum scrolls", "group": "Browser and pacing", "description": "Maximum scroll actions on a search page.", "minimum": 0, "maximum": 1000},
    {"key": "MIN_SCROLL_AMOUNT", "label": "Minimum scroll amount", "group": "Browser and pacing", "description": "Minimum scroll distance in pixels.", "minimum": 1, "maximum": 100000},
    {"key": "MAX_SCROLL_AMOUNT", "label": "Maximum scroll amount", "group": "Browser and pacing", "description": "Maximum scroll distance in pixels.", "minimum": 1, "maximum": 100000},
    {"key": "HEADLESS", "label": "Run browser headless", "group": "Browser and pacing", "description": "Hide the browser window while scraping.", "kind": "boolean"},
    {"key": "USER_AGENT", "label": "Browser user agent", "group": "Browser and pacing", "description": "User agent string sent by the browser.", "kind": "text"},
    {"key": "VIEWPORT", "label": "Browser viewport", "group": "Browser and pacing", "description": "Browser width and height in CSS pixels, as JSON.", "kind": "json"},
    {"key": "LOCALE", "label": "Browser locale", "group": "Browser and pacing", "description": "Locale passed to the browser context.", "kind": "text"},
    {"key": "TIMEZONE", "label": "Browser timezone", "group": "Browser and pacing", "description": "Timezone passed to the browser context.", "kind": "text"},
    {"key": "PROXY_TIMEOUT", "label": "Proxy request timeout", "group": "Proxy", "description": "Proxy acquisition request timeout in seconds.", "minimum": 1, "maximum": 300},
    {"key": "PROXY_API_PROXY_TIMEOUT_MS", "label": "Proxy API timeout", "group": "Proxy", "description": "ProxyScrape response filter timeout in milliseconds.", "minimum": 100, "maximum": 300000},
    {"key": "PROXY_API_URL", "label": "Proxy API URL", "group": "Proxy", "description": "Endpoint used to fetch proxy candidates.", "kind": "text"},
    {"key": "PROXY_POOL_SIZE", "label": "Proxy pool size", "group": "Proxy", "description": "Number of candidate proxies requested per pool.", "minimum": 1, "maximum": 10000},
    {"key": "PROXY_COOLDOWN", "label": "Proxy cooldown", "group": "Proxy", "description": "Seconds before a failed proxy can be retried.", "minimum": 0, "maximum": 86400},
    {"key": "PROXY_HEALTHY_TARGET", "label": "Healthy proxy target", "group": "Proxy", "description": "Number of healthy proxies to retain when available.", "minimum": 1, "maximum": 10000},
    {"key": "PROXY_MIN_HEALTHY_TO_START", "label": "Minimum proxies to start", "group": "Proxy", "description": "Healthy proxies required before a run can begin.", "minimum": 0, "maximum": 10000},
    {"key": "PROXY_MAX_POOL_REFRESHES", "label": "Pool refresh attempts", "group": "Proxy", "description": "Additional proxy API refreshes after the first request.", "minimum": 0, "maximum": 100},
    {"key": "PROXY_MAX_VALIDATION_CANDIDATES", "label": "Proxy candidates to validate", "group": "Proxy", "description": "Maximum unique candidates checked in each pool.", "minimum": 1, "maximum": 10000},
    {"key": "PROXY_VALIDATION_CONCURRENCY", "label": "Proxy validation concurrency", "group": "Proxy", "description": "Proxy health checks run concurrently.", "minimum": 1, "maximum": 200},
    {"key": "PROXY_VALIDATION_URL", "label": "Proxy validation URL", "group": "Proxy", "description": "Amazon URL used to check proxy health.", "kind": "text"},
    {"key": "PROXY_VALIDATION_TIMEOUT_MS", "label": "Proxy validation timeout", "group": "Proxy", "description": "Proxy health check timeout in milliseconds.", "minimum": 100, "maximum": 300000},
    {"key": "PROXY_RECOVERY_ATTEMPTS", "label": "Proxy recovery attempts", "group": "Proxy", "description": "Attempts to recover when a proxy fails during a run.", "minimum": 0, "maximum": 100},
    {"key": "FIELD_CONTAINER_SELECTORS", "label": "Field selectors", "group": "Parser selectors", "description": "CSS selector fallbacks tried for parsed product fields, as JSON.", "kind": "json"},
    {"key": "TILE_CONTAINER_SELECTORS", "label": "Search result selectors", "group": "Parser selectors", "description": "CSS selectors used to locate search result tiles, as JSON.", "kind": "json"},
    {"key": "QUALITY_REVIEW_WEIGHT", "label": "Review count weight", "group": "Scoring", "description": "Quality gap score weight for review count (0 to 1).", "minimum": 0, "maximum": 1, "step": 0.01},
    {"key": "QUALITY_RATING_WEIGHT", "label": "Rating weight", "group": "Scoring", "description": "Quality gap score weight for rating (0 to 1).", "minimum": 0, "maximum": 1, "step": 0.01},
    {"key": "QUALITY_LISTING_WEIGHT", "label": "Listing quality weight", "group": "Scoring", "description": "Quality gap score weight for listing signals (0 to 1).", "minimum": 0, "maximum": 1, "step": 0.01},
    {"key": "QUALITY_RATING_LOW", "label": "Low rating threshold", "group": "Scoring", "description": "Lower rating threshold for the quality gap model.", "minimum": 0, "maximum": 5, "step": 0.1},
    {"key": "QUALITY_RATING_HIGH", "label": "High rating threshold", "group": "Scoring", "description": "Upper rating threshold for the quality gap model.", "minimum": 0, "maximum": 5, "step": 0.1},
    {"key": "QUALITY_RATING_IDEAL", "label": "Ideal rating", "group": "Scoring", "description": "Rating target used by the quality gap model.", "minimum": 0, "maximum": 5, "step": 0.05},
    {"key": "QUALITY_TARGET_IMAGES", "label": "Target listing images", "group": "Scoring", "description": "Expected healthy number of product images.", "minimum": 0, "maximum": 100},
    {"key": "QUALITY_TARGET_BULLETS", "label": "Target listing bullets", "group": "Scoring", "description": "Expected healthy number of listing bullet points.", "minimum": 0, "maximum": 100},
    {"key": "REVIEW_COUNT_WEIGHT", "label": "Demand review count weight", "group": "Scoring", "description": "Demand score weight for accumulated reviews (0 to 1).", "minimum": 0, "maximum": 1, "step": 0.01},
    {"key": "REVIEW_VELOCITY_WEIGHT", "label": "Demand review velocity weight", "group": "Scoring", "description": "Demand score weight for reviews gained per day (0 to 1).", "minimum": 0, "maximum": 1, "step": 0.01},
    {"key": "TOP_COMPETITORS_COUNT", "label": "Dominant competitors", "group": "Scoring", "description": "Top products included in review concentration scoring.", "minimum": 1, "maximum": 100},
    {"key": "SCORE_WEIGHTS", "label": "Opportunity score weights", "group": "Scoring", "description": "Final demand, competition, and quality gap score weights, as JSON.", "kind": "json"},
]

_GROUPS = ["Scraping limits", "Browser and pacing", "Proxy", "Parser selectors", "Scoring"]
_SYSTEM_PATHS = {
    "PROJECT_ROOT": config.PROJECT_ROOT,
    "DATA_DIR": config.DATA_DIR,
    "LOG_DIR": config.LOG_DIR,
    "LOG_FILE": config.LOG_FILE,
    "DB_FILE": config.DB_FILE,
    "RENDERED_HTML_DIR": config.RENDERED_HTML_DIR,
    "MIGRATIONS_DIR": config.MIGRATIONS_DIR,
    "SCRAPER_SETTINGS_FILE": config.SCRAPER_SETTINGS_FILE,
}


def _make_schema() -> list[dict[str, Any]]:
    defaults = config.get_dashboard_setting_defaults()
    fields = []
    for field in _FIELDS:
        if field["key"] not in defaults:
            continue
        kind = field.get("kind")
        if kind is None:
            value = defaults[field["key"]]
            kind = "number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "text"
        fields.append({**field, "kind": kind, "default": defaults[field["key"]]})
    return fields


def get_scraper_settings() -> dict[str, Any]:
    """Return saved values, code defaults, editor metadata, and fixed paths."""
    defaults = config.get_dashboard_setting_defaults()
    field_keys = {field["key"] for field in _make_schema()}
    values = {key: deepcopy(getattr(config, key)) for key in field_keys}
    return {
        "settings": values,
        "defaults": {key: defaults[key] for key in field_keys},
        "groups": _GROUPS,
        "fields": _make_schema(),
        "system": {key: str(value) for key, value in _SYSTEM_PATHS.items()},
    }


def _normalize_like_default(value: Any, default: Any, key: str) -> Any:
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean.")
        return value
    if isinstance(default, int) and not isinstance(default, bool):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer.")
        return value
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number.")
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string.")
        if len(value) > 20000:
            raise ValueError(f"{key} is too long.")
        return value
    if isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a JSON array.")
        if default:
            return [_normalize_like_default(item, default[0], f"{key} item") for item in value]
        return value
    if isinstance(default, dict):
        if not isinstance(value, dict) or set(value) != set(default):
            raise ValueError(f"{key} must be a JSON object with keys: {', '.join(default)}.")
        return {
            child_key: _normalize_like_default(value[child_key], child_default, f"{key}.{child_key}")
            for child_key, child_default in default.items()
        }
    raise ValueError(f"{key} is not editable from the dashboard.")


def _validate_values(values: dict[str, Any]) -> dict[str, Any]:
    defaults = config.get_dashboard_setting_defaults()
    schema = _make_schema()
    known = {field["key"] for field in schema}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown scraper setting: {sorted(unknown)[0]}.")

    normalized = {key: deepcopy(getattr(config, key)) for key in known}
    for field in schema:
        key = field["key"]
        if key not in values:
            continue
        value = _normalize_like_default(values[key], defaults[key], key)
        minimum = field.get("minimum")
        maximum = field.get("maximum")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if minimum is not None and value < minimum:
                raise ValueError(f"{field['label']} must be at least {minimum}.")
            if maximum is not None and value > maximum:
                raise ValueError(f"{field['label']} must be at most {maximum}.")
        normalized[key] = value

    if normalized["MIN_SCROLL_DELAY"] > normalized["MAX_SCROLL_DELAY"]:
        raise ValueError("Minimum scroll delay cannot exceed maximum scroll delay.")
    if normalized["MIN_SCROLL_AMOUNT"] > normalized["MAX_SCROLL_AMOUNT"]:
        raise ValueError("Minimum scroll amount cannot exceed maximum scroll amount.")
    if not normalized["QUALITY_RATING_LOW"] <= normalized["QUALITY_RATING_IDEAL"] <= normalized["QUALITY_RATING_HIGH"]:
        raise ValueError("Ideal rating must be between the low and high rating thresholds.")
    if normalized["PROXY_MIN_HEALTHY_TO_START"] > normalized["PROXY_HEALTHY_TARGET"]:
        raise ValueError("Minimum proxies to start cannot exceed the healthy proxy target.")
    if normalized["VIEWPORT"]["width"] < 320 or normalized["VIEWPORT"]["height"] < 320:
        raise ValueError("Browser viewport width and height must each be at least 320 pixels.")

    for label, weights in (
        ("Quality gap", [normalized["QUALITY_REVIEW_WEIGHT"], normalized["QUALITY_RATING_WEIGHT"], normalized["QUALITY_LISTING_WEIGHT"]]),
        ("Demand", [normalized["REVIEW_COUNT_WEIGHT"], normalized["REVIEW_VELOCITY_WEIGHT"]]),
        ("Opportunity", list(normalized["SCORE_WEIGHTS"].values())),
    ):
        if not any(weight > 0 for weight in weights):
            raise ValueError(f"At least one {label.lower()} score weight must be greater than zero.")

    for key in ("PROXY_API_URL", "PROXY_VALIDATION_URL"):
        if not normalized[key].startswith(("https://", "http://")):
            raise ValueError(f"{key} must start with http:// or https://.")

    selectors = normalized["FIELD_CONTAINER_SELECTORS"]
    if not selectors or any(not name or not selectors[name] for name in selectors):
        raise ValueError("Field selectors must include at least one fallback for each field.")
    if not normalized["TILE_CONTAINER_SELECTORS"]:
        raise ValueError("At least one search result selector is required.")
    return normalized


def save_scraper_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically save settings for subsequent scraper runs."""
    if not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict):
        raise ValueError("A settings object is required.")
    with _settings_lock:
        values = _validate_values(payload["settings"])
        defaults = config.get_dashboard_setting_defaults()
        overrides = {key: value for key, value in values.items() if value != defaults[key]}
        settings_file: Path = config.SCRAPER_SETTINGS_FILE
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=settings_file.parent, delete=False) as temporary_file:
                json.dump(overrides, temporary_file, indent=2, ensure_ascii=False)
                temporary_file.write("\n")
                temporary_path = temporary_file.name
            os.replace(temporary_path, settings_file)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

        for key, value in values.items():
            setattr(config, key, deepcopy(value))
        # Modules that imported config values directly (such as the API's run
        # limit validator) also see the update immediately. Scraper processes
        # read the persisted file when each run starts.
        for module in tuple(sys.modules.values()):
            namespace = getattr(module, "__dict__", None)
            if not namespace or not str(namespace.get("__name__", "")).startswith("src."):
                continue
            for key, value in values.items():
                if key in namespace:
                    namespace[key] = deepcopy(value)
    return get_scraper_settings()


def reset_scraper_settings() -> dict[str, Any]:
    """Remove dashboard overrides and restore source-code defaults."""
    defaults = config.get_dashboard_setting_defaults()
    return save_scraper_settings({"settings": defaults})
