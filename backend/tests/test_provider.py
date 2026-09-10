"""Provider detection, offline answering, and the offline/LLM switch."""

from __future__ import annotations

import httpx
import pytest

from app.services import provider as provider_module
from app.services.provider import (
    AnthropicProvider,
    GenericLLMProvider,
    MockProvider,
    build_provider,
    clear_runtime_provider,
    describe_provider,
    detect_provider,
    get_provider,
    probe_provider,
    reset_provider,
    save_provider_key,
    set_runtime_provider,
)


@pytest.fixture(autouse=True)
def _clean_provider(_isolated_environment: None):
    reset_provider()
    yield
    reset_provider()


def _stub_probe_responses(
    monkeypatch: pytest.MonkeyPatch,
    statuses: dict[str, int],
    *,
    unreachable: str | None = None,
) -> list[str]:
    """Answer `probe_provider`'s HTTP calls from a URL-fragment -> status map.

    Returns the list of URLs actually requested, so a test can assert which
    providers the key was — and was not — shown to.
    """
    calls: list[str] = []

    class _Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    class _Client:
        def __init__(self, **_: object) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_: object) -> bool:
            return False

        async def get(self, url: str, headers: dict[str, str] | None = None) -> _Response:
            calls.append(url)
            if unreachable is not None and unreachable in url:
                raise httpx.ConnectError("unreachable")
            for fragment, status in statuses.items():
                if fragment in url:
                    return _Response(status)
            return _Response(401)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", _Client)
    return calls


