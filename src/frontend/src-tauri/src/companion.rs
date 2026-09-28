use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewWindow};

const EXPANDED_WIDTH: f64 = 420.0;
const COLLAPSED_WIDTH: f64 = 56.0;

fn dock(window: &WebviewWindow, collapsed: bool) -> tauri::Result<()> {
    let monitor = window
        .current_monitor()?
        .or(window.primary_monitor()?)
        .ok_or_else(|| tauri::Error::WindowNotFound)?;
    let work_area = monitor.work_area();
    let scale = monitor.scale_factor();
    let logical_width = if collapsed {
        COLLAPSED_WIDTH
    } else {
        EXPANDED_WIDTH
    };
    let width = (logical_width * scale).round() as u32;
    let x = work_area.position.x + work_area.size.width as i32 - width as i32;

    window.set_size(PhysicalSize::new(width, work_area.size.height))?;
    window.set_position(PhysicalPosition::new(x, work_area.position.y))?;
    Ok(())
}

pub fn initialize(app: &AppHandle) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("companion") {
        dock(&window, false)?;
    }
    Ok(())
}

#[tauri::command]
pub fn set_companion_collapsed(
    window: WebviewWindow,
    collapsed: bool,
) -> Result<(), String> {
    dock(&window, collapsed).map_err(|error| error.to_string())
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

#[tauri::command]
pub fn quit_app(app: AppHandle) {
    app.exit(0);
}
