"""Extract a working file in memory, without ingestion or knowledge/memory writes."""

import io
from pathlib import PurePath

from src.backend.common.companion_config import load_companion_policy
from src.backend.common.schemas.work import DocumentInput
from src.backend.office_reader.package import read_package


def read_work_file(filename: str, data: bytes) -> DocumentInput:
    if len(data) > load_companion_policy().max_upload_bytes:
        raise ValueError("This working file is too large (maximum 20 MB).")
    title = PurePath(filename.replace("\\", "/")).name[:300] or "Document"
    extension = PurePath(title).suffix.casefold()
    warnings: list[str] = []
    if extension in {".docx", ".pptx", ".xlsx"}:
        kind = {".docx": "word", ".pptx": "powerpoint", ".xlsx": "excel"}[extension]
        read = read_package(data, kind=kind, host=title)
        text = "\n\n".join(f"{u.label}\n{u.text}" for u in read.units)
        warnings = list(read.warnings)
        warnings.append(
            "Text extraction does not include every image, comment, or embedded object."
        )
    elif extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Unlock this PDF before connecting it.")
        pages = []
        readable = False
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            readable = readable or bool(page_text.strip())
            if not page_text.strip():
                warnings.append(
                    f"Page {i + 1} has no readable text; connect a text version or use "
                    f"screen capture."
                )
            pages.append(f"Page {i + 1}\n{page_text}")
        if not readable:
            raise ValueError(
                "This PDF has no readable text. "
                "Connect a text version or capture its pages."
            )
        text = "\n\n".join(pages)
    elif extension in {".txt", ".md", ".csv"}:
        text = data.decode("utf-8-sig")
    else:
        raise ValueError(
            "Connect a PDF, DOCX, PPTX, XLSX, Markdown, CSV, or UTF-8 text file."
        )
    if not text.strip() or len(text) > load_companion_policy().max_document_chars:
        raise ValueError(
            "The file has no readable text or exceeds the 300,000 character limit."
        )
    return DocumentInput(
        title=title,
        text=text,
        origin="file",
        coverage="partial" if warnings else "document",
        warnings=warnings,
    )
