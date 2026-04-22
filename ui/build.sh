#!/bin/bash
# LLM Harness — standalone .app build pipeline (Apple Silicon Mac)
#
# Usage:
#   ./ui/build.sh            # build .app (into src-tauri/target/release/bundle/)
#   ./ui/build.sh --install  # also copy to /Applications
#
# Pipeline:
#   1. Build React frontend    → ui/frontend/dist/
#   2. PyInstaller sidecar     → ui/frontend/src-tauri/binaries/
#   3. tauri build             → LLM Harness.app + .dmg
#   4. Ad-hoc codesign         → avoids "damaged app" Gatekeeper error
#   5. (optional) Install      → copy to /Applications

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

GREEN='\033[0;32m'
DIM='\033[2m'
BOLD='\033[1m'
RED='\033[0;31m'
RESET='\033[0m'

step() { echo -e "\n${GREEN}▸${RESET} ${BOLD}$1${RESET}"; }
sub() { echo -e "  ${DIM}$1${RESET}"; }

INSTALL=false
for arg in "$@"; do
    case "$arg" in
        --install) INSTALL=true ;;
    esac
done

# Apple Silicon only for now
TARGET_TRIPLE="aarch64-apple-darwin"
SIDECAR_NAME="llm-harness-backend"
SIDECAR_BIN="${SIDECAR_NAME}-${TARGET_TRIPLE}"

# ── Preflight ────────────────────────────────────────────────────────
step "Preflight"
for cmd in python3.11 npm cargo; do
    if ! command -v "$cmd" &>/dev/null; then
        echo -e "${RED}Missing: $cmd${RESET}"
        exit 1
    fi
done
if ! python3.11 -c "import PyInstaller" &>/dev/null; then
    sub "Installing PyInstaller..."
    python3.11 -m pip install --quiet pyinstaller
fi
sub "all tools present"

# ── Step 1: Frontend ─────────────────────────────────────────────────
step "Building frontend"
cd "$PROJECT_ROOT/ui/frontend"
if [ ! -d "node_modules" ]; then
    sub "Installing npm deps..."
    npm install --silent
fi
npm run build --silent
sub "→ dist/"

# ── Step 2: PyInstaller sidecar ──────────────────────────────────────
step "Bundling Python sidecar"
cd "$PROJECT_ROOT"

# Clean old build artifacts to avoid stale caches
rm -rf build/ dist/ "ui/backend/build" "ui/backend/dist"

python3.11 -m PyInstaller \
    --onefile \
    --noconfirm \
    --clean \
    --name "${SIDECAR_BIN}" \
    --distpath "${PROJECT_ROOT}/ui/frontend/src-tauri/binaries" \
    --workpath "${PROJECT_ROOT}/build/pyinstaller" \
    --specpath "${PROJECT_ROOT}/build" \
    --paths "${PROJECT_ROOT}" \
    --paths "${PROJECT_ROOT}/ui/backend" \
    --add-data "${PROJECT_ROOT}/ui/backend/recommended_models.json:ui/backend" \
    --add-data "${PROJECT_ROOT}/harness.py:." \
    --add-data "${PROJECT_ROOT}/tools.py:." \
    --add-data "${PROJECT_ROOT}/memory.py:." \
    --add-data "${PROJECT_ROOT}/main.py:." \
    --collect-all mlx \
    --collect-all mlx_lm \
    --collect-all huggingface_hub \
    --collect-submodules uvicorn \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.http.h11_impl \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.protocols.websockets.websockets_impl \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.loops.uvloop \
    --hidden-import uvicorn.lifespan.on \
    --hidden-import websockets.legacy \
    --hidden-import websockets.legacy.server \
    --hidden-import dotenv \
    --hidden-import psutil \
    --exclude-module torch \
    --exclude-module torchvision \
    --exclude-module torchaudio \
    --exclude-module transformers \
    --exclude-module tensorflow \
    --exclude-module pytest \
    --exclude-module setuptools \
    --exclude-module pip \
    --exclude-module wheel \
    --exclude-module tkinter \
    --exclude-module test \
    --exclude-module matplotlib \
    --exclude-module jupyter \
    --exclude-module IPython \
    "${PROJECT_ROOT}/ui/backend/standalone.py"

if [ ! -f "ui/frontend/src-tauri/binaries/${SIDECAR_BIN}" ]; then
    echo -e "${RED}PyInstaller did not produce expected binary${RESET}"
    exit 1
fi

# NOTE: Do NOT `strip` the PyInstaller binary. It appends its Python
# archive after the Mach-O segments, and strip truncates that data,
# producing a valid-looking but non-functional binary.

SIDECAR_SIZE=$(du -h "ui/frontend/src-tauri/binaries/${SIDECAR_BIN}" | cut -f1)
sub "→ binaries/${SIDECAR_BIN} (${SIDECAR_SIZE})"

# ── Step 3: Tauri build ──────────────────────────────────────────────
step "Building .app with Tauri"
cd "$PROJECT_ROOT/ui/frontend"
npx tauri build 2>&1 | grep -v "^warning:" | grep -v "^$" || true

APP_PATH="$PROJECT_ROOT/ui/frontend/src-tauri/target/release/bundle/macos/LLM Harness.app"
if [ ! -d "$APP_PATH" ]; then
    echo -e "${RED}Tauri did not produce .app${RESET}"
    exit 1
fi
sub "→ ${APP_PATH}"

# ── Step 4: Ad-hoc codesign ──────────────────────────────────────────
step "Ad-hoc codesigning"
codesign --force --deep --sign - "$APP_PATH" 2>&1 | tail -3
sub "signed with ad-hoc identity"

APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)

# ── Step 5: Install (optional) ──────────────────────────────────────
if [ "$INSTALL" = true ]; then
    step "Installing to /Applications"
    rm -rf "/Applications/LLM Harness.app"
    cp -r "$APP_PATH" "/Applications/"
    sub "→ /Applications/LLM Harness.app"
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✓ Build complete${RESET}"
echo -e "${DIM}  .app: ${APP_PATH}${RESET}"
echo -e "${DIM}  size: ${APP_SIZE}${RESET}"
if [ "$INSTALL" = true ]; then
    echo -e "${DIM}  installed: /Applications/LLM Harness.app${RESET}"
    echo ""
    echo -e "${BOLD}Launch:${RESET} open -a 'LLM Harness'"
else
    echo ""
    echo -e "${BOLD}Install:${RESET} ${DIM}./ui/build.sh --install${RESET}"
    echo -e "${BOLD}Or:${RESET} ${DIM}cp -r '${APP_PATH}' /Applications/${RESET}"
fi
