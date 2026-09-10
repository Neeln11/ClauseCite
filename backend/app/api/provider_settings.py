"""Runtime AI provider configuration.

The user pastes an API key; provider, endpoint, and model are inferred from the
key's prefix by default (see `app.services.provider.detect_provider`) — a
single field is the difference between "I'll set this up later" and "it works
now". A key whose prefix matches no rule is not assumed to be anything: the
providers are asked which one owns it (`probe_provider`), because guessing
wrong reports a valid key as invalid. `provider_id`/`base_url`/`model` let the
UI override all of that, up to and including a fully custom OpenAI-compatible
endpoint (see `app.services.provider.resolve_profile`).

Connecting is verified before it is reported as connected: a key that cannot
reach the provider is rejected here rather than failing later, mid-answer.
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.observability import get_logger
from app.schemas import ProviderStatus
from app.services.errors import ProviderError
from app.services.provider import (
    PROVIDER_REGISTRY,
    clear_runtime_provider,
    describe_provider,
    forget_provider_key,
    get_provider,
    probe_provider,
    resolve_profile,
    save_provider_key,
    set_runtime_provider,
)

router = APIRouter(prefix="/api/provider", tags=["provider"])
log = get_logger(__name__)


class ConfigureRequest(BaseModel):
    """Only the API key is required — everything else is detected from it.

    `provider_id` overrides detection: a known id (see `/options`) skips
    guessing from the key, and "custom" builds a profile from `base_url` and
    `model` instead, so any OpenAI-compatible endpoint can be used.
    """

    api_key: str = Field(
        ...,
        min_length=8,
        description=(
            "API key. The provider is detected from its prefix, or by asking "
            "the providers, unless provider_id overrides it."
        ),
    )
    provider_id: str | None = Field(
        default=None, description="Skip detection: a known provider id, or 'custom'."
    )
    base_url: str | None = Field(
        default=None, description="Required when provider_id is 'custom'."
    )
    model: str | None = Field(
        default=None,
        description="Required when provider_id is 'custom'; optional override otherwise.",
    )


class ProviderOption(BaseModel):
    provider_id: str
    provider_name: str


def _status() -> ProviderStatus:
    return ProviderStatus(**dataclasses.asdict(describe_provider()))


@router.get("/status", response_model=ProviderStatus)
async def get_status() -> ProviderStatus:
    """Current answering mode, so the UI can show the right badge."""
    return _status()


@router.get("/options", response_model=list[ProviderOption])
async def get_options() -> list[ProviderOption]:
    """Known providers, for a manual-override dropdown in the UI.

    "custom" is not included here — it is not a detected provider but a UI
    escape hatch for anything else, always offered alongside this list.
    """
    return [
        ProviderOption(provider_id=p.provider_id, provider_name=p.provider_name)
        for p in PROVIDER_REGISTRY.values()
    ]


@router.post("/configure", response_model=ProviderStatus)
async def configure_provider(body: ConfigureRequest) -> ProviderStatus:
    try:
        profile = resolve_profile(
            body.api_key,
            provider_id=body.provider_id,
            base_url=body.base_url,
            model=body.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if profile.provider_id == "unknown":
        # The key matched no prefix rule. Rather than assume OpenAI and report
        # its inevitable 401 as "your key was rejected", ask the providers
        # which one actually owns it.
        probed = await probe_provider(body.api_key)
        if probed is None:
            log.warning("provider.unidentified")
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not work out which provider this API key belongs to. "
                    "Pick the provider from the list, or choose Custom and give "
                    "its base URL and model name."
                ),
            )
        profile = probed

    previous = describe_provider()

    set_runtime_provider(body.api_key, profile)
    try:
        await get_provider().healthcheck()
    except ProviderError as exc:
        # Roll back to whatever was active before, so a failed attempt to change
        # keys does not disconnect a session that was working.
        clear_runtime_provider()
        if previous.mode == "llm":
            from app.services.provider import restore_saved_provider

            restore_saved_provider()
        log.warning("provider.configure_failed", provider=profile.provider_id)
        raise HTTPException(
            status_code=422,
            detail=f"Could not connect to {profile.provider_name}: {exc.detail}",
        ) from exc

    save_provider_key(body.api_key, profile)
    # The key itself is never logged.
    log.info("provider.configured", provider=profile.provider_id, model=profile.model)
    return _status()


@router.delete("/configure", response_model=ProviderStatus)
async def clear_provider() -> ProviderStatus:
    """Disconnect and return to answering from the documents alone."""
    clear_runtime_provider()
    forget_provider_key()
    log.info("provider.cleared")
    return _status()
