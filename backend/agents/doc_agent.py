from __future__ import annotations
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from bs4 import BeautifulSoup
from docx import Document


@dataclass
class RawDocument:
    content: str
    metadata: dict[str, Any]


def parse_file(file_path: str | Path, file_type: str) -> RawDocument:
    path = Path(file_path)
    ext = file_type.lower().lstrip(".")

    parsers = {
        "pdf":  _parse_pdf,
        "docx": _parse_docx,
        "html": _parse_html,
        "htm":  _parse_html,
        "json": _parse_json,
        "csv":  _parse_csv,
    }

    parser = parsers.get(ext)
    if parser:
        return parser(path)

    # Fallback: plain text (txt, md, etc.)
    content = path.read_text(encoding="utf-8", errors="replace")
    return RawDocument(content=content, metadata={"file_type": ext})


def parse_text(content: str) -> RawDocument:
    return RawDocument(content=content, metadata={"file_type": "text"})


def parse_url_content(html: str, url: str) -> RawDocument:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return RawDocument(content=text, metadata={"file_type": "url", "source_url": url})


def _parse_pdf(path: Path) -> RawDocument:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
    return RawDocument(
        content="\n\n".join(pages),
        metadata={"file_type": "pdf", "page_count": len(pages)},
    )


def _parse_docx(path: Path) -> RawDocument:
    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return RawDocument(
        content="\n\n".join(paragraphs),
        metadata={"file_type": "docx"},
    )


def _parse_html(path: Path) -> RawDocument:
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return RawDocument(content=text, metadata={"file_type": "html"})


def _parse_json(path: Path) -> RawDocument:
    data = json.loads(path.read_text(encoding="utf-8"))
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return RawDocument(content=content, metadata={"file_type": "json"})


def _parse_csv(path: Path) -> RawDocument:
    rows: list[str] = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
    return RawDocument(
        content="\n".join(rows),
        metadata={"file_type": "csv", "row_count": len(rows)},
    )
