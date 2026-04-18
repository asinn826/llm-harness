// LLM Harness — Tauri desktop shell
//
// Launches the FastAPI backend as a sidecar process and opens the
// React frontend in a native webview window.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use std::process::Command;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Spawn the FastAPI backend
            let resource_dir = app
                .path()
                .resource_dir()
                .expect("failed to resolve resource dir");

            // In dev mode, the backend is started separately.
            // In production, we spawn it as a child process.
            #[cfg(not(debug_assertions))]
            {
                let python = if cfg!(target_os = "macos") {
                    "python3"
                } else {
                    "python"
                };

                let backend_dir = resource_dir.join("backend");
                Command::new(python)
                    .args([
                        "-m", "uvicorn",
                        "ui.backend.server:app",
                        "--host", "127.0.0.1",
                        "--port", "8000",
                    ])
                    .current_dir(backend_dir.parent().unwrap().parent().unwrap())
                    .spawn()
                    .expect("failed to start backend");
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
