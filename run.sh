#!/usr/bin/env bash
# Start the app with one command (macOS / Linux):
#   OPENAI_API_KEY=sk-... ./run.sh     an OpenAI key; no .env editing needed
#   ./run.sh                           whatever backend/.env says (created from .env.example the first time)
# Optional: OPENAI_MODEL (default gpt-4.1-mini), PORT (default 8000).
set -euo pipefail
cd "$(dirname "$0")"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing $1. $2" >&2; exit 1; }; }
need uv "Install it from https://docs.astral.sh/uv/getting-started/installation/"
need npm "Install Node.js 22 or newer from https://nodejs.org/"

if [ ! -f backend/.env ]; then
  if [ -n "${OPENAI_API_KEY:-}" ]; then
    # The key is written into backend/.env, which git ignores; refuse anything that is not key-shaped.
    [[ "$OPENAI_API_KEY" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "OPENAI_API_KEY has unexpected characters." >&2; exit 1; }
    model="${OPENAI_MODEL:-gpt-4.1-mini}"
    sed -e "s|^LLM_BASE_URL=.*|LLM_BASE_URL=https://api.openai.com/v1|" \
        -e "s|^LLM_API_KEY=.*|LLM_API_KEY=${OPENAI_API_KEY}|" \
        -e "s|^LLM_MODEL=.*|LLM_MODEL=${model}|" \
        -e "s|^LLM_EXTRA_BODY=.*|LLM_EXTRA_BODY=|" \
        backend/.env.example > backend/.env
    echo "Created backend/.env for OpenAI ($model)."
  else
    cp backend/.env.example backend/.env
    echo "Created backend/.env for the tested local model (llama.cpp at port 8080)."
    echo "To use OpenAI instead: rm backend/.env, then run OPENAI_API_KEY=sk-... ./run.sh"
  fi
elif [ -n "${OPENAI_API_KEY:-}" ]; then
  echo "backend/.env already exists and is used as it is. To switch to OpenAI, delete it and run this again."
fi

if [ ! -f frontend/dist/index.html ]; then
  echo "Building the web interface (first run only)..."
  npm --prefix frontend ci --no-audit --no-fund
  npm --prefix frontend run build
fi

echo "Open http://localhost:${PORT:-8000}"
exec uv --directory backend run uvicorn app.main:app --port "${PORT:-8000}"
