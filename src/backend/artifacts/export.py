"""Artifacts as files: Word, Excel, PowerPoint, Markdown, CSV (plan §4.3).

Every export ends with the artifact's sources — "[n] file, page" — so a
citation still means something once the file leaves the app. A doc is
Markdown, parsed with markdown-it into real Word headings, lists, tables
and code; math stays as its LaTeX source (Word has no safe equivalent).
"""

from __future__ import annotations

import csv
import html
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

FORMATS: dict[str, tuple[str, ...]] = {
    "doc": ("docx", "md"),
    "sheet": ("xlsx", "csv"),
    "slides": ("pptx", "md"),
    "quiz": ("md",),
    "flashcards": ("csv", "md"),
    "code": ("txt",),
    "chart": ("html",),
}
_CODE_EXTENSIONS = {
    "python": "py",
    "py": "py",
    "javascript": "js",
    "js": "js",
    "typescript": "ts",
    "ts": "ts",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "c++": "cpp",
    "r": "r",
    "sql": "sql",
    "html": "html",
    "css": "css",
    "rust": "rs",
    "go": "go",
    "matlab": "m",
    "julia": "jl",
}
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MD = MarkdownIt("commonmark").enable("table").enable("strikethrough")
# A chart is model-written HTML. In the app it is sanitized (DOMPurify);
# in an exported file nothing sanitizes it, so scripts, inline handlers
# and javascript: URLs are removed here.
_SCRIPT = re.compile(r"<\s*script\b.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)
_HANDLER = re.compile(r"\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_URL = re.compile(r"javascript:", re.IGNORECASE)


@dataclass(frozen=True)
class SourceLabel:
    number: int
    filename: str
    label: str


def safe_stem(title: str) -> str:
    return _UNSAFE.sub("_", title).strip(" .")[:120] or "artifact"


def unique_path(directory: Path, stem: str, extension: str) -> Path:
    candidate = directory / f"{stem}.{extension}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}).{extension}"
        counter += 1
    return candidate


def extension_for(kind: str, fmt: str, content: dict[str, Any]) -> str:
    if kind == "code":
        return _CODE_EXTENSIONS.get(str(content.get("language", "")).lower(), "txt")
    return fmt


def _source_lines(sources: Sequence[SourceLabel]) -> list[str]:
    return [f"[{s.number}] {s.filename}, {s.label}" for s in sources]


# --- Markdown ---


def _slides_markdown(title: str, content: dict[str, Any]) -> str:
    parts = [f"# {title}"]
    for slide in content.get("slides", []):
        parts.append(
            f"## {slide.get('title') or 'Slide'}\n\n{slide.get('body', '')}".rstrip()
        )
        if slide.get("notes"):
            parts.append(f"> Notes: {slide['notes']}")
    return "\n\n---\n\n".join(parts)


def _quiz_markdown(title: str, content: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    for number, question in enumerate(content.get("questions", []), start=1):
        cited = "".join(f"[{n}]" for n in question.get("sources", []))
        lines.append(f"**{number}. {question['prompt']}** {cited}".rstrip())
        for index, option in enumerate(question["options"]):
            lines.append(f"- {'ABCDEFGH'[index]}. {option}")
        lines.append("")
    lines.append("## Answers")
    for number, question in enumerate(content.get("questions", []), start=1):
        answer = "ABCDEFGH"[question["answer"]]
        explanation = (
            f" — {question['explanation']}" if question.get("explanation") else ""
        )
        lines.append(f"{number}. {answer}{explanation}")
    return "\n".join(lines)


def _cards_markdown(title: str, content: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    for card in content.get("cards", []):
        cited = "".join(f"[{n}]" for n in card.get("sources", []))
        lines.append(f"**{card['front']}**  \n{card['back']} {cited}".rstrip())
        lines.append("")
    return "\n".join(lines)


def to_markdown(
    kind: str, title: str, content: dict[str, Any], sources: Sequence[SourceLabel]
) -> str:
    if kind == "doc":
        body = str(content.get("markdown", "")).rstrip()
        if not body.lstrip().startswith("#"):
            body = f"# {title}\n\n{body}"
    elif kind == "slides":
        body = _slides_markdown(title, content)
    elif kind == "quiz":
        body = _quiz_markdown(title, content)
    elif kind == "flashcards":
        body = _cards_markdown(title, content)
    else:
        raise ValueError(f"no Markdown export for {kind}")
    if sources:
        body += "\n\n## Sources\n\n" + "\n".join(
            f"- {line}" for line in _source_lines(sources)
        )
    return body + "\n"


# --- CSV / Excel ---


def _table(kind: str, content: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    if kind == "sheet":
        return list(content.get("columns", [])), [
            list(r) for r in content.get("rows", [])
        ]
    if kind == "flashcards":
        return ["Front", "Back"], [
            [c["front"], c["back"]] for c in content.get("cards", [])
        ]
    raise ValueError(f"no table export for {kind}")


def to_csv(kind: str, content: dict[str, Any]) -> str:
    columns, rows = _table(kind, content)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns)
    writer.writerows(rows)
    return out.getvalue()


def to_xlsx(
    title: str, content: dict[str, Any], sources: Sequence[SourceLabel]
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = safe_stem(title)[:31] or "Sheet"
    columns, rows = _table("sheet", content)
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    for index, column in enumerate(columns, start=1):
        width = max([len(column), *(len(r[index - 1]) for r in rows)])
        sheet.column_dimensions[get_column_letter(index)].width = min(
            max(width + 2, 8), 60
        )
    sheet.freeze_panes = "A2"
    if sources:
        cited = book.create_sheet("Sources")
        cited.append(["#", "File", "Where"])
        for cell in cited[1]:
            cell.font = Font(bold=True)
        for source in sources:
            cited.append([source.number, source.filename, source.label])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


# --- Word ---


def _add_inline(paragraph: Any, token: Token | None) -> None:
    if token is None or not token.children:
        return
    bold = italic = strike = False
    for child in token.children:
        if child.type == "strong_open":
            bold = True
        elif child.type == "strong_close":
            bold = False
        elif child.type == "em_open":
            italic = True
        elif child.type == "em_close":
            italic = False
        elif child.type == "s_open":
            strike = True
        elif child.type == "s_close":
            strike = False
        elif child.type in ("softbreak",):
            paragraph.add_run(" ")
        elif child.type == "hardbreak":
            paragraph.add_run().add_break()
        elif child.type == "code_inline":
            run = paragraph.add_run(child.content)
            run.font.name = "Consolas"
        elif child.type == "image":
            paragraph.add_run(child.content or "[image]")
        elif child.type == "text" and child.content:
            run = paragraph.add_run(child.content)
            run.bold, run.italic, run.font.strike = bold, italic, strike


def _add_table(document: Any, tokens: list[Token], start: int) -> int:
    rows: list[list[Token | None]] = []
    index = start
    while tokens[index].type != "table_close":
        token = tokens[index]
        if token.type == "tr_open":
            rows.append([])
        elif token.type == "inline" and rows:
            rows[-1].append(token)
        index += 1
    width = max((len(r) for r in rows), default=0)
    if width:
        table = document.add_table(rows=len(rows), cols=width)
        table.style = "Table Grid"
        for r, row in enumerate(rows):
            for c in range(width):
                cell_paragraph = table.cell(r, c).paragraphs[0]
                _add_inline(cell_paragraph, row[c] if c < len(row) else None)
                if r == 0:
                    for run in cell_paragraph.runs:
                        run.bold = True
    return index


def to_docx(title: str, markdown: str, sources: Sequence[SourceLabel]) -> bytes:
    from docx import Document

    document = Document()
    document.core_properties.title = title
    tokens = _MD.parse(markdown)
    if not markdown.lstrip().startswith("#"):
        document.add_heading(title, level=0)
    lists: list[str] = []
    quote = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.type
        if kind == "heading_open":
            level = int(token.tag[1])
            heading = document.add_heading("", level=min(level, 9) if level > 1 else 1)
            _add_inline(heading, tokens[index + 1])
            index += 3
            continue
        if kind in ("bullet_list_open", "ordered_list_open"):
            lists.append("List Bullet" if kind == "bullet_list_open" else "List Number")
        elif kind in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif kind == "blockquote_open":
            quote += 1
        elif kind == "blockquote_close":
            quote -= 1
        elif kind == "paragraph_open":
            if lists:
                depth = len(lists)
                style = lists[-1] + (f" {depth}" if depth > 1 else "")
            elif quote:
                style = "Quote"
            else:
                style = None
            try:
                paragraph = document.add_paragraph(style=style)
            except KeyError:
                paragraph = document.add_paragraph(style=lists[-1] if lists else None)
            _add_inline(paragraph, tokens[index + 1])
            index += 3
            continue
        elif kind in ("fence", "code_block"):
            for line in token.content.rstrip("\n").split("\n"):
                run = document.add_paragraph().add_run(line)
                run.font.name = "Consolas"
        elif kind == "table_open":
            index = _add_table(document, tokens, index)
        elif kind == "hr":
            document.add_paragraph("")
        index += 1
    if sources:
        document.add_heading("Sources", level=1)
        for line in _source_lines(sources):
            document.add_paragraph(line)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


# --- PowerPoint ---

_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)(.+?)\1")


def _plain(text: str) -> str:
    return _EMPHASIS.sub(r"\2", text).strip()


def to_pptx(
    title: str, content: dict[str, Any], sources: Sequence[SourceLabel]
) -> bytes:
    from pptx import Presentation
    from pptx.util import Pt

    deck = Presentation()
    cover = deck.slides.add_slide(deck.slide_layouts[0])
    if cover.shapes.title is not None:
        cover.shapes.title.text = title
    for slide in content.get("slides", []):
        page = deck.slides.add_slide(deck.slide_layouts[1])
        if page.shapes.title is not None:
            page.shapes.title.text = _plain(slide.get("title", ""))
        body = page.placeholders[1].text_frame
        body.clear()
        first = True
        for line in str(slide.get("body", "")).splitlines():
            if not line.strip():
                continue
            match = _LIST_ITEM.match(line)
            text, level = (
                (match.group(2), min(len(match.group(1)) // 2, 4))
                if match
                else (line, 0)
            )
            paragraph = body.paragraphs[0] if first else body.add_paragraph()
            paragraph.text = _plain(text.lstrip("# "))
            paragraph.level = level
            first = False
        if slide.get("notes"):
            page.notes_slide.notes_text_frame.text = slide["notes"]
    if sources:
        page = deck.slides.add_slide(deck.slide_layouts[1])
        if page.shapes.title is not None:
            page.shapes.title.text = "Sources"
        body = page.placeholders[1].text_frame
        body.clear()
        for number, line in enumerate(_source_lines(sources)):
            paragraph = body.paragraphs[0] if number == 0 else body.add_paragraph()
            paragraph.text = line
            for run in paragraph.runs:
                run.font.size = Pt(14)
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def chart_html(title: str, body: str, sources: Sequence[SourceLabel]) -> str:
    safe = _JS_URL.sub("", _HANDLER.sub("", _SCRIPT.sub("", body)))
    cited = "".join(f"<li>{html.escape(line)}</li>" for line in _source_lines(sources))
    footer = f"<h2>Sources</h2><ol>{cited}</ol>" if sources else ""
    return (
        f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"{safe}{footer}"
    )


# --- dispatch ---


def render(
    kind: str,
    fmt: str,
    title: str,
    content: dict[str, Any],
    sources: Sequence[SourceLabel],
) -> bytes:
    if fmt not in FORMATS.get(kind, ()):
        raise ValueError(f"a {kind} can't be exported as .{fmt}")
    if fmt == "docx":
        return to_docx(title, str(content.get("markdown", "")), sources)
    if fmt == "xlsx":
        return to_xlsx(title, content, sources)
    if fmt == "pptx":
        return to_pptx(title, content, sources)
    if fmt == "md":
        return to_markdown(kind, title, content, sources).encode("utf-8")
    if fmt == "csv":
        return to_csv(kind, content).encode("utf-8-sig")
    if fmt == "txt":
        return str(content.get("code", "")).encode("utf-8")
    if fmt == "html":
        return chart_html(title, str(content.get("html", "")), sources).encode("utf-8")
    raise ValueError(f"unknown format: {fmt}")
