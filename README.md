<div align="center">

# NicheScope

**Find Amazon niches worth entering, using data instead of guesswork.**

Scrape Amazon India search results and product pages, store every observation as a time-stamped snapshot,<br>and rank opportunities with a transparent demand, competition and quality-gap score.

![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?style=flat-square&logo=playwright&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)
![React](https://img.shields.io/badge/React-20232A?style=flat-square&logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white)

[Quick start](#quick-start) &nbsp;·&nbsp; [Dashboard](#dashboard) &nbsp;·&nbsp; [How scoring works](#how-scoring-works) &nbsp;·&nbsp; [Data model](#data-model) &nbsp;·&nbsp; [Status](#project-status) &nbsp;·&nbsp; [Responsible use](#responsible-use)

<br>

<img src="docs/images/nichescope-banner.svg" alt="NicheScope pipeline: collect, store, score, explore" width="900">

</div>

<br>

## Overview

NicheScope answers one question for Amazon sellers and product researchers: **is this niche worth entering, and which products define it?**

A run takes a niche and a search keyword, collects the first pages of Amazon India results, visits a selected set of product pages, and stores everything as time-stamped snapshots in a local SQLite database. Each snapshot is then scored. Everything runs on your machine.

| Track | Compare | Decide |
| :--- | :--- | :--- |
| Every run is stored as snapshots, so price, rating, reviews and rank can be compared over time. | Niches, products and sellers share one data model. | A transparent score combines demand, competition and listing quality gaps. |

## Features

| Capability | Details |
| :--- | :--- |
| **Browser-based collection** | Playwright (with stealth patches) drives Chromium for search pages and product pages, with retries and rotating public proxies. |
| **Structured storage** | Products, sellers, keywords and snapshots in SQLite, managed with numbered migrations. |
| **Opportunity scoring** | Demand, competition and quality gap, combined into one score with configurable weights. |
| **Resumable pipeline** | Every run has a `search_run_id`, a status and a current stage, so progress and failures are traceable. |
| **FastAPI backend** | Dashboard read APIs plus a validated, queued execution API for the existing scraper pipeline. |
| **React dashboard** | A Vite and React interface backed by the local FastAPI and SQLite service. |

## How it works

```mermaid
flowchart TB
    subgraph collect ["1. Collect (Playwright)"]
        direction LR
        A["Search pages<br/>src/scraper/search.py"] --> B["Product pages<br/>src/scraper/product_detail.py"]
    end
    subgraph process ["2. Process and score"]
        direction LR
        C["Parse and normalize<br/>src/parser"] --> D[("SQLite snapshots<br/>src/storage")] --> E["Opportunity scoring<br/>src/analysis/scoring.py"]
    end
    subgraph serve ["3. Serve"]
        direction LR
        F["FastAPI<br/>src/storage/backend"] --> G["React dashboard<br/>nichescope-phase9"]
    end
    collect --> process --> serve
```

| # | Stage | What happens | Result |
| :-: | :--- | :--- | :--- |
| 1 | **Search pages** | Fetch up to 10 result pages for the keyword | Ranked product list and saved page HTML |
| 2 | **Product pages** | Visit up to `MAX_DETAIL_PAGES_PER_RUN` products for detail fields | Seller, rank, listing quality and more |
| 3 | **Parse** | Normalize prices, ratings, counts and ranks; de-duplicate ASINs across pages | Product and snapshot records |
| 4 | **Store** | Upsert into SQLite under one `search_run_id` | Rows in `products`, `snapshots` and related tables |
| 5 | **Score** | Compute demand, competition, quality gap and the final score | One row in `opportunity_scores` per snapshot |
| 6 | **Serve** | FastAPI exposes the data on localhost | JSON API |

> [!NOTE]
> Every run has a `search_run_id` that ties together its products, snapshots, scores and errors. Search-page HTML is kept under `data/rendered_html/` for local recovery and diagnostics. The newest `RAW_HTML_RETENTION_RUNS` runs are kept.

### What gets captured

| Source | Fields |
| :--- | :--- |
| **Search results** | ASIN, title, price, rating, review count, search rank position, Sponsored / Amazon's Choice / Best Seller flags, product URL, thumbnail |
| **Product pages** | Brand, seller, fulfillment type, category path, Best Sellers Rank (all listed categories), image count, bullet-point count, A+ content flag, variant count, weight and dimensions |
| **Derived** | Demand, competition, quality-gap and final opportunity scores for each snapshot |

## Quick start

| Requirement | Version |
| :--- | :--- |
| Python | 3.13 |
| Node.js | 20.19+ or 22.12+ (dashboard only; Vite 7) |
| pnpm | 10.4.1 (dashboard only) |
| Chromium | Installed or verified from the dashboard during first-run setup |

On Windows, install Python 3.13 and Node.js 20.19+ or 22.12+, then launch from the repository folder. In PowerShell, run `.\start-dashboard.bat` (or `Start-Process -FilePath "$PWD\start-dashboard.bat"` to open it separately); in Command Prompt, run `start "" "%CD%\start-dashboard.bat"`. The launcher creates the project virtual environment, installs missing Python or dashboard packages, starts the API and dashboard, and opens the browser. On first launch, use the dashboard setup screen to initialize SQLite and install or verify Playwright Chromium; later checks and repairs are available under **Settings → Environment Setup & Maintenance**. Existing database contents and valid scraper settings are preserved.

On macOS or Linux, run `bash start-dashboard.sh` after installing the same Python and Node.js versions. It performs the same local bootstrap and opens the dashboard when available.

> [!NOTE]
> The launchers are for local use. A live scrape sends requests to Amazon and fetches a public proxy list. The browser submits jobs to the local API; its worker runs the Python scraper.

**1. Launch the dashboard**

```powershell
git clone https://github.com/kharatatva/amazon_scraper.git
Set-Location amazon_scraper
.\start-dashboard.bat
```

<details>
<summary><b>macOS / Linux</b></summary>

```bash
git clone https://github.com/kharatatva/amazon_scraper.git
cd amazon_scraper
bash start-dashboard.sh
```

</details>

**2. Initialize in the dashboard**

On a fresh checkout, the API creates the local data folders, initializes SQLite, applies available migrations, and opens the first-run setup screen. Choose **Initialize environment** to install or verify Playwright Chromium and run the remaining readiness checks. No database or browser setup commands are required. To check or repair the environment later, open **Settings → Environment Setup & Maintenance**.

**3. Start a scrape**

Open **Scraper** in the dashboard, enter a niche and one or more Amazon search keywords, then select **Start scraping**. Each keyword is queued as a separate run and progress appears in the dashboard.

<details>
<summary><b>Run the Python pipeline manually</b></summary>

The launchers create `.venv` and install runtime packages. After activating that environment, you can still run the pipeline directly:

```powershell
python scripts/run_full_pipeline.py
```

The pipeline is interactive. It asks for three values:

| Prompt | Description |
| :--- | :--- |
| `Enter niche` | The niche you are researching, for example `desk accessories`. |
| `Enter keyword` | The Amazon search keyword, for example `desk organizer`. |
| `Enter number of pages to scrape` | Search pages to scrape. Values above `MAX_PAGES_TO_CRAWL` (10) are capped. |

How many product pages are visited is controlled by `MAX_DETAIL_PAGES_PER_RUN` in [`src/config.py`](src/config.py).

You can also run stages separately for an existing run:

```powershell
python scripts/run_parser.py <search_run_id>
python scripts/run_scoring.py
python scripts/verify_schema.py
```

</details>

## Dashboard

Start the API from the project root:

```powershell
python -m uvicorn src.storage.backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, start the frontend:

```powershell
Set-Location nichescope-phase9
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

Open the URL Vite prints (port `3000` is preferred; Vite picks the next free port if it is busy).

| Page | What you can do |
| :--- | :--- |
| **Overview** | See headline numbers across tracked niches |
| **Niches** | Follow a niche, its keywords and its latest runs |
| **Opportunities** | Rank products by opportunity score |
| **Products** | Browse products with price, rating, reviews and rank history |
| **Sellers** | See who sells in a niche and how many products they hold |
| **Analytics** | Compare signals across niches and products |
| **Scraper** | Create niches and keywords, queue the real pipeline, and monitor stored progress and logs |

> [!IMPORTANT]
> The dashboard reads the project SQLite database through FastAPI. Start both the API and Vite server as described above to browse stored results and launch scraper runs.

| Endpoint | Returns |
| :--- | :--- |
| `GET /api/niches` | All niches |
| `GET /api/niches/{niche_id}/runs` | Runs for a niche |
| `GET /api/niches/{niche_id}/runs/{search_run_id}/opportunities` | Ranked opportunities for a run |
| `GET /api/products/{product_id}` | Product detail |
| `GET /api/products/{product_id}/price-history` | Price history |
| `GET /api/products/{product_id}/rank-history?niche_id=` | Rank history within a niche |
| `POST /api/scrape/start` | Queue runs for one or more keywords under a niche |
| `GET /api/runs/{run_id}/logs` | Recent captured scraper output |

> [!WARNING]
> The API has no authentication. Keep it bound to `127.0.0.1`. Its CORS policy allows the local Vite origins `http://localhost:3000`, `http://127.0.0.1:3000` and `http://localhost:5173`.

## How scoring works

Every snapshot receives three signals and one overall score, each from 0 to 1 (higher means a more attractive opportunity). Signals are measured relative to the other products in the same niche run.

| Signal | What it tells you | How it is computed |
| :--- | :--- | :--- |
| **Demand** | How much attention the product already attracts | 70% min-max normalized review count and 30% normalized review velocity, both relative to the niche run. Velocity needs at least two dated observations. |
| **Competition** | How open the niche is to a newcomer | Measures how concentrated review counts are among the top `TOP_COMPETITORS_COUNT` (3) products of the niche run. Reviews spread more evenly give a higher score. |
| **Quality gap** | Room to out-execute established products | 40% review count (as the "established" signal), 35% rating (best near 3.75, inside a 3.3 to 4.2 band) and 25% listing quality (targets: 7 images, 5 bullet points). |
| **Opportunity** | The overall ranking score | A weighted blend of the three signals, shown below. |

```text
opportunity = 0.4 × demand + 0.3 × competition + 0.3 × quality_gap
```

> [!IMPORTANT]
> A missing signal is never counted as zero. When a signal is unavailable, for example velocity before a second run, it is omitted and the remaining weights are renormalized.

Review count feeds both Demand and Quality gap by design, so the signals are correlated. All weights and thresholds live in [`src/config.py`](src/config.py); the logic is in [`src/analysis/scoring.py`](src/analysis/scoring.py).

## Data model

```mermaid
erDiagram
    NICHES ||--o{ SEARCH_RUNS : runs
    KEYWORDS ||--o{ SEARCH_RUNS : searched_with
    NICHES }o--o{ KEYWORDS : niche_keywords
    NICHES }o--o{ PRODUCTS : niche_products
    NICHES ||--o{ SCHEDULED_NICHES : schedules
    KEYWORDS ||--o{ SCHEDULED_NICHES : uses
    SELLERS ||--o{ PRODUCTS : sells
    PRODUCTS ||--o{ SNAPSHOTS : "observed as"
    SEARCH_RUNS ||--o{ SNAPSHOTS : produces
    SEARCH_RUNS ||--o{ SCRAPE_ERRORS : logs
    SNAPSHOTS ||--o| OPPORTUNITY_SCORES : "scored as"

    NICHES {
        int id PK
        text name
        text slug
        text created_at
        text last_scraped_at
    }
    KEYWORDS {
        int id PK
        text text
    }
    SEARCH_RUNS {
        int id PK
        int niche_id FK
        int keyword_id FK
        text run_timestamp
        text status
        text current_stage
        int pages_scraped
        int products_found
    }
    SELLERS {
        int id PK
        text name
        text first_seen_at
    }
    PRODUCTS {
        int id PK
        text asin
        text title
        text brand
        int seller_id FK
        text fulfillment_type
        text category_path
    }
    SNAPSHOTS {
        int id PK
        int product_id FK
        int search_run_id FK
        text parsed_at
        real price
        real rating
        int review_count
        int search_rank_position
        text bsr_data
        int images_count
        int bullet_points_count
        int has_a_plus_content
        int variant_count
    }
    OPPORTUNITY_SCORES {
        int id PK
        int snapshot_id FK
        real demand_score
        real competition_score
        real quality_gap_score
        real final_score
    }
    SCRAPE_ERRORS {
        int id PK
        int search_run_id FK
        text error_type
        text error_message
    }
    SCHEDULED_NICHES {
        int id PK
        int niche_id FK
        int keyword_id FK
        text frequency
        int is_active
    }
```

<sub>`niche_keywords` and `niche_products` are junction tables, drawn here as many-to-many links. Some columns are omitted for readability.</sub>

Design notes:

- **One snapshot per product per run.** Re-processing a run updates its rows instead of duplicating them.
- **History by default.** Running a niche again adds new snapshots, which is what makes review velocity and trends possible.
- **Local first.** The database is a SQLite file at `data/scraper_analysis.db`, created by `init_db` and evolved with numbered migrations in `migrations/`.

## Configuration

Scraper and scoring defaults live in [`src/config.py`](src/config.py) as plain Python variables. The Python code does not read a `.env` file.

| Setting | Default | Description |
| :--- | :---: | :--- |
| `MAX_PAGES_TO_CRAWL` | `10` | Maximum search pages in one run. |
| `MAX_DETAIL_PAGES_PER_RUN` | `100` | Maximum product detail pages selected for a run. |
| `SEARCH_PAGE_CONCURRENCY` | `7` | Concurrent search-page tasks. |
| `PRODUCT_PAGE_CONCURRENCY` | `10` | Concurrent product-detail tasks. |
| `MIN_DELAY` / `MAX_DELAY` | `5` / `15` s | Random pause range between requests. |
| `MAX_RETRIES` | `3` | Total fetch attempts, including the first. |
| `HEADLESS` | `False` | Launch Chromium without a visible window. Set `True` on servers without a display. |
| `PROXY_POOL_SIZE` | `20` | Number of validated public proxies kept in the pool. |
| `SCORE_WEIGHTS` | `0.4 / 0.3 / 0.3` | Demand, competition and quality-gap weights. |

> [!TIP]
> The default concurrency is aggressive for a site that restricts automated access. Lower `SEARCH_PAGE_CONCURRENCY` and `PRODUCT_PAGE_CONCURRENCY` (for example to `2`) if you see CAPTCHAs or access-denied pages.

> [!IMPORTANT]
> Frontend settings are in [`.env.example`](.env.example). Copy it to `nichescope-phase9/.env` only when you need to change them. Values beginning with `VITE_` are bundled into browser code and must never contain secrets.

## Project structure

```text
amazon_scraper/
├── src/
│   ├── config.py            Scraper and scoring settings
│   ├── scraper/             Playwright search, product-detail, proxy and pacing code
│   ├── parser/              Raw HTML to normalized product records
│   ├── analysis/            Opportunity scoring
│   ├── dashboards/          Legacy Streamlit components (not used by the React dashboard)
│   └── storage/             SQLite access, migrations runner, FastAPI backend
├── scripts/                 Pipeline, parser, scoring and schema-check entry points
├── migrations/              Numbered SQLite migrations
├── tests/                   Exploratory tests (see Project status)
├── nichescope-phase9/       React + TypeScript dashboard (Vite)
├── docs/                    README images
└── data/                    Local database, logs and captured pages (git-ignored)
```

## Project status

NicheScope includes a working scraper, parser, scorer, local FastAPI service, and React dashboard. The dashboard can queue real scraper runs for new or saved niches and keywords:

- **Amazon India only.** Search URLs are fixed to `amazon.in`.
- **Tests are not hermetic yet.** Several tests read captured HTML from a local `data/rendered_html/` folder or your real database, so `pytest` is not expected to pass on a fresh clone. Lint (`ruff check`) also reports open findings.
- **Only `amazon.in` is supported.** Search URLs are hard-coded to it.

## Troubleshooting

<details>
<summary><b>Activating the virtual environment fails on Windows</b></summary>

PowerShell may block activation scripts. Allow them for the current session only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

</details>

<details>
<summary><b><code>pnpm</code> is not recognized</b></summary>

Enable it through Corepack, which ships with Node.js:

```powershell
corepack enable
corepack prepare pnpm@10.4.1 --activate
```

</details>

<details>
<summary><b>Playwright cannot find a browser</b></summary>

Install Chromium inside the activated virtual environment:

```powershell
python -m playwright install chromium
```

On Linux, add `--with-deps` to install the system libraries Chromium needs.

</details>

<details>
<summary><b>Runs fail, stall or time out</b></summary>

Proxies come from a free public list and are often slow or unavailable, so a failed run frequently succeeds when repeated. If it keeps failing, lower the two concurrency settings in `src/config.py`, or retry later.

</details>

<details>
<summary><b>Amazon shows a CAPTCHA or "access denied" page</b></summary>

Stop and wait. Do not push harder when access is denied. Reduce how much you scrape and try again later.

</details>

## Responsible use

> [!WARNING]
> Amazon may restrict automated access, and scraping may conflict with its terms. Review Amazon's terms and applicable laws before you run this project, keep request rates low, and stop if access is denied.

- Use NicheScope for personal research and learning, and at your own risk.
- Do not commit credentials, `.env` files, databases, logs, saved Amazon pages or scraped product data. The provided `.gitignore` excludes them.
- Free public proxies can observe the traffic that passes through them. Do not send logins or personal data through them.
- The marketplace is Amazon India (`amazon.in`).

## Roadmap ideas

These are ideas, not commitments:

- Expand offline integration coverage for the dashboard job lifecycle
- Support Amazon marketplaces other than `amazon.in`

## License

MIT, as declared in the dashboard's `package.json`. Add a `LICENSE` file with your name before publishing.

<br>

<div align="center">
<sub>Amazon and its affiliates do not sponsor or endorse this project.</sub>
</div>
<summary><b>Runs fail, stall or time out</b></summary>

Proxies come from a free public list and are often slow or unavailable, so a failed run frequently succeeds when repeated. If it keeps failing, lower the two concurrency settings in `src/config.py`, or retry later.

</details>

<details>
<summary><b>Amazon shows a CAPTCHA or "access denied" page</b></summary>

Stop and wait. Do not push harder when access is denied. Reduce how much you scrape and try again later.

</details>

## Responsible use

> [!WARNING]
> Amazon may restrict automated access, and scraping may conflict with its terms. Review Amazon's terms and applicable laws before you run this project, keep request rates low, and stop if access is denied.

- Use NicheScope for personal research and learning, and at your own risk.
- Do not commit credentials, `.env` files, databases, logs, saved Amazon pages or scraped product data. The provided `.gitignore` excludes them.
- Free public proxies can observe the traffic that passes through them. Do not send logins or personal data through them.
- The marketplace is Amazon India (`amazon.in`).

## Roadmap ideas

These are ideas, not commitments:

- Expand offline integration coverage for the dashboard job lifecycle
- Support Amazon marketplaces other than `amazon.in`

## License

MIT, as declared in the dashboard's `package.json`. Add a `LICENSE` file with your name before publishing.

<br>

<div align="center">
<sub>Amazon and its affiliates do not sponsor or endorse this project.</sub>
</div>
See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and pull request guidance. This project is licensed under the MIT License; see [LICENSE](LICENSE).
=======
# amazon_scraper
>>>>>>> bc93aa42ef3a35f67299712fc57c31be2541681b
