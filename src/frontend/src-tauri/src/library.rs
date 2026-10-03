//! Activating a recovered backup from the desktop shell (B-14).
//!
//! The Python API can only *prepare* a recovered folder: it is itself a
//! writer, so it cannot swap the live database underneath itself. This
//! command is the coordinator: stop the running backend, run the one-shot
//! `--activate` process (which validates, migrates, and preserves the
//! previous library for rollback), then start a fresh backend. If the
//! activation process fails, the backend is restarted against the
//! unchanged library so the app stays usable.

use serde::Serialize;
use tauri::{AppHandle, Manager};

use crate::backend::{Backend, BackendInfo};

#[derive(Serialize)]
pub struct ActivationOutcome {
    ok: bool,
    message: String,
    backend: Option<BackendInfo>,
}

/// Replace the managed `Backend` in place. `app.manage` cannot be called
/// twice for one type, so the shell holds it behind a `Mutex` and swaps
/// the value; `backend_info` reads through the same cell.
fn replace_backend(app: &AppHandle, backend: Backend) {
    let state: tauri::State<'_, BackendCell> = app.state();
    let replaced = state.0.lock().ok().map(|mut guard| {
        *guard = Some(backend);
    });
    let _ = replaced;
}

pub struct BackendCell(pub std::sync::Mutex<Option<Backend>>);

#[tauri::command]
pub async fn activate_backup(
    app: AppHandle,
    backup_id: String,
) -> Result<ActivationOutcome, String> {
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || activate_blocking(&handle, &backup_id))
        .await
        .map_err(|e| e.to_string())?
}

fn activate_blocking(app: &AppHandle, backup_id: &str) -> Result<ActivationOutcome, String> {
    // 1. Stop the current backend and its writers.
    {
        let state: tauri::State<'_, BackendCell> = app.state();
        let stopped = state.0.lock().ok().map(|mut guard| {
            if let Some(backend) = guard.as_ref() {
                backend.shutdown();
            }
            *guard = None;
        });
        let _ = stopped;
    }

    // 2. Run the one-shot activation against the same data folder.
    let activated = run_activation(app, backup_id);

    // 3. Start a fresh backend either way — on success it reads the
    //    recovered library, on failure the unchanged one.
    let backend = Backend::spawn(app)
        .map_err(|e| format!("activation {}: could not restart the backend: {e}",
            if activated.is_ok() { "succeeded" } else { "failed" }))?;
    let info = backend.wait_ready_public().ok();
    replace_backend(app, backend);

    match activated {
        Ok(()) => Ok(ActivationOutcome {
            ok: true,
            message: "Recovered backup activated. The library restarted against it.".into(),
            backend: info,
        }),
        Err(error) => Ok(ActivationOutcome {
            ok: false,
            message: format!(
                "Activation failed; the previous library was kept. {error}"
            ),
            backend: info,
        }),
    }
}

fn run_activation(app: &AppHandle, backup_id: &str) -> Result<(), String> {
    let mut launch = crate::backend::activation_command(app, backup_id)
        .map_err(|e| format!("could not prepare activation: {e}"))?;
    let output = launch
        .output()
        .map_err(|e| format!("could not run activation: {e}"))?;
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(stderr.trim().to_string())
}
