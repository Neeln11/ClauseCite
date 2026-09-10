"""Shared fixtures.

Every test runs against a temporary SQLite file and the offline provider, so the
suite needs no database server, no Docker, and no API key. That is the same
configuration a first-time contributor gets by default, which means the tests
exercise the path most people actually run.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# This block runs at conftest import — before any test module, and therefore
# before any `app.*` import. That ordering is load-bearing: `app.models` calls
# `get_settings()` at import time and the result is cached for the process, so
# redirecting the environment from inside a fixture would be too late and the
# suite would quietly run against whatever DATABASE_URL the developer's .env
# happens to hold.
_TEST_DATA = Path(tempfile.mkdtemp(prefix="docqa-tests-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TEST_DATA / 'test.db').as_posix()}"
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = f"local:{_TEST_DATA / 'blobs'}"
os.environ["PERSIST_PROVIDER_KEY"] = "false"
os.environ["PROVIDER_KEY_FILE"] = str(_TEST_DATA / "provider.json")
os.environ["ENVIRONMENT"] = "ci"
os.environ["LOG_LEVEL"] = "WARNING"


@pytest.fixture(scope="session", autouse=True)
def _isolated_environment() -> Iterator[None]:
    """Marker fixture: depend on it to document the redirection above."""
    yield


@pytest.fixture
def client(_isolated_environment: None) -> Iterator[object]:
    """A TestClient with the app's lifespan run, against an empty database.

    Settings are process-cached, so every test shares one SQLite file. Wiping
    the rows between tests is what keeps them independent — otherwise a document
    uploaded by an earlier test stays retrievable and quietly changes the
    answers a later one gets.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.provider import reset_provider

    reset_provider()
    with TestClient(app) as test_client:  # lifespan creates the schema
        _truncate_all()
        yield test_client
    reset_provider()


def _truncate_all() -> None:
    """Empty every table, using a plain connection so no event loop is needed."""
    import sqlite3

    database = os.environ["DATABASE_URL"].split("///", 1)[1]
    with sqlite3.connect(database) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            connection.execute(f"DELETE FROM {table}")
        connection.commit()


@pytest.fixture
def sample_pdf() -> bytes:
    """A small contract-shaped PDF with a real text layer."""
    return build_pdf(
        [
            "MASTER SERVICES AGREEMENT",
            "",
            "3.2 Notice Period",
            "Either party may terminate this Agreement for convenience upon",
            "ninety (90) days prior written notice to the other party.",
            "",
            "4.1 Payment Terms",
            "Client shall pay each undisputed invoice within thirty (30) days",
            "of receipt. Late amounts accrue interest at 1.5% per month.",
            "",
            "7.3 Limitation of Liability",
            "Neither party's aggregate liability shall exceed the fees paid",
            "in the twelve (12) months preceding the claim.",
        ]
    )


def build_pdf(lines: list[str]) -> bytes:
    """Render lines to a one-page PDF. Kept here so tests never ship a binary."""
    import io

    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    text = pdf.beginText(72, 720)
    text.setFont("Helvetica", 11)
    for line in lines:
        text.textLine(line)
    pdf.drawText(text)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
