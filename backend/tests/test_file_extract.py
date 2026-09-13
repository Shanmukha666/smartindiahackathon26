from __future__ import annotations

import pytest

from app.file_extract import MAX_FILE_BYTES, extract_text


def test_extract_plain_text() -> None:
    data = b"Section 1. The formulation uses neem extract."
    result = extract_text(data, "notes.txt")
    assert "neem extract" in result


def test_extract_html_strips_tags() -> None:
    html = b"<html><body><nav>Menu</nav><p>Actual content</p></body></html>"
    result = extract_text(html, "page.html")
    assert "Actual content" in result
    assert "Menu" not in result


def test_extract_csv() -> None:
    csv_data = b"Name,Value\nNeem,100\nTurmeric,200\n"
    result = extract_text(csv_data, "data.csv")
    assert "Neem" in result
    assert "Turmeric" in result


def test_extract_rejects_oversized_file() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        extract_text(b"x" * (MAX_FILE_BYTES + 1), "huge.txt")


def test_extract_unknown_extension_falls_back_to_text() -> None:
    data = b"Some arbitrary content in unknown format."
    result = extract_text(data, "weird.xyz")
    assert "arbitrary content" in result


def test_extract_pdf_returns_empty_without_pypdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """When pypdf is not installed, PDF extraction degrades gracefully."""
    import builtins
    import app.file_extract as mod

    original_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pypdf":
            raise ImportError("mocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    result = mod._extract_pdf(b"%PDF-1.4 fake pdf data")
    assert result == ""
