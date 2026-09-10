"""Prompt assembly and citation resolution.

Citation resolution is the load-bearing piece of this product: a chip that does
not point at real text is worse than no chip, because it looks trustworthy.
"""

from __future__ import annotations

import uuid

import pytest

from app.services import generate as gen
from app.services.retrieve import RetrievedChunk


def make_chunk(index: int, content: str = "Some clause text.") -> RetrievedChunk:
    return RetrievedChunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename=f"doc{index}.pdf",
        chunk_index=index,
        content=content,
        token_count=12,
        page_start=index + 1,
        page_end=index + 1,
        bbox=[{"page": index + 1, "x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0}],
        section_path=f"{index}.0 Section",
        score=0.5,
    )


class TestSystemPrompt:
    def test_offline_prompt_forbids_outside_knowledge(self) -> None:
        prompt = gen.build_system_prompt("[1] a.pdf, p.1\ntext", llm_mode=False)
        assert "ONLY" in prompt
        assert "outside knowledge" in prompt

    def test_llm_prompt_allows_labelled_general_knowledge(self) -> None:
        prompt = gen.build_system_prompt("[1] a.pdf, p.1\ntext", llm_mode=True)
        assert "general knowledge" in prompt
        # Even in LLM mode, document-derived claims must carry a marker.
        assert "[n]" in prompt or "[1]" in prompt

    def test_sources_are_embedded_verbatim(self) -> None:
        block = "[1] contract.pdf, p.4\nNinety (90) days notice."
        assert block in gen.build_system_prompt(block, llm_mode=False)


class TestHistory:
    def test_question_is_last(self) -> None:
        messages = gen.build_messages("And termination?", [("user", "Hi"), ("assistant", "Hello")])
        assert messages[-1] == {"role": "user", "content": "And termination?"}

    def test_history_is_truncated_to_the_limit(self) -> None:
        history = [("user", f"q{i}") for i in range(10)]
        messages = gen.build_messages("new", history, limit=4)
        # 4 history turns plus the new question.
        assert len(messages) == 5

    def test_zero_limit_drops_history(self) -> None:
        messages = gen.build_messages("new", [("user", "old")], limit=0)
        assert messages == [{"role": "user", "content": "new"}]


class TestCitationResolution:
    def test_markers_map_to_sources_in_order(self) -> None:
        sources = [make_chunk(0), make_chunk(1)]
        resolved = gen.resolve_citations("Answer [1] and more [2].", sources)
        assert [c.marker for c in resolved.citations] == [1, 2]
        assert resolved.citations[0].chunk_id == sources[0].id
        assert resolved.citations[1].chunk_id == sources[1].id

    def test_only_cited_sources_are_returned(self) -> None:
        resolved = gen.resolve_citations("Only [2] matters.", [make_chunk(0), make_chunk(1)])
        assert [c.marker for c in resolved.citations] == [2]

    def test_unresolvable_markers_are_stripped_not_rendered(self) -> None:
        """A model citing [7] when six sources were supplied must not produce a
        chip the user can click into nothing."""
        resolved = gen.resolve_citations("Claim [1] and claim [7].", [make_chunk(0)])
        assert "[7]" not in resolved.text
        assert "[1]" in resolved.text
        assert resolved.unresolved_markers == [7]

    def test_comma_form_is_understood(self) -> None:
        resolved = gen.resolve_citations("Both agree [1, 2].", [make_chunk(0), make_chunk(1)])
        assert [c.marker for c in resolved.citations] == [1, 2]

    def test_repeated_marker_yields_one_citation(self) -> None:
        resolved = gen.resolve_citations("[1] and again [1].", [make_chunk(0)])
        assert len(resolved.citations) == 1

    def test_stripping_does_not_leave_dangling_punctuation(self) -> None:
        resolved = gen.resolve_citations("A claim [9] .", [make_chunk(0)])
        assert " ." not in resolved.text
        assert "  " not in resolved.text

    def test_citation_carries_everything_the_ui_needs_to_highlight(self) -> None:
        source = make_chunk(0, "A" * 500)
        citation = gen.resolve_citations("[1]", [source]).citations[0]
        assert citation.page == source.page_start
        assert citation.filename == source.filename
        assert citation.bbox  # without a bbox the PDF viewer cannot highlight
        assert len(citation.snippet) <= 330  # truncated for the chip

    def test_answer_without_markers_yields_no_citations(self) -> None:
        resolved = gen.resolve_citations("I could not find that.", [make_chunk(0)])
        assert resolved.citations == []


class TestNoAnswerDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "The documents provided don't cover this.",
            "the documents provided do not cover this",
            "Unfortunately, the documents provided don't cover this.",
        ],
    )
    def test_recognises_declines(self, text: str) -> None:
        assert gen.is_no_answer(text)

    def test_does_not_flag_a_real_answer(self) -> None:
        assert not gen.is_no_answer("The notice period is ninety (90) days [1].")


class TestModeSelection:
    def test_offline_provider_is_not_llm_mode(self) -> None:
        from app.config import get_settings
        from app.services.provider import MockProvider

        assert not gen.llm_is_active(MockProvider(get_settings()))

    def test_configured_provider_is_llm_mode(self) -> None:
        from app.services.provider import build_provider, detect_provider

        provider = build_provider("gsk_test", detect_provider("gsk_test"))
        assert gen.llm_is_active(provider)