class TestDetection:
    @pytest.mark.parametrize(
        ("key", "provider_id"),
        [
            ("sk-ant-api03-abcdef", "anthropic"),
            ("sk-or-v1-abcdef", "openrouter"),
            ("sk-proj-abcdef", "openai"),
            ("sk-abcdefghijklmnop", "openai"),
            ("gsk_abcdefghijklmnop", "groq"),
            ("tog-abcdefghijklmnop", "together"),
            ("mis-abcdefghijklmnop", "mistral"),
        ],
    )
    def test_known_prefixes(self, key: str, provider_id: str) -> None:
        assert detect_provider(key).provider_id == provider_id

    def test_anthropic_keys_do_not_use_the_openai_protocol(self) -> None:
        """Regression: routing an Anthropic key to an OpenAI-compatible gateway
        fails authentication, because Anthropic's API is a different protocol."""
        profile = detect_provider("sk-ant-api03-abcdef")
        assert profile.kind == "anthropic"
        assert "anthropic.com" in profile.base_url

    def test_specific_prefixes_win_over_general_ones(self) -> None:
        # Both start with "sk-"; the more specific rule must match first.
        assert detect_provider("sk-ant-x").provider_id == "anthropic"
        assert detect_provider("sk-or-v1-x").provider_id == "openrouter"

    def test_unknown_key_is_tried_as_openai_compatible(self) -> None:
        # Self-hosted servers (vLLM, Ollama, LM Studio) use arbitrary keys.
        profile = detect_provider("my-local-server-key")
        assert profile.kind == "openai_compatible"

    def test_surrounding_whitespace_is_ignored(self) -> None:
        # Pasted keys routinely carry a trailing newline.
        assert detect_provider("  sk-ant-abc\n").provider_id == "anthropic"

    async def test_probe_identifies_the_provider_that_accepts_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid key with an unrecognised prefix must still be placed.

        Prefix rules only know the formats that existed when they were
        written; a provider changing its key format must not turn a working
        key into "the API key was rejected".
        """
        calls = _stub_probe_responses(monkeypatch, {"generativelanguage": 200})
        profile = await probe_provider("a-key-in-some-new-format")
        assert profile is not None
        assert profile.provider_id == "gemini"
        assert any("generativelanguage" in url for url in calls)

    async def test_probe_returns_none_when_no_provider_claims_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_probe_responses(monkeypatch, {})
        assert await probe_provider("nobody-owns-this") is None

    async def test_probe_never_asks_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: OpenRouter's /models catalogue is public.

        It answers 200 to any key, so probing it would make it claim every
        unidentified key. Its `sk-or-` prefix is stable, so detection covers
        it without a probe.
        """
        calls = _stub_probe_responses(monkeypatch, {"openrouter": 200})
        assert await probe_provider("not-an-openrouter-key") is None
        assert not any("openrouter" in url for url in calls)

    async def test_probe_stops_at_the_first_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The key is a secret: it should reach as few providers as possible.
        calls = _stub_probe_responses(monkeypatch, {"api.openai.com": 200})
        assert (await probe_provider("some-key")) is not None
        assert len(calls) == 1

    async def test_probe_skips_a_provider_it_cannot_reach(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Being unreachable says nothing about who owns the key.
        calls = _stub_probe_responses(
            monkeypatch, {"generativelanguage": 200}, unreachable="api.openai.com"
        )
        profile = await probe_provider("a-key")
        assert profile is not None and profile.provider_id == "gemini"
        assert any("api.openai.com" in url for url in calls)

    def test_builds_the_matching_client(self) -> None:
        assert isinstance(
            build_provider("sk-ant-x", detect_provider("sk-ant-x")), AnthropicProvider
        )
        assert isinstance(
            build_provider("gsk_x", detect_provider("gsk_x")), GenericLLMProvider
        )


class TestModeSwitch:
    def test_offline_is_the_default(self) -> None:
        assert isinstance(get_provider(), MockProvider)
        assert describe_provider().mode == "offline"

    def test_configuring_a_key_switches_to_llm_mode(self) -> None:
        set_runtime_provider("gsk_test", detect_provider("gsk_test"))
        description = describe_provider()
        assert description.mode == "llm"
        assert description.provider_name == "Groq"
        assert description.model

    def test_clearing_returns_to_offline(self) -> None:
        set_runtime_provider("gsk_test", detect_provider("gsk_test"))
        clear_runtime_provider()
        assert describe_provider().mode == "offline"
        assert isinstance(get_provider(), MockProvider)


class TestKeyPersistence:
    """A key entered once should survive a restart.

    Without this, every reboot silently drops the app back to document-only
    answers and the user has no idea why the output changed.
    """

    @pytest.fixture
    def persisted(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        from app.config import Settings, get_settings

        settings = get_settings()
        overridden = settings.model_copy(
            update={
                "persist_provider_key": True,
                "provider_key_file": str(tmp_path / "provider.json"),
            }
        )
        for module in ("app.services.provider",):
            monkeypatch.setattr(
                f"{module}.get_settings", lambda: overridden, raising=True
            )
        assert isinstance(overridden, Settings)
        return tmp_path / "provider.json"

    def test_saved_key_is_restored_on_the_next_start(self, persisted) -> None:
        from app.services.provider import restore_saved_provider

        profile = detect_provider("gsk_saved_key_value")
        save_provider_key("gsk_saved_key_value", profile)
        assert persisted.exists()

        clear_runtime_provider()  # as if the process had exited
        assert describe_provider().mode == "offline"

        assert restore_saved_provider() == "Groq"
        assert describe_provider().mode == "llm"

    def test_disconnecting_deletes_the_saved_key(self, persisted) -> None:
        from app.services.provider import forget_provider_key, restore_saved_provider

        save_provider_key("gsk_saved_key_value", detect_provider("gsk_saved_key_value"))
        forget_provider_key()

        assert not persisted.exists()
        assert restore_saved_provider() is None

    def test_a_byte_order_mark_does_not_break_the_restore(self, persisted) -> None:
        """A file hand-edited on Windows usually gains a BOM; plain utf-8 JSON
        parsing rejects it, which would silently drop the key."""
        from app.services.provider import restore_saved_provider

        persisted.write_text(
            '{"api_key": "gsk_saved_key_value", "provider_id": "groq"}',
            encoding="utf-8-sig",
        )
        assert restore_saved_provider() == "Groq"

    def test_a_corrupt_file_leaves_the_app_working_offline(self, persisted) -> None:
        from app.services.provider import restore_saved_provider

        persisted.write_text("not json at all", encoding="utf-8")
        assert restore_saved_provider() is None
        assert describe_provider().mode == "offline"

    def test_nothing_is_written_when_persistence_is_disabled(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import get_settings
        from app.services import provider as provider_module

        target = tmp_path / "provider.json"
        overridden = get_settings().model_copy(
            update={"persist_provider_key": False, "provider_key_file": str(target)}
        )
        monkeypatch.setattr(provider_module, "get_settings", lambda: overridden)

        save_provider_key("gsk_saved_key_value", detect_provider("gsk_saved_key_value"))
        assert not target.exists()


class TestOfflineAnswering:
    @pytest.fixture
    def provider(self) -> MockProvider:
        from app.config import get_settings

        return MockProvider(get_settings())

    async def test_embeddings_are_deterministic_and_normalised(
        self, provider: MockProvider
    ) -> None:
        first, second = await provider.embed(["notice period", "notice period"])
        assert first == second
        assert abs(sum(v * v for v in first) ** 0.5 - 1.0) < 1e-9

    async def test_related_text_scores_above_unrelated(
        self, provider: MockProvider
    ) -> None:
        query, related, unrelated = await provider.embed(
            [
                "termination notice period",
                "the notice period for termination is ninety days",
                "the parties shall arbitrate in Delaware",
            ]
        )
        assert sum(q * r for q, r in zip(query, related, strict=True)) > sum(
            q * u for q, u in zip(query, unrelated, strict=True)
        )

    async def test_answer_is_quoted_from_the_sources(
        self, provider: MockProvider
    ) -> None:
        system = (
            "SOURCES:\n"
            "[1] contract.pdf, p.4\n"
            "Either party may terminate for convenience upon ninety (90) days notice.\n"
        )
        chunks = [
            delta.text
            async for delta in provider.stream_chat(
                system, [{"role": "user", "content": "What is the notice period?"}]
            )
            if delta.text
        ]
        answer = "".join(chunks)
        assert "ninety (90) days" in answer
        assert "[1]" in answer

    async def test_declines_when_sources_do_not_cover_the_question(
        self, provider: MockProvider
    ) -> None:
        system = "SOURCES:\n[1] contract.pdf, p.1\nThe parties are Acme and Globex.\n"
        answer = "".join(
            [
                delta.text
                async for delta in provider.stream_chat(
                    system,
                    [{"role": "user", "content": "What is the zoning classification?"}],
                )
                if delta.text
            ]
        )
        assert "don't cover this" in answer

    async def test_reports_token_usage(self, provider: MockProvider) -> None:
        deltas = [
            delta
            async for delta in provider.stream_chat(
                "SOURCES:\n[1] a.pdf, p.1\nSome contract text about payment terms.\n",
                [{"role": "user", "content": "payment terms?"}],
            )
        ]
        final = deltas[-1]
        assert final.prompt_tokens and final.completion_tokens
