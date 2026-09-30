"""Explicit, bounded capture; no continuous monitoring or document mutation."""

import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.db import connection
from src.backend.common.schemas.work import DocumentInput
from src.backend.office_reader.screens import read_screens


class CaptureUnavailableError(ValueError):
    pass


class CaptureWindow(BaseModel):
    handle: int = Field(gt=0)
    process_id: int = Field(gt=0)
    title: str
    application: str = ""


def _run(*arguments: str) -> Any:
    if sys.platform != "win32":
        raise CaptureUnavailableError(
            "Window capture currently supports Windows. Use a file, paste, or "
            "the Office bridge on this platform."
        )
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(Path(__file__).with_name("capture_windows.ps1")),
                *arguments,
            ],
            capture_output=True,
            timeout=load_companion_policy().capture_timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode:
            raise CaptureUnavailableError(
                "The application could not be read. Refresh the window list or "
                "connect its file instead."
            )
        return json.loads(completed.stdout.decode("utf-8-sig"))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        raise CaptureUnavailableError(
            "The application did not respond to capture. Connect its file or "
            "paste the document instead."
        ) from err


def list_windows() -> list[CaptureWindow]:
    return [CaptureWindow.model_validate(w) for w in _run("-Mode", "list")]


def capture(window: CaptureWindow) -> DocumentInput:
    current = next(
        (
            w
            for w in list_windows()
            if w.handle == window.handle
            and w.process_id == window.process_id
            and w.title == window.title
        ),
        None,
    )
    if not current:
        raise CaptureUnavailableError(
            "That window changed or closed. Refresh and choose it again."
        )
    raw = _run(
        "-Mode",
        "read",
        "-WindowHandle",
        str(current.handle),
        "-ExpectedProcess",
        str(current.process_id),
    )
    if raw["limited"]:
        raise CaptureUnavailableError(
            "The application exposes too much text. Connect the document file instead."
        )
    text = raw["text"]
    origin: Literal["accessibility", "screen"] = "accessibility"
    warnings = [
        "Application-exposed text may omit pages, images, or canvas "
        "content. Check the captured text before relying on it."
    ]
    if not text and raw["image"]:
        with connection() as conn:
            read = read_screens(
                conn, [base64.b64decode(raw["image"])], host=current.title
            )
        text = read.text
        origin = "screen"
        warnings = [
            "Window rendering contains only rendered pixels. "
            "It cannot read off-screen pages; "
            "OCR may misread text."
        ]
    if not text.strip():
        raise CaptureUnavailableError(
            "No readable document text was found. Connect the file or paste "
            "the document."
        )
    return DocumentInput(
        title=current.title[:300],
        text=text,
        origin=origin,
        external_id=f"window:{current.handle}:{current.process_id}",
        coverage="partial",
        warnings=warnings,
    )
