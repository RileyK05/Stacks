mod backend;

use tauri::Manager;

use backend::Backend;

pub fn run() {
    tauri::Builder::default()
        // Two copies of the app would run two backends on one database;
        // a second launch focuses the window that is already open.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let backend = Backend::spawn(app.handle())?;
            app.manage(backend);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend::backend_info])
        .build(tauri::generate_context!())
        .expect("failed to build the Stacks app")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(backend) = app.try_state::<Backend>() {
                    backend.shutdown();
                }
            }
        });
}
