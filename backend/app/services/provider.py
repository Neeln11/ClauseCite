"""AI provider abstraction.

The application has exactly two answering modes, and this module is what decides
which one is live:

* **Offline (no API key).** `MockProvider` answers extractively — it selects and
  quotes the most relevant sentences from the retrieved chunks. No network, no
  key, no cost. Every answer is, by construction, text that appears in the
  uploaded documents.
* **LLM (a key was supplied in the UI).** A real model generates the answer from
  the same retrieved chunks, and may add general knowledge on top as long as it
  labels it. See `app.services.generate` for the two system prompts.

Retrieval is identical in both modes. That is deliberate: **embeddings always
come from `MockProvider`'s hashed projection, even when an LLM is connected.**
Chunks are embedded once at ingest time, and swapping the embedding model
afterwards would leave the query vector in a different space from the stored
ones — retrieval would silently return noise. Keeping one embedding function
means a user can connect, disconnect, or change keys at any time and the index
stays valid.

Adding a provider is a matter of adding one detection rule plus, if it is not
OpenAI-compatible, one class.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import httpx

from app.config import Settings, get_settings
from app.observability import get_logger
from app.services.errors import ProviderError


@dataclass(slots=True)
class ChatDelta:
    """One streamed step: either text, or the final usage report."""

    text: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AIProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def stream_chat(
        self, system: str, messages: Sequence[dict[str, str]]
    ) -> AsyncIterator[ChatDelta]: ...

    async def healthcheck(self) -> None: ...


# --------------------------------------------------------------------------
# Provider detection
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Everything needed to talk to a provider, derived from the key alone."""

    provider_id: str
    provider_name: str
    kind: Literal["openai_compatible", "anthropic"]
    base_url: str
    model: str


