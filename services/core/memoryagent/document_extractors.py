"""Text extraction for supported local document formats."""

from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader
from docx import Document

logger = logging.getLogger(__name__)

MAX_BYTES_BY_SUFFIX: dict[str, int] = {
    ".md": 2 * 1024 * 1024,
    ".txt": 2 * 1024 * 1024,
    ".pdf": 25 * 1024 * 1024,
    ".docx": 25 * 1024 * 1024,
}


def extract_text_from_path(path: Path) -> tuple[str, str]:
    """
    Return (text, source_kind) from a supported file path.
    Supported: .md, .txt, .pdf, .docx
    """
    p = path.expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    suf = p.suffix.lower()
    _validate_size_limit(p, suf)
    if suf in (".md", ".txt"):
        return _read_text_lossy_utf8(p), "file"
    if suf == ".pdf":
        text = _extract_pdf_text(p)
        return text, "file_pdf"
    if suf == ".docx":
        text = _extract_docx_text(p)
        return text, "file_docx"
    raise ValueError(f"unsupported file type: {suf}")


def _read_text_lossy_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        logger.warning(
            "text_decode_failed path=%s encoding=utf-8 byte_offset=%s; "
            "ingesting with replacement characters",
            path,
            e.start,
        )
        return path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text() or ""
        if t.strip():
            parts.append(t.strip())
    merged = "\n\n".join(parts).strip()
    if not merged:
        raise ValueError(
            "PDF has no extractable text (possibly scanned image-only or encrypted)."
        )
    return merged


def _extract_docx_text(path: Path) -> str:
    doc = Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    merged = "\n\n".join(paragraphs).strip()
    if not merged:
        raise ValueError("DOCX has no extractable paragraph text.")
    return merged


def _validate_size_limit(path: Path, suffix: str) -> None:
    max_bytes = MAX_BYTES_BY_SUFFIX.get(suffix)
    if max_bytes is None:
        return
    size_bytes = int(path.stat().st_size)
    if size_bytes > max_bytes:
        raise ValueError(
            f"{suffix} file exceeds max size ({size_bytes} > {max_bytes} bytes)."
        )
