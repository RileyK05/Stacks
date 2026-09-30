use std::sync::{Mutex, OnceLock};

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

const COMPANION_WIDTH: f64 = 420.0;
const COMPANION_HEIGHT: f64 = 760.0;
const COMPANION_MIN_WIDTH: f64 = 340.0;
const COMPANION_MIN_HEIGHT: f64 = 420.0;

fn bring_forward(window: &WebviewWindow) -> Result<(), String> {
    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}

/// Create the optional companion only after the user asks for it. Repeated
/// requests focus the existing window instead of creating another webview.
///
/// Must stay `async`: a sync command runs on the main thread, and building a
/// webview there deadlocks WebView2 on Windows (tauri-apps/wry#583) — the
/// window appears but stays white, and a second click blocks on the lock
/// below with the main thread already stuck, freezing the whole app.
#[tauri::command]
pub async fn show_companion(app: AppHandle) -> Result<(), String> {
    // A fast second click can arrive before the first window has finished
    // building. Serialize the lookup and creation to keep one companion.
    static OPEN_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    let _guard = OPEN_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .map_err(|error| error.to_string())?;
    if let Some(window) = app.get_webview_window("companion") {
        return bring_forward(&window);
    }
    let window = WebviewWindowBuilder::new(&app, "companion", WebviewUrl::App("companion/".into()))
        .title("Stacks Companion")
        .inner_size(COMPANION_WIDTH, COMPANION_HEIGHT)
        .min_inner_size(COMPANION_MIN_WIDTH, COMPANION_MIN_HEIGHT)
        .center()
        .resizable(true)
        .decorations(true)
        .always_on_top(false)
        .build()
        .map_err(|error| error.to_string())?;
    bring_forward(&window)
}

#[tauri::command]
pub fn set_companion_pinned(window: WebviewWindow, pinned: bool) -> Result<(), String> {
    window
        .set_always_on_top(pinned)
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub fn show_library(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "the Stacks library window is unavailable".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}
