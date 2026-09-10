"""Generate realistic contract PDFs and ingest them through the running API.

    python scripts/seed.py                      # generate, upload, wait for ready
    python scripts/seed.py --reset              # delete existing documents first
    python scripts/seed.py --no-upload          # just write the PDFs to disk

Uploading through the HTTP API rather than writing rows directly is deliberate:
it exercises the same path a user does, so a broken extractor, chunker, or
embedder fails here rather than during a demo.

The PDFs are typeset to give the chunker real structure to find - all-caps
article headings, short numbered sub-headings, and body paragraphs that open with
clause numbers. See scripts/contracts.py for why the corpus reads the way it does.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

# Importable both as `python scripts/seed.py` and `python -m scripts.seed`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contracts import CORPUS, Contract

DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / ".data" / "seed"

# Body text at 10pt is the median line size, which is what heading detection
# measures against. Sub-headings sit at 11pt: large enough to read as headings,
# and detected regardless of size because they are short and numbered.
_BODY_SIZE = 10
_LEADING = 14.5

SAMPLE_QUESTIONS = [
    "What is the notice period for termination?",
    "How much is the monthly rent for the Henderson premises, and when is it reviewed?",
    "What is the cap on Norwood's liability, and what falls outside it?",
    "What uptime does the Brightline agreement commit to, and what happens if it is missed?",
    "How long do the NDA confidentiality obligations last?",
    "How much holiday is Rachel Okonjo entitled to, and can she carry it over?",
    "Who owns intellectual property created for the client?",
    "What are the post-termination restrictions on the employee?",
    "What is the governing law across these documents?",
    "What is the penalty for paying an invoice late?",
]


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title",
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="Helvetica-Oblique",
            fontSize=10.5,
            leading=14,
            alignment=TA_CENTER,
            spaceAfter=16,
        ),
        "article": ParagraphStyle(
            "article",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            spaceBefore=16,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "clause": ParagraphStyle(
            "clause",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            spaceBefore=9,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=_BODY_SIZE,
            leading=_LEADING,
            alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "execution": ParagraphStyle(
            "execution",
            fontName="Helvetica",
            fontSize=_BODY_SIZE,
            leading=_LEADING * 1.6,
            spaceBefore=10,
        ),
    }


def _escape(text: str) -> str:
    """Paragraph parses a small XML dialect, so bare & and < would break it."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _footer(canvas: object, doc: object) -> None:
    canvas.saveState()  # type: ignore[attr-defined]
    canvas.setFont("Helvetica", 8)  # type: ignore[attr-defined]
    canvas.drawCentredString(A4[0] / 2, 12 * mm, str(doc.page))  # type: ignore[attr-defined]
    canvas.restoreState()  # type: ignore[attr-defined]


