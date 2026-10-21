# Contributing

## Setup and checks

Use Python 3.13.1, install `requirements-dev.txt`, and run `pytest -q` and
`ruff check` from the repository root. For the active dashboard, use the
`nichescope-phase9` folder and its frozen pnpm lockfile.

## Pull requests

Use Conventional Commit subjects such as `fix: handle empty proxy pools` or
`docs: clarify database setup`. Include a concise description of the change and
the checks you ran. Do not include credentials, `.env` files, databases, logs,
browser profiles, saved Amazon pages, screenshots, or scraped product data.
Keep tests offline and use synthetic HTML fixtures.
