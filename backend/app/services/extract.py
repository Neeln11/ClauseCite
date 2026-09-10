"""PDF text extraction with layout metadata (PyMuPDF).

Coordinates are converted once, here, into **unrotated PDF user space**
(origin bottom-left, units = points). That is the space pdf.js's
`viewport.convertToViewportRectangle()` expects, so the frontend needs no
knowledge of how extraction worked. Getting this wrong is invisible until the
highlight lands in the wrong half of the page, so the conversion lives in one
function with a test against a known fixture.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, cast

import pymupdf as fitz

from app.services.errors import UnsupportedDocumentError

# PyMuPDF span flag bits
_FLAG_BOLD = 1 << 4


@dataclass(slots=True)
class Span:
    text: str
    bbox: tuple[float, float, float, float]  # PDF user space
    size: float
    bold: bool
    font: str


@dataclass(slots=True)
class Line:
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    size: float
    bold: bool
    spans: list[Span] = field(default_factory=list)


@dataclass(slots=True)
class Page:
    number: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(line.text) for line in self.lines)


@dataclass(slots=True)
class ExtractedDocument:
    pages: list[Page]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)

    @property
    def body_size(self) -> float:
        """Median font size across all lines — the baseline for heading detection.

        Median rather than mean: a title page full of 28pt text would drag a mean
        upward and hide every real heading in the body.
        """
        sizes = [line.size for page in self.pages for line in page.lines if line.text.strip()]
        return statistics.median(sizes) if sizes else 0.0


def _union(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)
    return (x0, y0, x1, y1)


def extract_document(pdf_bytes: bytes, min_chars_per_page: int = 50) -> ExtractedDocument:
    """Extract lines with page numbers and PDF-space bounding boxes.

    Raises:
        UnsupportedDocumentError: the file is not a readable PDF, is encrypted,
            or has no text layer (i.e. it is scanned).
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover - depends on corrupt input
        raise UnsupportedDocumentError(
            "This file could not be read as a PDF.",
            problem_type="/errors/unreadable-document",
            title="Unreadable PDF",
        ) from exc

    with doc:
        if doc.needs_pass:
            raise UnsupportedDocumentError(
                "This PDF is password protected. Remove the password and upload it again.",
                problem_type="/errors/encrypted-document",
                title="Encrypted PDF",
            )
        if doc.page_count == 0:
            raise UnsupportedDocumentError(
                "This PDF contains no pages.",
                problem_type="/errors/empty-document",
                title="Empty PDF",
            )

        # PyMuPDF ships no type stubs for Document's page iteration, so the
        # element type has to be stated rather than inferred.
        pages = [
            _extract_page(page, number)
            for number, page in enumerate(cast("Iterable[Any]", doc), start=1)
        ]

    extracted = ExtractedDocument(pages=pages)

    # Guard rail: a document with almost no extractable text is a scan. Fail it
    # loudly. Silently indexing nothing is the worst outcome -- the app answers
    # "I don't know" forever and the user concludes the AI is broken.
    if extracted.char_count < min_chars_per_page * extracted.page_count:
        raise UnsupportedDocumentError(
            "No extractable text layer found. This document appears to be scanned, "
            "and OCR is not supported in this version.",
            problem_type="/errors/unsupported-document",
            title="Scanned document not supported",
        )

    return extracted


def _extract_page(page: fitz.Page, number: int) -> Page:
    # PyMuPDF reports coordinates in a rotation-applied, top-left-origin space.
    # Derotate, then flip the y axis to land in unrotated PDF user space.
    derotate = page.derotation_matrix
    unrotated = page.rect * derotate
    flip_base = unrotated.y0 + unrotated.y1

    lines: list[Line] = []
    blocks = page.get_text("dict").get("blocks", [])

    for block in blocks:
        if block.get("type") != 0:  # 0 = text; 1 = image
            continue
        for raw_line in block.get("lines", []):
            spans: list[Span] = []
            for raw_span in raw_line.get("spans", []):
                text = raw_span.get("text", "")
                if not text.strip():
                    continue
                rect = fitz.Rect(raw_span["bbox"]) * derotate
                font = raw_span.get("font", "")
                spans.append(
                    Span(
                        text=text,
                        bbox=(
                            rect.x0,
                            flip_base - rect.y1,
                            rect.x1,
                            flip_base - rect.y0,
                        ),
                        size=round(float(raw_span.get("size", 0.0)), 2),
                        bold=bool(raw_span.get("flags", 0) & _FLAG_BOLD)
                        or "bold" in font.lower()
                        or "black" in font.lower(),
                        font=font,
                    )
                )
            if not spans:
                continue
            text = "".join(span.text for span in spans).strip()
            if not text:
                continue
            lines.append(
                Line(
                    text=text,
                    page=number,
                    bbox=_union([span.bbox for span in spans]),
                    size=max(span.size for span in spans),
                    # A heading is usually bold throughout; one bold word in a
                    # sentence is emphasis, not structure.
                    bold=all(span.bold for span in spans),
                    spans=spans,
                )
            )

    return Page(
        number=number,
        width=abs(unrotated.width),
        height=abs(unrotated.height),
        lines=lines,
    )
