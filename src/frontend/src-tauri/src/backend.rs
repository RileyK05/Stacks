//! The Python backend as a child process of the app.
//!
//! The shell starts the backend with a per-launch secret (APP_API_TOKEN)
//! and hands that secret only to its own webview (`backend_info`); every
//! API request echoes it, so other programs on this machine that can
//! reach 127.0.0.1 still cannot drive the API. The backend binds a free
//! port itself and announces it on stdout (`STACKS_PORT=<n>`).
//!
//! The shell holds the backend's stdin. Closing it — on quit, or when the
//! app dies — tells the backend to shut down cleanly, which also stops the
//! model server it supervises. A backend that doesn't stop in time is
//! killed.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Manager, State};

const PORT_ANNOUNCEMENT: &str = "STACKS_PORT=";
/// First launch applies migrations and loads the encoders; a slow laptop
/// needs a while.
const START_TIMEOUT: Duration = Duration::from_secs(180);
const STOP_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Clone, Serialize)]
pub struct BackendInfo {
    url: String,
    token: String,
    log_dir: Option<String>,
}

enum Status {
    Starting,
    Ready(BackendInfo),
    Failed(String),
}

type SharedStatus = Arc<(Mutex<Status>, Condvar)>;

pub struct Backend {
    status: SharedStatus,
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

impl Backend {
    pub fn spawn(app: &AppHandle) -> Result<Self, Box<dyn std::error::Error>> {
        let token = new_token().map_err(|e| format!("could not create a launch token: {e}"))?;
        let launch = launch_command(app)?;
        let mut command = launch.command;
        command
            .env("APP_API_TOKEN", &token)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped());
        if let Some(dir) = &launch.log_dir {
            std::fs::create_dir_all(dir)?;
            let log = std::fs::File::create(dir.join("backend-stderr.log"))?;
            command.stderr(Stdio::from(log));
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = command
            .spawn()
            .map_err(|e| format!("could not start the Stacks backend: {e}"))?;
        let stdout = child.stdout.take().expect("stdout is piped");
        let stdin = child.stdin.take();

        let status: SharedStatus = Arc::new((Mutex::new(Status::Starting), Condvar::new()));
        let log_dir = launch.log_dir.map(|dir| dir.display().to_string());
        let watcher = status.clone();
        thread::Builder::new()
            .name("backend-stdout".into())
            .spawn(move || watch_startup(stdout, token, log_dir, watcher))?;

        Ok(Self {
            status,
            child: Mutex::new(Some(child)),
            stdin: Mutex::new(stdin),
        })
    }

    fn wait_ready(&self) -> Result<BackendInfo, String> {
        let (lock, ready) = &*self.status;
        let mut status = lock.lock().map_err(|e| e.to_string())?;
        loop {
            match &*status {
                Status::Ready(info) => return Ok(info.clone()),
                Status::Failed(reason) => return Err(reason.clone()),
                Status::Starting => status = ready.wait(status).map_err(|e| e.to_string())?,
            }
        }
    }

    pub fn shutdown(&self) {
        // Closing stdin is the shutdown signal (src/backend/serve.py).
        if let Ok(mut stdin) = self.stdin.lock() {
            stdin.take();
        }
        let Ok(mut guard) = self.child.lock() else {
            return;
        };
        let Some(mut child) = guard.take() else {
            return;
        };
        let deadline = Instant::now() + STOP_TIMEOUT;
        loop {
            match child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(100)),
                _ => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return;
                }
            }
        }
    }
}

/// The API's address and this launch's token, once the backend answers.
#[tauri::command]
pub async fn backend_info(app: AppHandle) -> Result<BackendInfo, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let backend: State<'_, Backend> = app.state();
        backend.wait_ready()
    })
    .await
    .map_err(|e| e.to_string())?
}

struct Launch {
    command: Command,
    /// Where the backend's stderr goes; None inherits the shell's (dev).
    log_dir: Option<PathBuf>,
}

/// Development runs the backend from the checkout's virtualenv, with the
/// checkout's own data folder, and admits the Vite dev server's origin.
#[cfg(debug_assertions)]
fn launch_command(_app: &AppHandle) -> Result<Launch, Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let python = if cfg!(windows) {
        root.join(".venv/Scripts/python.exe")
    } else {
        root.join(".venv/bin/python")
    };
    let mut command = Command::new(python);
    command
        .args(["-m", "src.backend.serve", "--watch-stdin"])
        .current_dir(&root)
        .env("APP_CORS_ORIGINS", "http://localhost:5173");
    Ok(Launch {
        command,
        log_dir: None,
    })
}

/// A packaged app runs the bundled backend (scripts/build_desktop.py)
/// and keeps the user's data in the OS's per-user app-data folder.
#[cfg(not(debug_assertions))]
fn launch_command(app: &AppHandle) -> Result<Launch, Box<dyn std::error::Error>> {
    let dir = app.path().resource_dir()?.join("backend");
    let name = if cfg!(windows) {
        "stacks-backend.exe"
    } else {
        "stacks-backend"
    };
    let data_dir = app.path().app_local_data_dir()?;
    std::fs::create_dir_all(&data_dir)?;
    let mut command = Command::new(dir.join(name));
    command
        .arg("--watch-stdin")
        .current_dir(&dir)
        .env("APP_DATA_DIR", &data_dir)
        .env("APP_ENV", "production");
    Ok(Launch {
        command,
        log_dir: Some(data_dir),
    })
}

fn new_token() -> Result<String, getrandom::Error> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn watch_startup(stdout: impl Read, token: String, log_dir: Option<String>, status: SharedStatus) {
    let mut lines = BufReader::new(stdout).lines();
    let port = lines.by_ref().map_while(Result::ok).find_map(|line| {
        line.trim()
            .strip_prefix(PORT_ANNOUNCEMENT)
            .and_then(|port| port.parse::<u16>().ok())
    });
    let outcome = match port {
        None => Status::Failed(failure("the backend exited before it started", &log_dir)),
        Some(port) if wait_healthy(port, &token) => Status::Ready(BackendInfo {
            url: format!("http://127.0.0.1:{port}"),
            token,
            log_dir: log_dir.clone(),
        }),
        Some(_) => Status::Failed(failure("the backend did not answer in time", &log_dir)),
    };
    let (lock, ready) = &*status;
    if let Ok(mut current) = lock.lock() {
        *current = outcome;
        ready.notify_all();
    }
    // Keep draining stdout so the backend never blocks on a full pipe.
    for line in lines.map_while(Result::ok) {
        if cfg!(debug_assertions) {
            println!("[backend] {line}");
        }
    }
}

fn failure(reason: &str, log_dir: &Option<String>) -> String {
    match log_dir {
        Some(dir) => format!(
            "{reason}. Details are in {}",
            PathBuf::from(dir).join("backend.log").display()
        ),
        None => reason.to_string(),
    }
}

fn wait_healthy(port: u16, token: &str) -> bool {
    let deadline = Instant::now() + START_TIMEOUT;
    while Instant::now() < deadline {
        if healthy(port, token) {
            return true;
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
}

fn healthy(port: u16, token: &str) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(1)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(10)));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-App-Token: {token}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut status_line = String::new();
    BufReader::new(stream).read_line(&mut status_line).is_ok()
        && status_line.starts_with("HTTP/1.1 200")
}
