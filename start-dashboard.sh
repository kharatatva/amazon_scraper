#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/nichescope-phase9"
PYTHON_EXE="$PROJECT_ROOT/.venv/bin/python"
DATA_DIR="$PROJECT_ROOT/data"
LOG_DIR="$DATA_DIR/logs"

fail() {
    printf 'NicheScope setup: %s\n' "$1" >&2
    exit 1
}

if [[ ! -x "$PYTHON_EXE" ]]; then
    command -v python3.13 >/dev/null 2>&1 || fail "Install Python 3.13, then run this launcher again."
    python3.13 -m venv "$PROJECT_ROOT/.venv" || fail "Could not create the project Python environment."
fi

"$PYTHON_EXE" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)' \
    || fail "This project requires Python 3.13."

if ! "$PYTHON_EXE" -c 'import bs4, playwright, playwright_stealth, fastapi, requests, uvicorn' >/dev/null 2>&1; then
    printf 'Installing required Python packages...\n'
    "$PYTHON_EXE" -m pip install -r "$PROJECT_ROOT/requirements.txt" \
        || fail "Python package installation failed. Check network access and retry."
fi

command -v node >/dev/null 2>&1 || fail "Install Node.js 20.19+ or 22.12+, then run this launcher again."
NODE_VERSION="$(node -p 'process.versions.node')"
IFS=. read -r NODE_MAJOR NODE_MINOR _ <<< "$NODE_VERSION"
if ! { (( NODE_MAJOR == 20 && NODE_MINOR >= 19 )) \
    || (( NODE_MAJOR == 22 && NODE_MINOR >= 12 )) \
    || (( NODE_MAJOR > 22 )); }; then
    fail "The dashboard requires Node.js 20.19+ or 22.12+."
fi

if ! command -v corepack >/dev/null 2>&1 && ! command -v pnpm >/dev/null 2>&1; then
    fail "Install pnpm or a Node.js distribution that includes Corepack."
fi

if [[ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]] \
    || ! "$FRONTEND_DIR/node_modules/.bin/vite" --version >/dev/null 2>&1; then
    printf 'Installing dashboard packages...\n'
    if command -v corepack >/dev/null 2>&1; then
        (cd "$FRONTEND_DIR" && corepack pnpm install --frozen-lockfile)
    else
        (cd "$FRONTEND_DIR" && pnpm install --frozen-lockfile)
    fi || fail "Dashboard package installation failed. Check network access and retry."
fi

mkdir -p "$LOG_DIR"
http_ready() {
    "$PYTHON_EXE" -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)' "$1" >/dev/null 2>&1
}

if ! http_ready "http://127.0.0.1:8000/api/environment"; then
    (cd "$PROJECT_ROOT" && nohup "$PYTHON_EXE" -m uvicorn src.storage.backend.main:app \
        --host 127.0.0.1 --port 8000 >"$LOG_DIR/api-console.log" 2>&1 </dev/null &)
fi

attempt=0
until http_ready "http://127.0.0.1:8000/api/environment"; do
    (( attempt += 1 ))
    (( attempt < 60 )) || fail "The API did not start. Review the local API log under data/logs."
    sleep 0.5
done

if ! http_ready "http://127.0.0.1:3000/"; then
    if command -v corepack >/dev/null 2>&1; then
        (cd "$FRONTEND_DIR" && nohup corepack pnpm exec vite --host 127.0.0.1 \
            >"$LOG_DIR/dashboard-console.log" 2>&1 </dev/null &)
    else
        (cd "$FRONTEND_DIR" && nohup pnpm exec vite --host 127.0.0.1 \
            >"$LOG_DIR/dashboard-console.log" 2>&1 </dev/null &)
    fi
fi

attempt=0
until http_ready "http://127.0.0.1:3000/"; do
    (( attempt += 1 ))
    (( attempt < 40 )) || fail "The dashboard did not start. Review the local dashboard log under data/logs."
    sleep 0.5
done

if command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:3000/"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:3000/" >/dev/null 2>&1 || true
else
    printf 'Open http://127.0.0.1:3000/ in your browser.\n'
fi
