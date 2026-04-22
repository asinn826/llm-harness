// LLM Harness — Tauri desktop shell
//
// In dev mode, the backend is started by ./ui/dev.sh separately.
// In production, this spawns the bundled PyInstaller sidecar binary
// (ui/frontend/src-tauri/binaries/llm-harness-backend-*) and waits
// for its "HARNESS_READY <port>" marker before revealing the window.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;

#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{ShellExt, process::CommandEvent};

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Hide the window until the backend is ready (prod only).
            // In dev mode the window shows immediately; backend is already running.
            #[cfg(not(debug_assertions))]
            {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }

                let app_handle = app.handle().clone();

                tauri::async_runtime::spawn(async move {
                    // Sidecar name matches the basename in tauri.conf.json externalBin.
                    // Tauri appends the target triple and locates the binary.
                    let sidecar = match app_handle.shell().sidecar("llm-harness-backend") {
                        Ok(s) => s,
                        Err(e) => {
                            eprintln!("failed to find sidecar: {e}");
                            return;
                        }
                    };

                    let (mut rx, _child) = match sidecar.spawn() {
                        Ok(tuple) => tuple,
                        Err(e) => {
                            eprintln!("failed to spawn sidecar: {e}");
                            return;
                        }
                    };

                    let mut shown = false;

                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line_bytes) => {
                                let line = String::from_utf8_lossy(&line_bytes);
                                let trimmed = line.trim();
                                if trimmed.starts_with("HARNESS_READY") && !shown {
                                    shown = true;
                                    if let Some(window) = app_handle.get_webview_window("main") {
                                        let _ = window.show();
                                        let _ = window.set_focus();
                                    }
                                }
                                eprintln!("[backend] {}", trimmed);
                            }
                            CommandEvent::Stderr(line_bytes) => {
                                let line = String::from_utf8_lossy(&line_bytes);
                                eprintln!("[backend:err] {}", line.trim_end());
                            }
                            CommandEvent::Terminated(_) => {
                                eprintln!("[backend] terminated");
                                break;
                            }
                            _ => {}
                        }
                    }
                });

                // Safety net: reveal the window after 20s even if we never
                // saw HARNESS_READY — user sees the error banner instead of
                // staring at a hidden window.
                let app_handle2 = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    tokio::time::sleep(std::time::Duration::from_secs(20)).await;
                    if let Some(window) = app_handle2.get_webview_window("main") {
                        if !window.is_visible().unwrap_or(true) {
                            let _ = window.show();
                        }
                    }
                });
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
