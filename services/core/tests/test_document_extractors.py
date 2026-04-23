"""Unit tests for document text extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryagent.document_extractors import extract_text_from_path


def test_extract_text_md(data_dir: Path) -> None:
    f = data_dir / "a.md"
    f.write_text("# Title\nhello\n", encoding="utf-8")
    text, kind = extract_text_from_path(f)
    assert "hello" in text
    assert kind == "file"


def test_extract_text_pdf_via_mock(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = data_dir / "a.pdf"
    f.write_bytes(b"%PDF-1.4\n% fake")

    class _P:
        def __init__(self, t: str) -> None:
            self._t = t

        def extract_text(self) -> str:
            return self._t

    class _R:
        def __init__(self, _path: str) -> None:
            self.pages = [_P("PDF hello"), _P("world")]

    monkeypatch.setattr("memoryagent.document_extractors.PdfReader", _R)
    text, kind = extract_text_from_path(f)
    assert "PDF hello" in text
    assert "world" in text
    assert kind == "file_pdf"


def test_extract_text_pdf_no_text_raises(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = data_dir / "empty.pdf"
    f.write_bytes(b"%PDF-1.4\n% fake")

    class _P:
        def extract_text(self) -> str:
            return ""

    class _R:
        def __init__(self, _path: str) -> None:
            self.pages = [_P()]

    monkeypatch.setattr("memoryagent.document_extractors.PdfReader", _R)
    with pytest.raises(ValueError):
        extract_text_from_path(f)


def test_extract_text_docx_via_mock(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = data_dir / "a.docx"
    f.write_bytes(b"fake")

    class _Para:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Doc:
        def __init__(self, _path: str) -> None:
            self.paragraphs = [_Para("Docx hello"), _Para("  "), _Para("world")]

    monkeypatch.setattr("memoryagent.document_extractors.Document", _Doc)
    text, kind = extract_text_from_path(f)
    assert "Docx hello" in text
    assert "world" in text
    assert kind == "file_docx"


def test_extract_text_docx_no_text_raises(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = data_dir / "empty.docx"
    f.write_bytes(b"fake")

    class _Para:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Doc:
        def __init__(self, _path: str) -> None:
            self.paragraphs = [_Para(""), _Para(" ")]

    monkeypatch.setattr("memoryagent.document_extractors.Document", _Doc)
    with pytest.raises(ValueError):
        extract_text_from_path(f)


def test_extract_text_size_guardrail(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = data_dir / "too_big.md"
    f.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(
        "memoryagent.document_extractors.MAX_BYTES_BY_SUFFIX",
        {".md": 1},
    )
    with pytest.raises(ValueError):
        extract_text_from_path(f)
