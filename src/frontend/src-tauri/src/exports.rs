use getrandom::fill as random_fill;
use serde::Serialize;
use std::fs::{self, Metadata, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::SystemTime;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};

const EXTENSIONS: &[&str] = &[
    "c", "cpp", "csv", "css", "docx", "go", "html", "java", "jl", "js", "m", "md", "pptx", "py",
    "r", "rs", "sql", "ts", "txt", "xlsx",
];

#[derive(Debug, Clone, PartialEq, Eq)]
struct TargetSnapshot {
    len: u64,
    modified: Option<SystemTime>,
    #[cfg(unix)]
    device: u64,
    #[cfg(unix)]
    inode: u64,
}

fn snapshot_metadata(metadata: &Metadata) -> TargetSnapshot {
    #[cfg(unix)]
    use std::os::unix::fs::MetadataExt;

    TargetSnapshot {
        len: metadata.len(),
        modified: metadata.modified().ok(),
        #[cfg(unix)]
        device: metadata.dev(),
        #[cfg(unix)]
        inode: metadata.ino(),
    }
}

#[derive(Serialize)]
pub struct SavedExport {
    pub path: String,
    pub filename: String,
}

fn safe_filename(input: &str) -> Result<(String, &'static str), String> {
    let basename = input.rsplit(['/', '\\']).next().unwrap_or_default();
    let mut clean: String = basename
        .chars()
        .filter(|character| {
            !character.is_control()
                && !matches!(*character, '<' | '>' | ':' | '"' | '|' | '?' | '*')
        })
        .collect();
    clean = clean.trim().trim_end_matches('.').to_owned();
    if clean.is_empty() || clean == "." || clean == ".." {
        return Err("The export filename is invalid.".into());
    }
    let extension = Path::new(&clean)
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
        .ok_or_else(|| "The export filename has no supported extension.".to_owned())?;
    let supported = EXTENSIONS
        .iter()
        .copied()
        .find(|candidate| *candidate == extension)
        .ok_or_else(|| format!("The .{extension} export format is not supported."))?;
    let stem = clean.split('.').next().unwrap_or_default();
    if ["CON", "PRN", "AUX", "NUL"]
        .iter()
        .any(|device| stem.eq_ignore_ascii_case(device))
        || [
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
            "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        ]
        .iter()
        .any(|device| stem.eq_ignore_ascii_case(device))
    {
        return Err("The export filename is reserved by the operating system.".into());
    }
    Ok((clean, supported))
}

fn unique_temp_path(parent: &Path, filename: &str) -> Result<PathBuf, String> {
    for _ in 0..8 {
        let mut random = [0_u8; 16];
        random_fill(&mut random)
            .map_err(|error| format!("Could not create a temporary export name: {error}"))?;
        let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let candidate = parent.join(format!(".{filename}.export-{suffix}.tmp"));
        if !candidate.exists() {
            return Ok(candidate);
        }
    }
    Err("Could not reserve a temporary export file.".into())
}

fn target_snapshot(path: &Path) -> Result<Option<TargetSnapshot>, String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            Err("The selected destination is a symbolic link and cannot be replaced.".into())
        }
        Ok(metadata) if !metadata.is_file() => {
            Err("The selected destination is not a regular file.".into())
        }
        Ok(metadata) => Ok(Some(snapshot_metadata(&metadata))),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!(
            "Could not inspect the selected destination: {error}"
        )),
    }
}

fn remove_reserved(path: &Path, reservation: &TargetSnapshot) {
    if target_snapshot(path).ok().flatten().as_ref() == Some(reservation) {
        let _ = fs::remove_file(path);
    }
}

fn write_export(
    path: &Path,
    filename: &str,
    data: &[u8],
    confirmed_target: Option<TargetSnapshot>,
) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "The selected destination has no parent folder.".to_owned())?;
    if target_snapshot(path)? != confirmed_target {
        return Err(
            "The selected destination changed while the export was being saved. Please try again."
                .into(),
        );
    }

    // New paths are reserved exclusively. For an existing file, keep its
    // pre-confirmation identity and leave it untouched until the final rename.
    let reservation = if confirmed_target.is_some() {
        None
    } else {
        let reserved = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|error| format!("Could not reserve the selected destination: {error}"))?
            .metadata()
            .map(|metadata| snapshot_metadata(&metadata))
            .map_err(|error| format!("Could not inspect the reserved destination: {error}"))?;
        Some(reserved)
    };
    let rename_target = confirmed_target.as_ref().or(reservation.as_ref());

    let temp_path = match unique_temp_path(parent, filename) {
        Ok(path) => path,
        Err(error) => {
            if let Some(reservation) = &reservation {
                remove_reserved(path, reservation);
            }
            return Err(error);
        }
    };
    let result = (|| {
        let mut temp = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)
            .map_err(|error| format!("Could not create the temporary export file: {error}"))?;
        temp.write_all(data)
            .and_then(|_| temp.sync_all())
            .map_err(|error| format!("Could not write the export: {error}"))?;
        drop(temp);

        // Recheck the target immediately before replacing it to reject a link
        // or non-file that appeared after the user's dialog confirmation.
        if target_snapshot(path)?.as_ref() != rename_target {
            return Err(
                "The selected destination changed while the export was being saved. Please try again."
                    .into(),
            );
        }
        fs::rename(&temp_path, path)
            .map_err(|error| format!("Could not finish saving the export: {error}"))
    })();

    if result.is_err() {
        let _ = fs::remove_file(&temp_path);
        if let Some(reservation) = &reservation {
            remove_reserved(path, reservation);
        }
    }
    result
}

