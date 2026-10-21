# NicheScope Phase 9 progress

- [x] Audit the Phase 9 frontend, Python storage layer, active SQLite schema, database path, and migration history.
- [x] Replace fixture-backed frontend data with typed calls to the existing FastAPI application.
- [x] Add schema-aligned, read-only dashboard queries for overview metrics, niche and keyword relationships, products, runs, errors, schedules, history, and analytics.
- [x] Add server-side filtering and pagination for product, run, seller, and error lists.
- [x] Add interactive Recharts views with compatible chart selectors, date/niche filters, product comparison, and CSV export.
- [x] Keep scraper startup routed through the existing Python pipeline endpoint; remove simulated progress and unsupported recurring controls.
- [x] Add focused temporary-database tests for latest snapshots, scores, cardinality, historical observations, filters, errors, and schedules.

## Database audit

The configured database is the existing `data/scraper_analysis.db`. Its active schema matches the current contract, including `parsed_at`, all four supported run statuses, `current_stage`, `current_task`, and the unique score index on `opportunity_scores.snapshot_id`. The database has one recorded migration version and currently contains no application records. Foreign-key checks are clean. No schema change or migration was needed.

The repository also contains unrecorded legacy/test migration files. In particular, migration 0007 rebuilds `search_runs` without the active `current_task` column. The dashboard does not execute migrations, and this work did not apply them.

## Launch

Start the API from the project root:

```powershell
.\niche_finder\Scripts\python.exe -m uvicorn src.storage.backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, start the Phase 9 frontend:

```powershell
cd .\nichescope-phase9
.\node_modules\.bin\vite.cmd --host 127.0.0.1
```

Open `http://localhost:3000/`.

## Verification

- `npm run check` passes.
- `npm run build` passes. Vite reports the starter analytics placeholders are unset and the combined client JavaScript chunk is over its advisory size threshold.
- `tests/test_dashboard_queries.py` passes against a temporary SQLite database seeded with multiple niches, products, snapshots, scores, errors, and a schedule.
- Python backend modules compile and the API, scraper router, parsers, and scoring modules import successfully.
- API and frontend proxy smoke checks return the built dashboard and live API responses. Invalid status/date/price filters return 422, and missing records return 404.
- The configured database was inspected read-only and independently checked against overview counts. It has no application rows, one recorded migration, and no foreign-key violations.

The migration test was not run because its runner targets the configured database and the repository contains unrecorded legacy migrations, including one that drops the active `current_task` column. No browser-based visual check was available in this environment.
