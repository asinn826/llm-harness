"""Standalone entry point for the packaged .app.

PyInstaller bundles this file, the FastAPI app, and all Python deps into
a single binary that ships as a Tauri sidecar. The Rust shell spawns this
executable on app launch and kills it on quit.

Writes a startup marker line ("HARNESS_READY <port>") to stdout when the
server is accepting connections — Tauri polls that to know when to
reveal the webview window.
"""
import os
import sys
import threading
import time

# Default port; override via HARNESS_PORT env var if needed
PORT = int(os.environ.get("HARNESS_PORT", "8765"))
HOST = "127.0.0.1"


def _fix_bundled_paths():
    """Make sure `ui.backend.server` and friends are importable.

    Two cases:
    - Frozen (PyInstaller): bundled files live at sys._MEIPASS.
    - Source run (dev smoke test): add project root (two levels up) to path.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = sys._MEIPASS
        if meipass not in sys.path:
            sys.path.insert(0, meipass)
    else:
        # Running as a script — add project root so ui.backend.* resolves
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)


def _wait_for_ready_and_print():
    """Poll /health until the server is accepting requests, then print marker."""
    import urllib.request
    url = f"http://{HOST}:{PORT}/health"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    print(f"HARNESS_READY {PORT}", flush=True)
                    return
        except Exception:
            pass
        time.sleep(0.1)
    print(f"HARNESS_TIMEOUT {PORT}", flush=True)


def main():
    _fix_bundled_paths()

    # Import after path fix so bundled modules resolve
    import uvicorn
    from ui.backend.server import app  # noqa: F401  # register routes

    # Start readiness probe in the background
    threading.Thread(target=_wait_for_ready_and_print, daemon=True).start()

    # Serve forever (Tauri kills the process on quit)
    uvicorn.run(
        "ui.backend.server:app",
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
