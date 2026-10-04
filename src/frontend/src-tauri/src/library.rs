//! Backup activation stops all writers before swapping the recovered library.

use std::sync::{Arc, Mutex};

use serde::Serialize;
use tauri::{AppHandle, Manager};

use crate::backend::{Backend, BackendInfo};

#[derive(Serialize)]
pub struct ActivationOutcome {
    ok: bool,
    message: String,
    backend: Option<BackendInfo>,
}

pub enum BackendState {
    Running(Arc<Backend>),
    Restarting,
    Unavailable(String),
}

pub struct BackendCell {
    state: Mutex<BackendState>,
    operation: Mutex<()>,
}

impl BackendCell {
    pub fn new(state: BackendState) -> Self {
        Self {
            state: Mutex::new(state),
            operation: Mutex::new(()),
        }
    }

    pub fn current(&self) -> Result<Arc<Backend>, String> {
        match &*self.state.lock().map_err(|e| e.to_string())? {
            BackendState::Running(backend) => Ok(backend.clone()),
            BackendState::Restarting => Err("The backend is restarting. Try again shortly.".into()),
            BackendState::Unavailable(reason) => Err(reason.clone()),
        }
    }

    pub fn is_current(&self, backend: &Arc<Backend>) -> Result<bool, String> {
        let guard = self.state.lock().map_err(|e| e.to_string())?;
        Ok(matches!(&*guard, BackendState::Running(current) if Arc::ptr_eq(current, backend)))
    }

    fn take_for_restart(&self) -> Result<Option<Arc<Backend>>, String> {
        let mut guard = self.state.lock().map_err(|e| e.to_string())?;
        match std::mem::replace(&mut *guard, BackendState::Restarting) {
            BackendState::Running(backend) => Ok(Some(backend)),
            _ => Ok(None),
        }
    }

    fn set(&self, state: BackendState) -> Result<(), String> {
        *self.state.lock().map_err(|e| e.to_string())? = state;
        Ok(())
    }
}

#[tauri::command]
pub async fn activate_backup(
    app: AppHandle,
    backup_id: String,
) -> Result<ActivationOutcome, String> {
    tauri::async_runtime::spawn_blocking(move || activate_blocking(&app, &backup_id))
        .await
        .map_err(|e| e.to_string())?
}

fn activate_blocking(app: &AppHandle, backup_id: &str) -> Result<ActivationOutcome, String> {
    let cell: tauri::State<'_, BackendCell> = app.state();
    let _operation = cell
        .operation
        .try_lock()
        .map_err(|_| "A library restart is already in progress.")?;
    if let Some(backend) = cell.take_for_restart()? {
        backend.shutdown();
    }
    let activated = run_activation(app, backup_id);
    let mut message = match &activated {
        Ok(()) => "Recovered backup activated.".to_string(),
        Err(error) => format!("Activation failed; the previous library was kept. {error}"),
    };
    let info = match start_backend(app, &cell) {
        Ok(info) => {
            message.push_str(" The backend restarted.");
            Some(info)
        }
        Err(error) => {
            message.push_str(&format!(
                " The backend could not restart: {error} Use Restart backend to retry."
            ));
            cell.set(BackendState::Unavailable(message.clone()))?;
            None
        }
    };
    Ok(ActivationOutcome {
        ok: activated.is_ok(),
        message,
        backend: info,
    })
}

fn start_backend(app: &AppHandle, cell: &BackendCell) -> Result<BackendInfo, String> {
    let backend = Arc::new(Backend::spawn(app).map_err(|e| e.to_string())?);
    cell.set(BackendState::Running(backend.clone()))?;
    match backend.wait_ready_public() {
        Ok(info) => Ok(info),
        Err(error) => {
            cell.set(BackendState::Unavailable(error.clone()))?;
            backend.shutdown();
            Err(error)
        }
    }
}

#[tauri::command]
pub async fn restart_backend(app: AppHandle) -> Result<BackendInfo, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let cell: tauri::State<'_, BackendCell> = app.state();
        let _operation = cell
            .operation
            .try_lock()
            .map_err(|_| "A library restart is already in progress.")?;
        if let Ok(backend) = cell.current() {
            if !backend.failed() {
                return backend.wait_ready_public();
            }
        }
        if let Some(backend) = cell.take_for_restart()? {
            backend.shutdown();
        }
        match start_backend(&app, &cell) {
            Ok(info) => Ok(info),
            Err(error) => {
                cell.set(BackendState::Unavailable(format!(
                    "Could not start the backend: {error}"
                )))?;
                Err(error)
            }
        }
    })
    .await
    .map_err(|e| e.to_string())?
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
    Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
}