def render_pdf(contract: Contract, path: Path) -> int:
    """Typeset one contract. Returns the page count."""
    styles = _styles()
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=26 * mm,
        rightMargin=26 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title=contract.title,
        author="ClauseCite sample data",
        subject=contract.subtitle,
    )

    story: list[object] = [
        Paragraph(_escape(contract.title), styles["title"]),
        Paragraph(_escape(contract.subtitle), styles["subtitle"]),
    ]
    for paragraph in contract.parties:
        story.append(Paragraph(_escape(paragraph), styles["body"]))

    for section in contract.sections:
        story.append(Paragraph(_escape(section.heading), styles["article"]))
        for heading, paragraphs in section.clauses:
            story.append(Paragraph(_escape(heading), styles["clause"]))
            for paragraph in paragraphs:
                story.append(Paragraph(_escape(paragraph), styles["body"]))

    story.append(PageBreak())
    story.append(Paragraph("EXECUTION", styles["article"]))
    story.append(
        Paragraph(
            "IN WITNESS WHEREOF the parties have executed this document on the date "
            "first written above.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 18))
    for party in (
        "Signed for and on behalf of the first party",
        "Signed for and on behalf of the second party",
    ):
        story.append(
            Paragraph(f"{_escape(party)}: ______________________________", styles["execution"])
        )
        story.append(Paragraph("Name: ______________________________", styles["execution"]))
        story.append(Paragraph("Date: ______________________________", styles["execution"]))
        story.append(Spacer(1, 14))

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return int(document.page)


async def _reset(client: httpx.AsyncClient) -> int:
    existing = (await client.get("/api/documents")).json()
    for document in existing:
        await client.delete(f"/api/documents/{document['id']}")
    return len(existing)


async def _upload(client: httpx.AsyncClient, path: Path) -> tuple[str, bool]:
    """Upload one PDF. Returns (document_id, was_duplicate)."""
    with path.open("rb") as handle:
        response = await client.post(
            "/api/documents",
            files={"file": (path.name, handle, "application/pdf")},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"{path.name}: {response.status_code} {response.text}")
    body = response.json()
    return body["id"], body.get("duplicate_of") is not None


async def _wait_ready(
    client: httpx.AsyncClient, document_id: str, timeout: float
) -> dict[str, object]:
    """Poll until ingestion finishes. Mirrors what the frontend does."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        detail = (await client.get(f"/api/documents/{document_id}")).json()
        if detail["status"] in {"ready", "failed"}:
            return detail
        if asyncio.get_running_loop().time() > deadline:
            detail["status"] = "timeout"
            return detail
        await asyncio.sleep(0.4)


async def seed(api_url: str, out_dir: Path, *, upload: bool, reset: bool, timeout: float) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[tuple[Contract, Path, int]] = []
    for contract in CORPUS:
        path = out_dir / contract.filename
        pages = render_pdf(contract, path)
        size_kb = path.stat().st_size / 1024
        print(f"  rendered {contract.filename:<44} {pages} pages, {size_kb:>5.0f} KB")
        rendered.append((contract, path, pages))

    if not upload:
        print(f"\nPDFs written to {out_dir}")
        return 0

    print(f"\nUploading to {api_url}")
    failures = 0
    async with httpx.AsyncClient(base_url=api_url, timeout=60.0) as client:
        try:
            await client.get("/health")
        except httpx.ConnectError:
            print(
                f"\nCannot reach {api_url}. Start the backend first:\n"
                "  uvicorn app.main:app --reload",
                file=sys.stderr,
            )
            return 1

        if reset:
            removed = await _reset(client)
            print(f"  reset: deleted {removed} existing document(s)")

        for contract, path, _ in rendered:
            document_id, duplicate = await _upload(client, path)
            if duplicate:
                print(f"  {contract.filename:<44} already ingested (same sha256)")
                continue
            detail = await _wait_ready(client, document_id, timeout)
            status = detail["status"]
            if status == "ready":
                print(
                    f"  {contract.filename:<44} ready: "
                    f"{detail['page_count']} pages, {detail['chunk_count']} chunks"
                )
            else:
                failures += 1
                print(
                    f"  {contract.filename:<44} {status}: "
                    f"{detail.get('error_message') or 'ingestion did not complete'}",
                    file=sys.stderr,
                )

    if failures:
        print(f"\n{failures} document(s) did not ingest.", file=sys.stderr)
        return 1

    print("\nSeed complete. Questions worth trying:")
    for question in SAMPLE_QUESTIONS:
        print(f"  - {question}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API, help=f"default {DEFAULT_API}")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--no-upload", action="store_true", help="write the PDFs but do not ingest them"
    )
    parser.add_argument(
        "--reset", action="store_true", help="delete every existing document first"
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="per-document ingest timeout")
    args = parser.parse_args()

    return asyncio.run(
        seed(
            args.api_url.rstrip("/"),
            args.out_dir,
            upload=not args.no_upload,
            reset=args.reset,
            timeout=args.timeout,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
