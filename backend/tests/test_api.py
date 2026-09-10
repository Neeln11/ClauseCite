"""End-to-end API tests: upload a PDF, ask a question, get resolvable citations.

These run the real pipeline — extract, chunk, embed, retrieve, cite — against
SQLite and the offline provider. Nothing is stubbed, so a break anywhere in that
chain fails here.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest


def parse_sse(body: str) -> list[tuple[str, Any]]:
    """Split an SSE response into (event, parsed data) pairs."""
    events: list[tuple[str, Any]] = []
    for block in body.split("\n\n"):
        name: str | None = None
        payload: str | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                payload = line[len("data: ") :]
        if name is not None:
            events.append((name, json.loads(payload) if payload else None))
    return events


def events_of(events: list[tuple[str, Any]], name: str) -> list[Any]:
    return [data for event, data in events if event == name]


def ask(client: Any, question: str, **kwargs: Any) -> list[tuple[str, Any]]:
    response = client.post("/api/chat", json={"question": question, **kwargs})
    assert response.status_code == 200
    return parse_sse(response.text)


def answer_text(events: list[tuple[str, Any]]) -> str:
    return "".join(token["text"] for token in events_of(events, "token"))


@pytest.fixture
def uploaded(client: Any, sample_pdf: bytes) -> dict[str, Any]:
    """A document that has finished ingesting.

    Ingestion runs as a FastAPI background task, which TestClient completes
    before returning — so the document is queryable as soon as this returns.
    """
    response = client.post(
        "/api/documents", files={"file": ("agreement.pdf", sample_pdf, "application/pdf")}
    )
    assert response.status_code == 202, response.text
    document = response.json()
    detail = client.get(f"/api/documents/{document['id']}").json()
    assert detail["status"] == "ready", detail.get("error_message")
    assert detail["chunk_count"] >= 1
    return detail


class TestHealth:
    def test_liveness_does_not_touch_dependencies(self, client: Any) -> None:
        assert client.get("/health").json() == {"status": "ok"}

    def test_readiness_reports_every_dependency(self, client: Any) -> None:
        body = client.get("/ready").json()
        assert body["status"] == "ready", body["checks"]
        assert set(body["checks"]) == {"database", "storage", "ai_provider"}

    def test_offline_provider_is_ready_not_degraded(self, client: Any) -> None:
        """Running without an API key is a supported mode, not a broken one."""
        checks = client.get("/ready").json()["checks"]
        assert checks["ai_provider"].startswith("ok")


class TestUpload:
    def test_accepts_a_text_layer_pdf_and_indexes_it(self, uploaded: dict[str, Any]) -> None:
        assert uploaded["filename"] == "agreement.pdf"
        assert uploaded["page_count"] == 1

    def test_rejects_non_pdf_extension(self, client: Any) -> None:
        response = client.post(
            "/api/documents", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_rejects_a_file_that_only_claims_to_be_pdf(self, client: Any) -> None:
        response = client.post(
            "/api/documents",
            files={"file": ("fake.pdf", b"not really a pdf", "application/pdf")},
        )
        assert response.status_code == 422

    def test_rejects_an_empty_file(self, client: Any) -> None:
        response = client.post(
            "/api/documents", files={"file": ("empty.pdf", b"", "application/pdf")}
        )
        assert response.status_code == 422

    def test_reuploading_the_same_bytes_does_not_duplicate(
        self, client: Any, sample_pdf: bytes, uploaded: dict[str, Any]
    ) -> None:
        response = client.post(
            "/api/documents", files={"file": ("copy.pdf", sample_pdf, "application/pdf")}
        )
        assert response.status_code == 200  # 200, not 202 — nothing was ingested
        assert response.json()["duplicate_of"] == uploaded["id"]

    def test_serves_the_original_bytes_back(
        self, client: Any, uploaded: dict[str, Any], sample_pdf: bytes
    ) -> None:
        response = client.get(f"/api/documents/{uploaded['id']}/file")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == sample_pdf

    def test_delete_removes_it_from_retrieval(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        assert client.delete(f"/api/documents/{uploaded['id']}").status_code == 204
        assert client.get(f"/api/documents/{uploaded['id']}").status_code == 404
        # Chunks cascade, so the deleted document can no longer be cited.
        events = ask(client, "What is the notice period?")
        assert events_of(events, "sources")[0]["sources"] == []

    def test_unknown_document_is_a_problem_document(self, client: Any) -> None:
        response = client.get("/api/documents/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        assert set(response.json()) >= {"type", "title", "status", "detail"}


class TestChat:
    def test_answers_from_the_document_with_a_citation(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        events = ask(client, "What is the notice period for termination?")
        text = answer_text(events)

        assert "ninety (90) days" in text
        citations = events_of(events, "citations")[0]["citations"]
        assert citations, "an answer drawn from the document must cite it"
        assert citations[0]["document_id"] == uploaded["id"]

    def test_sources_arrive_before_any_token(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        """Chips must be clickable the moment a marker appears mid-stream."""
        names = [name for name, _ in ask(client, "What are the payment terms?")]
        assert names.index("sources") < names.index("token")
        assert names[-1] == "done"

    def test_every_citation_resolves_to_a_highlightable_location(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        events = ask(client, "What is the limitation of liability?")
        for citation in events_of(events, "citations")[0]["citations"]:
            assert citation["page"] >= 1
            assert citation["bbox"], "no bbox means the viewer cannot highlight"
            assert citation["snippet"]

    def test_cited_markers_all_appear_in_the_answer(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        events = ask(client, "What are the payment terms?")
        text = answer_text(events)
        for citation in events_of(events, "citations")[0]["citations"]:
            assert f"[{citation['marker']}]" in text

    def test_offline_answers_are_flagged_as_documents_only(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        done = events_of(ask(client, "What are the payment terms?"), "done")[0]
        assert done["answer_mode"] == "documents_only"
        assert done["model"] is None

    def test_declines_when_nothing_matches(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        """With no LLM connected, an unanswerable question must be declined
        rather than answered from thin air."""
        events = ask(client, "What is the zoning classification of the property?")
        text = answer_text(events)
        assert "don't cover this" in text
        assert events_of(events, "citations")[0]["citations"] == []

    def test_scoping_to_a_document_restricts_retrieval(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        events = ask(
            client, "What is the notice period?", document_ids=[uploaded["id"]]
        )
        for source in events_of(events, "sources")[0]["sources"]:
            assert source["document_id"] == uploaded["id"]

    def test_scoping_to_an_unrelated_document_returns_nothing(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        events = ask(
            client,
            "What is the notice period?",
            document_ids=["00000000-0000-0000-0000-000000000000"],
        )
        assert events_of(events, "sources")[0]["sources"] == []

    def test_conversation_is_persisted_and_replayable(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        done = events_of(ask(client, "What are the payment terms?"), "done")[0]
        conversation = client.get(f"/api/conversations/{done['conversation_id']}").json()

        roles = [message["role"] for message in conversation["messages"]]
        assert roles == ["user", "assistant"]
        assert conversation["messages"][1]["citations"]

    def test_follow_up_continues_the_same_conversation(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        first = events_of(ask(client, "What are the payment terms?"), "done")[0]
        second = events_of(
            ask(client, "And the notice period?", conversation_id=first["conversation_id"]),
            "done",
        )[0]
        assert second["conversation_id"] == first["conversation_id"]

        messages = client.get(
            f"/api/conversations/{first['conversation_id']}"
        ).json()["messages"]
        assert len(messages) == 4

    def test_empty_question_is_rejected_before_streaming(self, client: Any) -> None:
        response = client.post("/api/chat", json={"question": ""})
        assert response.status_code == 422

    def test_unknown_conversation_errors_in_band(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        """Once the stream has started the status is already 200, so errors have
        to arrive as an event rather than a status code."""
        response = client.post(
            "/api/chat",
            json={
                "question": "hello",
                "conversation_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 200
        errors = events_of(parse_sse(response.text), "error")
        assert errors and errors[0]["title"]

    def test_conversations_are_listed_newest_first(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        ask(client, "What are the payment terms?")
        listing = client.get("/api/conversations").json()
        assert listing
        assert listing[0]["message_count"] >= 2


class TestProviderEndpoint:
    def test_status_defaults_to_offline(self, client: Any) -> None:
        body = client.get("/api/provider/status").json()
        assert body["mode"] == "offline"
        assert body["provider_id"] is None
        assert "documents" in body["message"]

    def test_an_unreachable_key_is_rejected_and_leaves_offline_intact(
        self, client: Any
    ) -> None:
        """A bad key must not leave the app in a half-configured state where
        every subsequent question fails."""
        response = client.post(
            "/api/provider/configure", json={"api_key": "sk-not-a-real-key-12345"}
        )
        assert response.status_code == 422
        assert client.get("/api/provider/status").json()["mode"] == "offline"

    def test_questions_still_work_after_a_rejected_key(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        client.post("/api/provider/configure", json={"api_key": "sk-not-a-real-key-12345"})
        done = events_of(ask(client, "What are the payment terms?"), "done")[0]
        assert done["answer_mode"] == "documents_only"

    def test_a_too_short_key_is_a_validation_error(self, client: Any) -> None:
        assert client.post("/api/provider/configure", json={"api_key": "x"}).status_code == 422

    def test_disconnecting_returns_to_offline(self, client: Any) -> None:
        body = client.request("DELETE", "/api/provider/configure").json()
        assert body["mode"] == "offline"


class TestIngestRecovery:
    """Ingestion runs in-process, so a crash or restart mid-ingest strands a
    document at `pending` where nothing would ever pick it up again."""

    def test_startup_restarts_a_stranded_document(
        self, client: Any, uploaded: dict[str, Any]
    ) -> None:
        import sqlite3

        import anyio

        from app.workers.ingest import recover_interrupted_ingests

        # Simulate the interruption: the row exists and the blob is stored, but
        # the status never advanced past the upload.
        database = os.environ["DATABASE_URL"].split("///", 1)[1]
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE documents SET status = 'pending'")
            connection.execute("DELETE FROM chunks")
            connection.commit()

        assert client.get(f"/api/documents/{uploaded['id']}").json()["status"] == "pending"

        assert anyio.run(recover_interrupted_ingests) == 1

        detail = client.get(f"/api/documents/{uploaded['id']}").json()
        assert detail["status"] == "ready"
        assert detail["chunk_count"] >= 1
        # And it answers again.
        assert "ninety (90) days" in answer_text(ask(client, "What is the notice period?"))


class TestProviderFailureFallback:
    """A connected model that fails must not cost the user their answer.

    Expired keys, exhausted quota, and network blips are routine. The documents
    are still indexed and still answer the question, so a failure there degrades
    to document-only answering rather than to an error.
    """

    @pytest.fixture
    def broken_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services import provider as provider_module
        from app.services.errors import ProviderError

        class FailingProvider:
            async def embed(self, texts):
                return await provider_module.MockProvider(
                    provider_module.get_settings()
                ).embed(texts)

            async def stream_chat(self, system, messages):
                raise ProviderError("The API key was rejected.")
                yield  # pragma: no cover - makes this an async generator

            async def healthcheck(self) -> None:
                return None

        profile = provider_module.detect_provider("gsk_broken")
        monkeypatch.setattr(provider_module, "_runtime_provider", FailingProvider())
        monkeypatch.setattr(provider_module, "_runtime_profile", profile)

    def test_falls_back_to_the_documents(
        self, client: Any, uploaded: dict[str, Any], broken_llm: None
    ) -> None:
        events = ask(client, "What is the notice period for termination?")
        assert "ninety (90) days" in answer_text(events)
        assert events_of(events, "citations")[0]["citations"]

    def test_reports_the_downgrade_rather_than_hiding_it(
        self, client: Any, uploaded: dict[str, Any], broken_llm: None
    ) -> None:
        done = events_of(ask(client, "What is the notice period?"), "done")[0]
        assert done["answer_mode"] == "documents_only"
        assert done["degraded_reason"]

    def test_off_topic_question_still_gets_the_honest_decline(
        self, client: Any, uploaded: dict[str, Any], broken_llm: None
    ) -> None:
        """Retrieval returns its best matches even when they are weak, so the
        fallback runs and declines from the documents — no invented answer."""
        text = answer_text(ask(client, "What is the zoning classification?"))
        assert "don't cover this" in text

    def test_failure_with_no_documents_at_all_surfaces_as_an_error(
        self, client: Any, broken_llm: None
    ) -> None:
        """Nothing indexed means nothing to fall back to, so the provider failure
        has to reach the user rather than being silently swallowed."""
        events = ask(client, "What is the notice period?")
        assert events_of(events, "error")


class TestErrorContract:
    def test_unknown_route_uses_the_problem_shape(self, client: Any) -> None:
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        assert set(response.json()) >= {"type", "title", "status", "detail"}

    def test_every_response_carries_a_request_id(self, client: Any) -> None:
        assert client.get("/health").headers["X-Request-ID"]

    def test_an_inbound_request_id_is_echoed(self, client: Any) -> None:
        response = client.get("/health", headers={"X-Request-ID": "trace-me"})
        assert response.headers["X-Request-ID"] == "trace-me"
