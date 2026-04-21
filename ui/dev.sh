#!/bin/bash
# Development mode for the LLM Harness desktop app.
#
# Usage:
#   ./ui/dev.sh              # Launch desktop app (Tauri dev mode)
#   ./ui/dev.sh --browser    # Fallback: open in browser instead of native window
#   ./ui/dev.sh --backend    # Backend only (for debugging)
#
# Default mode launches Tauri, which opens a native window with hot reload.
# The --browser fallback is for environments without Rust installed.

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

PIDS=()

# Prefer python3.11 if present, otherwise fall back to python3.
if command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3 &>/dev/null; then
    PYTHON=python3
else
    echo -e "${RED}No python3 found on PATH.${RESET}"
    exit 1
fi

check_rust() {
    if ! command -v cargo &>/dev/null; then
        echo -e "${RED}Rust not found.${RESET} Tauri requires Rust to build the native window."
        echo ""
        echo -e "  Install Rust:  ${BOLD}curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh${RESET}"
        echo ""
        echo -e "  Or run in browser mode:  ${BOLD}./ui/dev.sh --browser${RESET}"
        exit 1
    fi
}

start_backend() {
    echo -e "${GREEN}Starting backend...${RESET} ${DIM}:8000${RESET}"
    # Use --no-access-log to reduce noise, PYTHONWARNINGS to suppress semaphore leak
    PYTHONWARNINGS="ignore::UserWarning" "$PYTHON" -m uvicorn ui.backend.server:app \
        --host 127.0.0.1 \
        --port 8000 \
        --reload \
        --reload-dir ui/backend \
        --reload-dir harness.py \
        --reload-dir tools.py \
        --reload-dir memory.py \
        --no-access-log \
        2>&1 &
    PIDS+=($!)
}

cleanup() {
    echo -e "\n${DIM}Shutting down...${RESET}"
    # Kill all child processes of this script
    pkill -P $$ 2>/dev/null
    sleep 0.3
    # Force kill anything still alive
    pkill -9 -P $$ 2>/dev/null
    # Also kill by stored PIDs in case pkill missed them
    for pid in "${PIDS[@]}"; do
        kill -9 "$pid" 2>/dev/null
    done
    # Belt-and-suspenders: uvicorn's --reload spawns a reloader parent + worker
    # child, and the worker's PID isn't in PIDS. If the parent dies ungracefully
    # the worker (or a closed-socket zombie parent) can squat on :8000 and
    # break the next launch with a silent ECONNREFUSED from Vite.
    pkill -9 -f 'uvicorn ui.backend.server:app' 2>/dev/null
    wait 2>/dev/null
    echo -e "${DIM}Done.${RESET}"
}

# If a previous run left a uvicorn zombie on :8000, the new backend will fail
# to bind and Vite's proxy will silently ECONNREFUSED. Clear it up front.
preflight_port_8000() {
    if lsof -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | head -1 >/dev/null || \
       pgrep -f 'uvicorn ui.backend.server:app' >/dev/null 2>&1; then
        echo -e "${DIM}Clearing stale process on :8000...${RESET}"
        pkill -9 -f 'uvicorn ui.backend.server:app' 2>/dev/null
        # Also kill anything still bound to 8000 (e.g. closed-socket zombie).
        local stuck
        stuck=$(lsof -iTCP:8000 -t 2>/dev/null)
        if [ -n "$stuck" ]; then
            kill -9 $stuck 2>/dev/null
        fi
        sleep 0.3
    fi
}

trap cleanup EXIT INT TERM

case "${1:-}" in
    --backend)
        preflight_port_8000
        start_backend
        wait
        ;;
    --browser)
        echo -e "${DIM}Browser mode — no native window${RESET}"
        preflight_port_8000
        start_backend
        sleep 1
        echo -e "${GREEN}Starting frontend...${RESET}"
        cd "$PROJECT_ROOT/ui/frontend"
        npx vite --host 127.0.0.1 --open &
        PIDS+=($!)
        cd "$PROJECT_ROOT"
        echo -e "\n${GREEN}Ready.${RESET}"
        echo -e "${DIM}Press Ctrl+C to stop.${RESET}\n"
        wait
        ;;
    *)
        check_rust
        preflight_port_8000
        start_backend
        sleep 1
        echo -e "${GREEN}Launching desktop app...${RESET}"
        cd "$PROJECT_ROOT/ui/frontend"
        npx tauri dev &
        PIDS+=($!)
        cd "$PROJECT_ROOT"
        echo -e "\n${GREEN}Ready.${RESET} Native window should open shortly."
        echo -e "${DIM}Press Ctrl+C to stop.${RESET}\n"
        wait
        ;;
esac