fn export_path(path: PathBuf, extension: &str) -> PathBuf {
    let existing = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("");
    // A dotted name ("week3.final", "notes.v2") is a name, not a type: only a
    // known extension is replaced, anything else gets ours appended (R4-NEW-j).
    if existing.eq_ignore_ascii_case(extension) {
        path
    } else if EXTENSIONS
        .iter()
        .any(|known| existing.eq_ignore_ascii_case(known))
    {
        path.with_extension(extension)
    } else {
        let mut name = path.into_os_string();
        name.push(".");
        name.push(extension);
        PathBuf::from(name)
    }
}

fn choose_and_write(
    app: tauri::AppHandle,
    filename: String,
    extension: &'static str,
    data: Vec<u8>,
) -> Result<Option<SavedExport>, String> {
    let Some(file_path) = app
        .dialog()
        .file()
        .set_file_name(&filename)
        .add_filter(extension.to_uppercase(), &[extension])
        .blocking_save_file()
    else {
        return Ok(None);
    };
    let path = file_path
        .into_path()
        .map_err(|error| format!("Could not use the selected destination: {error}"))?;
    let path = export_path(path, extension);
    let confirmed_target = target_snapshot(&path)?;
    if confirmed_target.is_some() {
        let replace = app
            .dialog()
            .message(format!("Replace the existing file?\n{}", path.display()))
            .title("Confirm export replacement")
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Replace".into(),
                "Cancel".into(),
            ))
            .blocking_show();
        if !replace {
            return Ok(None);
        }
    }
    write_export(&path, &filename, &data, confirmed_target)?;
    Ok(Some(SavedExport {
        path: path.to_string_lossy().into_owned(),
        filename: path
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or(&filename)
            .to_owned(),
    }))
}

#[tauri::command]
pub async fn save_export(
    app: tauri::AppHandle,
    filename: String,
    data: Vec<u8>,
) -> Result<Option<SavedExport>, String> {
    let (filename, extension) = safe_filename(&filename)?;
    tauri::async_runtime::spawn_blocking(move || choose_and_write(app, filename, extension, data))
        .await
        .map_err(|error| format!("Could not finish the export operation: {error}"))?
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_directory() -> PathBuf {
        let mut random = [0_u8; 12];
        random_fill(&mut random).unwrap();
        let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("stacks-export-test-{suffix}"));
        fs::create_dir(&path).unwrap();
        path
    }

    #[test]
    fn filenames_are_basenames_with_backend_code_extensions_and_reserved_stems_rejected() {
        assert_eq!(
            safe_filename(r"C:\private\lesson.py").unwrap(),
            ("lesson.py".into(), "py")
        );
        assert_eq!(safe_filename("source.rs").unwrap().1, "rs");
        assert!(safe_filename("CON.md").is_err());
        assert!(safe_filename("notes.exe").is_err());
    }

    #[test]
    fn dotted_names_keep_their_name_and_known_types_are_replaced() {
        assert_eq!(export_path(PathBuf::from("week3"), "md"), PathBuf::from("week3.md"));
        assert_eq!(
            export_path(PathBuf::from("week3.md"), "md"),
            PathBuf::from("week3.md")
        );
        assert_eq!(
            export_path(PathBuf::from("notes.txt"), "md"),
            PathBuf::from("notes.md")
        );
        assert_eq!(
            export_path(PathBuf::from("week3.final"), "md"),
            PathBuf::from("week3.final.md")
        );
        assert_eq!(
            export_path(PathBuf::from("notes.v2"), "md"),
            PathBuf::from("notes.v2.md")
        );
    }

    #[test]
    fn write_creates_exclusively_and_replaces_only_the_confirmed_file() {
        let directory = test_directory();
        let target = directory.join("notes.md");
        write_export(&target, "notes.md", b"first", None).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"first");

        let confirmed = target_snapshot(&target).unwrap();
        write_export(&target, "notes.md", b"replacement", confirmed.clone()).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"replacement");

        fs::write(&target, b"changed after confirmation").unwrap();
        assert!(write_export(&target, "notes.md", b"must not replace", confirmed).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"changed after confirmation");
        fs::remove_dir_all(directory).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn target_inspection_rejects_symbolic_links() {
        use std::os::unix::fs::symlink;

        let directory = test_directory();
        let target = directory.join("linked.md");
        symlink(directory.join("missing.md"), &target).unwrap();
        assert!(target_snapshot(&target).is_err());
        fs::remove_dir_all(directory).unwrap();
    }
}
