#!/bin/bash
# Development mode: runs the FastAPI backend and Vite dev server concurrently.
#
# Usage:
#   ./ui/dev.sh            # Start both backend and frontend
#   ./ui/dev.sh --backend  # Start backend only
#   ./ui/dev.sh --frontend # Start frontend only
#
# The frontend dev server proxies API requests to the backend (see vite.config.ts).
# Backend runs on :8000, frontend on :5173.

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
DIM='\033[2m'
RESET='\033[0m'

start_backend() {
    echo -e "${GREEN}Starting backend...${RESET} ${DIM}http://localhost:8000${RESET}"
    python3 -m uvicorn ui.backend.server:app \
        --host 127.0.0.1 \
        --port 8000 \
        --reload \
        --reload-dir ui/backend \
        --reload-dir harness.py \
        --reload-dir tools.py \
        --reload-dir memory.py &
    BACKEND_PID=$!
}

start_frontend() {
    echo -e "${GREEN}Starting frontend...${RESET} ${DIM}http://localhost:5173${RESET}"
    cd "$PROJECT_ROOT/ui/frontend"
    npx vite --host 127.0.0.1 &
    FRONTEND_PID=$!
    cd "$PROJECT_ROOT"
}

cleanup() {
    echo -e "\n${DIM}Shutting down...${RESET}"
    [ -n "$BACKEND_PID" ] && kill $BACKEND_PID 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill $FRONTEND_PID 2>/dev/null
    wait 2>/dev/null
    echo -e "${DIM}Done.${RESET}"
}

trap cleanup EXIT INT TERM

case "${1:-}" in
    --backend)
        start_backend
        wait $BACKEND_PID
        ;;
    --frontend)
        start_frontend
        wait $FRONTEND_PID
        ;;
    *)
        start_backend
        sleep 1
        start_frontend
        echo -e "\n${GREEN}Ready.${RESET} Open ${DIM}http://localhost:5173${RESET}"
        echo -e "${DIM}Press Ctrl+C to stop.${RESET}\n"
        wait
        ;;
esac
