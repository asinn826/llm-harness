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
    PYTHONWARNINGS="ignore::UserWarning" python3.11 -m uvicorn ui.backend.server:app \
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
    wait 2>/dev/null
    echo -e "${DIM}Done.${RESET}"
}

trap cleanup EXIT INT TERM

case "${1:-}" in
    --backend)
        start_backend
        wait
        ;;
    --browser)
        echo -e "${DIM}Browser mode — no native window${RESET}"
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