# Checked in order, first prefix match wins — so more specific prefixes must come
# before the general ones they extend (`sk-proj-` and `sk-ant-` before `sk-`).
_DETECTION_RULES: tuple[tuple[str, ProviderProfile], ...] = (
    (
        "sk-ant-",
        ProviderProfile(
            provider_id="anthropic",
            provider_name="Anthropic",
            # Anthropic's API is not OpenAI-compatible: different endpoint,
            # different auth header, different request and response shapes.
            # Routing these keys through an OpenAI client fails authentication.
            kind="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-opus-5",
        ),
    ),
    (
        "sk-or-",
        ProviderProfile(
            provider_id="openrouter",
            provider_name="OpenRouter",
            kind="openai_compatible",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-4o-mini",
        ),
    ),
    (
        "sk-proj-",
        ProviderProfile(
            provider_id="openai",
            provider_name="OpenAI",
            kind="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        ),
    ),
    (
        "gsk_",
        ProviderProfile(
            provider_id="groq",
            provider_name="Groq",
            kind="openai_compatible",
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
        ),
    ),
    (
        "tog-",
        ProviderProfile(
            provider_id="together",
            provider_name="Together AI",
            kind="openai_compatible",
            base_url="https://api.together.xyz/v1",
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ),
    ),
    (
        "mis-",
        ProviderProfile(
            provider_id="mistral",
            provider_name="Mistral AI",
            kind="openai_compatible",
            base_url="https://api.mistral.ai/v1",
            model="mistral-small-latest",
        ),
    ),
    (
        "AIza",
        ProviderProfile(
            provider_id="gemini",
            provider_name="Google Gemini",
            # Google's Gemini API has an OpenAI-compatible surface, so no
            # dedicated client class is needed — same as Groq/Together/Mistral.
            # Unlike those, model ids need the "models/" prefix on this
            # endpoint's /chat/completions — GET /models accepts either form,
            # which is why a bad id here still passes healthcheck and only
            # fails on the first real chat call. "gemini-flash-latest" is a
            # Google-maintained alias, so this doesn't need bumping by hand
            # every time a dated model version is retired.
            kind="openai_compatible",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="models/gemini-flash-latest",
        ),
    ),
    (
        "sk-",
        ProviderProfile(
            provider_id="openai",
            provider_name="OpenAI",
            kind="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        ),
    ),
)

_UNKNOWN_PROFILE = ProviderProfile(
    provider_id="unknown",
    provider_name="OpenAI-compatible endpoint",
    kind="openai_compatible",
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
)


def detect_provider(api_key: str) -> ProviderProfile:
    """Infer provider, endpoint, and a default model from an API key's prefix.

    Key prefixes are stable, publicly documented, and the only thing a user
    reliably has to hand — which is why the UI asks for nothing else. An
    unrecognised key is tried as an OpenAI-compatible endpoint rather than
    rejected, so self-hosted servers (vLLM, Ollama, LM Studio) work too.
    """
    key = api_key.strip()
    for prefix, profile in _DETECTION_RULES:
        if key.startswith(prefix):
            return profile
    return _UNKNOWN_PROFILE


# One entry per distinct provider_id, in first-seen order — lets the UI offer
# an explicit choice instead of relying on prefix-detection guessing right,
# and gives `resolve_profile` a name to look up when the user picks one.
PROVIDER_REGISTRY: dict[str, ProviderProfile] = {}
for _prefix, _profile in _DETECTION_RULES:
    PROVIDER_REGISTRY.setdefault(_profile.provider_id, _profile)
del _prefix, _profile


def resolve_profile(
    api_key: str,
    *,
    provider_id: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> ProviderProfile:
    """Resolve a `ProviderProfile`, honouring an explicit override if given.

    No override (`provider_id` is None or "auto") preserves today's behaviour:
    guess from the key's prefix. `provider_id="custom"` builds a profile from
    a user-supplied endpoint, so any OpenAI-compatible provider works even if
    it has no detection rule here. Picking a known `provider_id` skips
    detection entirely — useful when a key's prefix is ambiguous or shared
    across providers — and `model`, if given, overrides that provider's
    default.
    """
    if provider_id in (None, "", "auto"):
        return detect_provider(api_key)

    if provider_id == "custom":
        if not base_url or not model:
            raise ValueError("A custom provider needs both a base URL and a model name.")
        return ProviderProfile(
            provider_id="custom",
            provider_name="Custom endpoint",
            kind="openai_compatible",
            base_url=base_url,
            model=model,
        )

    profile = PROVIDER_REGISTRY.get(provider_id)
    if profile is None:
        raise ValueError(f"Unknown provider '{provider_id}'.")
    if model:
        profile = dataclasses.replace(profile, model=model)
    return profile


# Probing asks a provider "is this key yours?" with an authenticated
# `GET /models`, so only a provider that *requires* auth there can answer it.
# OpenRouter is deliberately excluded: its catalogue is public and returns 200
# for any key at all, which would make it claim every unidentified key. Its
# `sk-or-` prefix is stable and documented, so detection already covers it —
# do not "fix" this by adding it back.
_UNPROBEABLE = frozenset({"openrouter"})


async def probe_provider(api_key: str, *, timeout: float = 5.0) -> ProviderProfile | None:
    """Identify a key whose prefix matches no detection rule, by asking.

    Prefix rules only recognise formats that were known when they were
    written, and providers do change them — so a valid key can go
    unrecognised, and guessing sends it to the wrong provider, whose 401 then
    looks like "your key is invalid". A probe replaces that guess with an
    answer from the provider itself.

    Candidates are tried one at a time and the first 200 wins, so a key is
    exposed to as few providers as possible rather than broadcast to all of
    them at once. Returns None when nobody claims it.
    """
    log = get_logger(__name__)
    candidates = [
        p
        for p in PROVIDER_REGISTRY.values()
        if p.kind == "openai_compatible" and p.provider_id not in _UNPROBEABLE
    ]
    async with httpx.AsyncClient(timeout=timeout) as client:
        for profile in candidates:
            try:
                response = await client.get(
                    f"{profile.base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            except httpx.HTTPError:
                # Unreachable right now says nothing about who owns the key.
                continue
            if response.status_code == 200:
                log.info("provider.probe_matched", provider=profile.provider_id)
                return profile
    log.info("provider.probe_unmatched", candidates=len(candidates))
    return None


# --------------------------------------------------------------------------
# Mock — the offline, document-only provider
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    """a an and any are as at be been by for from has have if in is it its of on or
    shall such that the their there these this to under upon was were which will with""".split()
)


class MockProvider:
    """Offline provider. Deterministic by construction — no clocks, no randomness."""

    def __init__(self, settings: Settings) -> None:
        self._dim = settings.embedding_dimensions
        self._max_tokens = settings.generation_max_tokens

    def _vector(self, text: str) -> list[float]:
        counts = Counter(
            word for word in _WORD_RE.findall(text.lower()) if word not in _STOPWORDS
        )
        vector = [0.0] * self._dim
        for word, count in counts.items():
            weight = 1.0 + math.log(count)
            # Three hashed slots per word: enough spread that unrelated documents
            # do not collide into apparent similarity at 1536 dimensions.
            for salt in (b"\x00", b"\x01", b"\x02"):
                digest = hashlib.blake2b(word.encode() + salt, digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self._dim
                sign = 1.0 if digest[4] & 1 else -1.0
                vector[index] += sign * weight
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            # A zero vector has undefined cosine distance; pin it to a fixed unit
            # vector so pgvector never sees NaN.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def stream_chat(
        self, system: str, messages: Sequence[dict[str, str]]
    ) -> AsyncIterator[ChatDelta]:
        question = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        answer = self._extractive_answer(system, question)
        for word in answer.split(" "):
            yield ChatDelta(text=word + " ")
        yield ChatDelta(
            prompt_tokens=len(system.split()) + len(question.split()),
            completion_tokens=len(answer.split()),
        )

    def _extractive_answer(self, system: str, question: str) -> str:
        """Comprehensive extractive answer from all retrieved sources.

        Scores every sentence in every source chunk against the question, selects
        the top-N most relevant sentences across different chunks, groups them into
        coherent paragraphs per source, and assembles a readable multi-sentence
        answer with [n] citations — fully offline with no API calls.
        """
        sources = _parse_numbered_sources(system)
        if not sources:
            return "The documents provided don't cover this."

        question_words = {
            w for w in _WORD_RE.findall(question.lower()) if w not in _STOPWORDS
        }

        # Score every sentence across all sources
        scored: list[tuple[float, int, int, str]] = []  # (score, marker, sent_idx, sentence)
        for marker, body in sources:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", body) if s.strip()]
            for sent_idx, sentence in enumerate(sentences):
                words = {
                    w for w in _WORD_RE.findall(sentence.lower()) if w not in _STOPWORDS
                }
                if not words or len(sentence) < 20:
                    continue
                # Jaccard-like overlap weighted by question word coverage
                overlap = len(question_words & words) / math.sqrt(len(words))
                # Boost sentences that cover more question words
                coverage = len(question_words & words) / max(len(question_words), 1)
                final_score = overlap * (1.0 + coverage)
                scored.append((final_score, marker, sent_idx, sentence))

        if not scored or max(s[0] for s in scored) == 0:
            return "The documents provided don't cover this."

        # Keep only the top-3 sentences overall, at most 1 per source, skip
        # near-duplicates. A short, targeted question deserves a short,
        # targeted answer rather than a wall of merged paragraph text; a
        # second source is only pulled in when it's nearly as relevant as
        # the best match, i.e. genuinely a second fact worth stating.
        scored.sort(key=lambda x: -x[0])
        selected: list[tuple[float, int, int, str]] = []  # (score, marker, sent_idx, sentence)
        per_source_count: dict[int, int] = {}
        seen_words: list[set[str]] = []
        top_score = scored[0][0]

        for score, marker, sent_idx, sentence in scored:
            if score == 0:
                break
            # Drop sentences far weaker than the best match once we already
            # have an answer, instead of padding with low-relevance filler.
            if selected and score < top_score * 0.75:
                break
            if per_source_count.get(marker, 0) >= 1:
                continue
            # Skip near-duplicate sentences (>70% word overlap with an already-selected one)
            sent_words = {w for w in _WORD_RE.findall(sentence.lower()) if w not in _STOPWORDS}
            is_dup = any(
                len(sent_words & seen) / max(len(sent_words | seen), 1) > 0.70
                for seen in seen_words
            )
            if is_dup:
                continue
            selected.append((score, marker, sent_idx, sentence))
            per_source_count[marker] = per_source_count.get(marker, 0) + 1
            seen_words.append(sent_words)
            if len(selected) >= 3:
                break

        if not selected:
            return "The documents provided don't cover this."

        # Assemble final answer: one short sentence per citation, most
        # relevant first, instead of merging multiple sentences per source
        # into a single paragraph.
        return " ".join(
            f"{sentence.rstrip('.')} [{marker}]." for _, marker, _, sentence in selected
        )

    async def healthcheck(self) -> None:
        return None


def _parse_numbered_sources(system_prompt: str) -> list[tuple[int, str]]:
    """Recover (marker, text) pairs from an assembled prompt."""
    sources: list[tuple[int, str]] = []
    current: int | None = None
    body: list[str] = []
    for line in system_prompt.splitlines():
        header = re.match(r"^\[(\d+)\]\s", line)
        if header:
            if current is not None:
                sources.append((current, " ".join(body)))
            current = int(header.group(1))
            body = []
        elif current is not None:
            body.append(line.strip())
    if current is not None:
        sources.append((current, " ".join(body)))
    return sources


# --------------------------------------------------------------------------
# OpenAI-compatible providers (OpenAI, Groq, Mistral, Together, OpenRouter, …)
# --------------------------------------------------------------------------


class GenericLLMProvider:
    """Any endpoint that speaks the OpenAI `/chat/completions` protocol."""

    def __init__(self, api_key: str, profile: ProviderProfile, settings: Settings) -> None:
        from openai import AsyncOpenAI

        self._profile = profile
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=profile.base_url.rstrip("/"),
            # 20s * (1 + 1 retry) = 40s worst case. The previous 60s * (1 + 2
            # retries) let a provider having a bad moment (e.g. a transient
            # 503) hang the chat for up to 3 minutes before falling back to
            # documents-only — too long to make a user wait on every question.
            max_retries=1,
            timeout=20.0,
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # See the module docstring: embeddings are always the local hashed
        # projection so the query vector matches the stored ones.
        return await MockProvider(get_settings()).embed(texts)

    async def stream_chat(
        self, system: str, messages: Sequence[dict[str, str]]
    ) -> AsyncIterator[ChatDelta]:
        # The SDK types messages as a union of per-role TypedDicts; this app
        # carries them as plain dicts across the provider boundary so the
        # protocol stays SDK-agnostic. The shapes match at runtime.
        payload = cast(Any, [{"role": "system", "content": system}, *messages])
        try:
            stream = await self._client.chat.completions.create(
                model=self._profile.model,
                messages=payload,
                temperature=self._settings.generation_temperature,
                max_tokens=self._settings.generation_max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as exc:
            raise ProviderError(_readable_provider_error(exc)) from exc

        try:
            async for event in stream:
                usage = getattr(event, "usage", None)
                if usage is not None:
                    yield ChatDelta(
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                    )
                choices = getattr(event, "choices", None)
                if choices and (delta := choices[0].delta) and delta.content:
                    yield ChatDelta(text=delta.content)
        except Exception as exc:
            # A stream that dies halfway is still a provider failure, and the
            # caller has already emitted tokens — surface it rather than
            # truncating the answer silently.
            raise ProviderError(_readable_provider_error(exc)) from exc

    async def healthcheck(self) -> None:
        """Verify the key *and* the configured model actually work.

        This calls `/chat/completions` directly rather than `GET /models`
        first: some providers accept any model id in `/models` and only 404 on
        the endpoint that's actually used, which let a wrong model name (e.g.
        the "models/" prefix Google's endpoint requires) report as connected
        and only fail on the user's first real question.
        """
        try:
            await self._client.chat.completions.create(
                model=self._profile.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        except Exception as exc:
            raise ProviderError(_readable_provider_error(exc)) from exc


# --------------------------------------------------------------------------
# Anthropic (native API — not OpenAI-compatible)
# --------------------------------------------------------------------------


class AnthropicProvider:
    """Anthropic's Messages API.

    Kept separate from `GenericLLMProvider` because the wire format genuinely
    differs: the system prompt is a top-level field rather than a message, the
    auth header is `x-api-key`, and sampling parameters current models reject
    must be omitted rather than passed through.
    """

    def __init__(self, api_key: str, profile: ProviderProfile, settings: Settings) -> None:
        from anthropic import AsyncAnthropic

        self._profile = profile
        self._settings = settings
        # See GenericLLMProvider for why this is 20s/1 retry rather than 60s/2.
        self._client = AsyncAnthropic(api_key=api_key, max_retries=1, timeout=20.0)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # Anthropic has no embeddings endpoint, and even if it did the module
        # docstring's rule applies: retrieval uses the local projection.
        return await MockProvider(get_settings()).embed(texts)

    def _request_kwargs(self) -> dict[str, Any]:
        # `max_tokens` bounds reasoning *and* the reply on current models, so the
        # configured answer budget alone would truncate the answer mid-sentence.
        return {
            "model": self._profile.model,
            "max_tokens": max(self._settings.generation_max_tokens, 4096),
            # A grounded answer over supplied sources is not a deep-reasoning
            # task; low effort keeps latency and cost down. Note that current
            # models reject `temperature`, so generation_temperature is not
            # applied on this path.
            "output_config": {"effort": "low"},
        }

    async def stream_chat(
        self, system: str, messages: Sequence[dict[str, str]]
    ) -> AsyncIterator[ChatDelta]:
        kwargs = self._request_kwargs()
        # As above: plain dicts crossing the provider boundary, matching the
        # SDK's TypedDict shape at runtime.
        payload = cast(
            Any, [{"role": m["role"], "content": m["content"]} for m in messages]
        )
        try:
            stream_cm = self._client.messages.stream(
                system=system, messages=payload, **kwargs
            )
        except TypeError:
            # Older SDK builds don't know `output_config`. Drop it rather than
            # failing — the request is valid without it.
            kwargs.pop("output_config", None)
            stream_cm = self._client.messages.stream(
                system=system, messages=payload, **kwargs
            )

        try:
            async with stream_cm as stream:
                async for text in stream.text_stream:
                    if text:
                        yield ChatDelta(text=text)
                final = await stream.get_final_message()
                yield ChatDelta(
                    prompt_tokens=final.usage.input_tokens,
                    completion_tokens=final.usage.output_tokens,
                )
        except Exception as exc:
            raise ProviderError(_readable_provider_error(exc)) from exc

    async def healthcheck(self) -> None:
        try:
            await self._client.messages.create(
                model=self._profile.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        except Exception as exc:
            raise ProviderError(_readable_provider_error(exc)) from exc


# --------------------------------------------------------------------------
# Error shaping
# --------------------------------------------------------------------------


def _readable_provider_error(exc: Exception) -> str:
    """Turn an SDK exception into something worth showing a user.

    The raw string is often a full request dump. What the user can act on is
    almost always one of four things: the key is wrong, the key is out of
    credit, the model name is wrong, or the endpoint is unreachable.
    """
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "The API key was rejected. Check that it is correct and still active."
    if status == 404:
        return "The endpoint or model was not found for this key."
    if status == 429:
        return "The provider rate-limited or declined the request — check your quota or billing."
    if status is not None and status >= 500:
        return f"The provider returned a server error ({status}). Try again shortly."
    message = str(exc).strip()
    if not message:
        return f"The request failed ({type(exc).__name__})."
    return message[:300]


# --------------------------------------------------------------------------
# Provider registry
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderDescription:
    """What the API and the UI report about the current answering mode."""

    mode: Literal["offline", "llm"]
    provider_id: str | None
    provider_name: str | None
    model: str | None
    message: str


_OFFLINE_DESCRIPTION = ProviderDescription(
    mode="offline",
    provider_id=None,
    provider_name=None,
    model=None,
    message="Offline mode — answers come only from your uploaded documents.",
)

_default_provider: AIProvider | None = None
_runtime_provider: AIProvider | None = None
_runtime_profile: ProviderProfile | None = None


def get_provider() -> AIProvider:
    """The provider that should answer the next question.

    A user-supplied key wins; otherwise the offline provider answers from the
    documents alone. There is no third state — the app is always able to answer.
    """
    global _default_provider
    if _runtime_provider is not None:
        return _runtime_provider
    if _default_provider is None:
        _default_provider = MockProvider(get_settings())
    return _default_provider


def describe_provider() -> ProviderDescription:
    if _runtime_profile is None:
        return _OFFLINE_DESCRIPTION
    return ProviderDescription(
        mode="llm",
        provider_id=_runtime_profile.provider_id,
        provider_name=_runtime_profile.provider_name,
        model=_runtime_profile.model,
        message=f"Connected to {_runtime_profile.provider_name} · {_runtime_profile.model}. "
        "Answers combine your documents with the model's own knowledge.",
    )


def build_provider(api_key: str, profile: ProviderProfile) -> AIProvider:
    settings = get_settings()
    if profile.kind == "anthropic":
        return AnthropicProvider(api_key, profile, settings)
    return GenericLLMProvider(api_key, profile, settings)


def set_runtime_provider(api_key: str, profile: ProviderProfile) -> AIProvider:
    """Install a user-supplied provider as the active one."""
    global _runtime_provider, _runtime_profile
    _runtime_provider = build_provider(api_key, profile)
    _runtime_profile = profile
    return _runtime_provider


def clear_runtime_provider() -> None:
    """Drop the runtime provider and fall back to document-only answering."""
    global _runtime_provider, _runtime_profile
    _runtime_provider = None
    _runtime_profile = None


def reset_provider() -> None:
    """Test hook — resets both the default and runtime providers."""
    global _default_provider
    _default_provider = None
    clear_runtime_provider()


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
#
# The key is written to a local file so that "connected" survives a restart —
# without it, every reboot silently drops the app back to document-only answers
# and the user has no idea why the output changed.
#
# The file holds the key in plain text. That is the same trust level as the
# `.env` file next to it, and the directory is gitignored, but it is a real
# consideration on a shared machine: set PERSIST_PROVIDER_KEY=false to keep the
# key in memory only, at the cost of re-entering it after each restart.


def _key_file() -> Path:
    return Path(get_settings().provider_key_file).expanduser()


def save_provider_key(api_key: str, profile: ProviderProfile) -> None:
    if not get_settings().persist_provider_key:
        return
    path = _key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # The full profile is saved, not just provider_id: a custom endpoint's
    # base_url/model can't be re-derived from the key on restart, and saving
    # only the id would silently re-detect a *different* profile for any
    # provider whose default model changes later.
    path.write_text(
        json.dumps({"api_key": api_key, "profile": dataclasses.asdict(profile)}),
        encoding="utf-8",
    )
    # Owner-only. Best-effort: Windows ignores the mode bits, and failing to
    # tighten permissions must not stop the app from working.
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def forget_provider_key() -> None:
    with contextlib.suppress(OSError):
        _key_file().unlink(missing_ok=True)


def restore_saved_provider() -> str | None:
    """Reload a previously saved key at startup.

    Returns the provider name if one was restored. The key is *not* verified
    here — a network call would make startup depend on the provider being
    reachable. A key that has since been revoked surfaces on the first question
    as a normal stream error.
    """
    if not get_settings().persist_provider_key:
        return None
    path = _key_file()
    if not path.exists():
        return None
    try:
        # utf-8-sig, not utf-8: a file hand-edited on Windows often carries a
        # BOM, and json.loads rejects it. Reading it this way strips a BOM when
        # present and is identical to utf-8 when it is not.
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
        api_key = saved["api_key"]
        # Older files only ever saved provider_id; re-detect for those so an
        # upgrade doesn't strand existing users disconnected.
        profile = (
            ProviderProfile(**saved["profile"])
            if "profile" in saved
            else detect_provider(api_key)
        )
    except (OSError, ValueError, KeyError, TypeError):
        # A corrupt file must not block startup; offline mode still answers.
        log = get_logger(__name__)
        log.warning("provider.saved_key_unreadable", path=str(path))
        return None
    set_runtime_provider(api_key, profile)
    return profile.provider_name
