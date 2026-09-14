"""Multi-format file text extraction.

Supports PDF, DOCX, XLSX, CSV, HTML, and plain text. Each extractor returns
clean text suitable for chunking and embedding. All extractors enforce a size
ceiling and gracefully degrade (return empty string) on corrupt/unreadable input
rather than crashing the caller.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 50_000_000  # 50 MB hard ceiling
MAX_PDF_PAGES = 100
MAX_SPREADSHEET_ROWS = 5000


def extract_text(data: bytes, filename: str, content_type: str = "") -> str:
    """Dispatch to the correct extractor based on extension then content-type."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(
            f"File exceeds {MAX_FILE_BYTES // 1_000_000} MB limit "
            f"({len(data) // 1_000_000} MB)"
        )
    ext = Path(filename).suffix.lower()
    if ext == ".doc" or content_type == "application/msword":
        raise ValueError(
            "Legacy binary .doc files are not supported. Please convert to .docx or .pdf."
        )
    if ext == ".pdf" or content_type == "application/pdf":
        return _extract_pdf(data)
    if ext == ".docx" or content_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return _extract_docx(data)
    if ext == ".xlsx" or content_type in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        return _extract_xlsx(data)
    if ext == ".csv" or content_type == "text/csv":
        return _extract_csv(data)
    if ext in (".html", ".htm") or content_type.startswith("text/html"):
        return _extract_html(data)
    # Fallback: treat as plain text (covers .txt, .md, .json, .yaml, etc.)
    return _extract_text(data)


def _extract_pdf(data: bytes) -> str:
    try:
        import pypdf
    except ImportError:
        logger.warning("pypdf not installed; cannot extract PDF text")
        return ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for idx, page in enumerate(reader.pages):
            if idx >= MAX_PDF_PAGES:
                break
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        return "\n\n".join(pages)
    except Exception:
        logger.warning("PDF extraction failed", exc_info=True)
        return ""


def _extract_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError:
        logger.warning("python-docx not installed; cannot extract DOCX text")
        return ""
    try:
        doc = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception:
        logger.warning("DOCX extraction failed", exc_info=True)
        return ""


def _extract_xlsx(data: bytes) -> str:
    try:
        import openpyxl
    except ImportError:
        logger.warning("openpyxl not installed; cannot extract XLSX text")
        return ""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines: list[str] = []
        for sheet in wb.sheetnames:
            if len(lines) >= MAX_SPREADSHEET_ROWS:
                break
            ws = wb[sheet]
            for row in ws.iter_rows(values_only=True):
                if len(lines) >= MAX_SPREADSHEET_ROWS:
                    break
                cells = [str(c) if c is not None else "" for c in row]
                if any(cells):
                    lines.append("\t".join(cells))
        wb.close()
        return "\n".join(lines)
    except Exception:
        logger.warning("XLSX extraction failed", exc_info=True)
        return ""


def _extract_csv(data: bytes) -> str:
    try:
        text = data.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        lines: list[str] = []
        for idx, row in enumerate(reader):
            if idx >= MAX_SPREADSHEET_ROWS:
                break
            if any(cell.strip() for cell in row):
                lines.append("\t".join(row))
        return "\n".join(lines)
    except Exception:
        logger.warning("CSV extraction failed", exc_info=True)
        return ""


def _extract_html(data: bytes) -> str:
    from .scraper import extract_text_from_html

    html = data.decode("utf-8", errors="replace")
    _title, text = extract_text_from_html(html)
    return text


def _extract_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")
