mod backend;
mod companion;
mod library;

use tauri::{Manager, WindowEvent};

use backend::Backend;
use library::BackendCell;

pub fn run() {
    tauri::Builder::default()
        // Two copies of the app would run two backends on one database;
        // a second launch focuses the primary library that is already open.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let backend = Backend::spawn(app.handle())?;
            app.manage(BackendCell(std::sync::Mutex::new(Some(backend))));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend::backend_info,
            companion::show_companion,
            companion::set_companion_pinned,
            companion::show_library,
            library::activate_backup
        ])
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    window.app_handle().exit(0);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Stacks app")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(cell) = app.try_state::<BackendCell>() {
                    if let Ok(guard) = cell.0.lock() {
                        if let Some(backend) = guard.as_ref() {
                            backend.shutdown();
                        }
                    }
                }
            }
        });
}
