#!/usr/bin/env bash
# Optional convenience: launch backend (:8000) and frontend (:5173) together.
# Requires: python venv with app/backend/requirements.txt installed, and
# `npm install` already run in app/frontend.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

(cd "$ROOT/app/backend" && python -m uvicorn app.main:app --port 8000 --reload) &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null' EXIT

cd "$ROOT/app/frontend" && npm run dev
