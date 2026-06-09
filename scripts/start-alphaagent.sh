#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE="${COMPOSE:-docker compose}"
API_URL="${API_URL:-http://localhost:8000/api}"
WEB_URL="${WEB_URL:-http://localhost:5173}"
WAIT_SECONDS="${WAIT_SECONDS:-90}"

usage() {
  cat <<'EOF'
Usage: scripts/start-alphaagent.sh [--no-build] [--logs] [--status]

Starts AlphaAgent with Docker Compose:
  - alphaagent-api on http://localhost:8000/api
  - alphaagent-web on http://localhost:5173

Options:
  --no-build   Start existing images without rebuilding.
  --logs       Follow service logs after startup.
  --status     Print current compose status and exit.
EOF
}

build=1
follow_logs=0
status_only=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)
      build=0
      ;;
    --logs)
      follow_logs=1
      ;;
    --status)
      status_only=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not in PATH" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example. Review DATABASE_URL if PostgreSQL needs a real password."
  else
    echo ".env is missing and .env.example was not found" >&2
    exit 1
  fi
fi

if [[ "$status_only" -eq 1 ]]; then
  $COMPOSE ps
  exit 0
fi

echo "Starting AlphaAgent services..."
if [[ "$build" -eq 1 ]]; then
  $COMPOSE up -d --build alphaagent-api alphaagent-web
else
  $COMPOSE up -d alphaagent-api alphaagent-web
fi

echo "Waiting for API health: ${API_URL}/health"
deadline=$((SECONDS + WAIT_SECONDS))
until curl -fsS "${API_URL}/health" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "API did not become healthy within ${WAIT_SECONDS}s" >&2
    $COMPOSE ps >&2
    echo "Recent API logs:" >&2
    $COMPOSE logs --tail=80 alphaagent-api >&2
    exit 1
  fi
  sleep 2
done

echo "Checking frontend: ${WEB_URL}/sectors"
deadline=$((SECONDS + WAIT_SECONDS))
until curl -fsS "${WEB_URL}/sectors" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "Frontend did not respond within ${WAIT_SECONDS}s" >&2
    $COMPOSE ps >&2
    echo "Recent web logs:" >&2
    $COMPOSE logs --tail=80 alphaagent-web >&2
    exit 1
  fi
  sleep 2
done

echo
echo "AlphaAgent is running."
echo "Web: ${WEB_URL}/sectors"
echo "API: ${API_URL}/health"
echo
$COMPOSE ps

if [[ "$follow_logs" -eq 1 ]]; then
  $COMPOSE logs -f alphaagent-api alphaagent-web
fi
