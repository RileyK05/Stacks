import io
from pathlib import PurePath

from PIL import Image, UnidentifiedImageError
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.schemas.work import DocumentInput
from src.backend.office_reader.screens import read_screens


def read_work_screenshot(filename: str, data: bytes) -> DocumentInput:
    policy = load_companion_policy()
    if len(data) > policy.max_upload_bytes:
        raise ValueError("This screenshot exceeds the 20 MB limit.")
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in {"PNG", "JPEG"}:
                raise ValueError("Connect a PNG or JPEG screenshot.")
            if picture.width * picture.height > policy.max_screenshot_pixels:
                raise ValueError("This screenshot exceeds the image dimension limit.")
            picture.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as err:
        raise ValueError(
            "This screenshot is not a readable PNG or JPEG image."
        ) from err
    result = read_screens([data], host="Uploaded screenshot")
    text = "\n\n".join(unit.text for unit in result.units)
    if not text.strip():
        raise ValueError("No readable text was found in this screenshot.")
    if len(text) > policy.max_document_chars:
        raise ValueError("The screenshot text exceeds the document character limit.")
    return DocumentInput(
        title=PurePath(filename.replace("\\", "/")).name[:300] or "Screenshot",
        text=text,
        origin="screen",
        coverage="partial",
        warnings=[
            "Only the uploaded screenshot was read; off-screen content is missing.",
            "Image transcription may misread text, formulas, or layout. Inspect it.",
        ],
    )
