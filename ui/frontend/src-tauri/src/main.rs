// LLM Harness — Tauri desktop shell
//
// In dev mode, the backend is started by dev.sh separately.
// In production, this spawns the FastAPI backend as a child process.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|_app| {
            #[cfg(not(debug_assertions))]
            {
                use tauri::Manager;
                let python = if cfg!(target_os = "macos") {
                    "python3"
                } else {
                    "python"
                };

                let resource_dir = _app
                    .path()
                    .resource_dir()
                    .expect("failed to resolve resource dir");

                std::process::Command::new(python)
                    .args([
                        "-m", "uvicorn",
                        "ui.backend.server:app",
                        "--host", "127.0.0.1",
                        "--port", "8000",
                    ])
                    .current_dir(resource_dir.parent().unwrap().parent().unwrap())
                    .spawn()
                    .expect("failed to start backend");
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
