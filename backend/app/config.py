"""Application settings.

Everything the app needs from the environment is declared here so that a missing
or malformed variable fails loudly at import time rather than at 3am inside a
request handler.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # One .env at the repository root serves compose and a host-run backend
        # alike. `backend/.env` is read second so it can override, which is what
        # you want when running two backends against different databases.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Core -------------------------------------------------------------
    app_name: str = "ClauseCite"
    environment: Literal["local", "ci", "production"] = "local"
    log_level: str = "INFO"
    # NoDecode: without it, pydantic-settings JSON-decodes list-typed fields
    # straight from the environment and `CORS_ORIGINS=http://localhost:5173`
    # fails before the comma-splitting validator below ever runs.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # ---- Datastore --------------------------------------------------------
    # SQLite by default so the app runs with nothing installed. Point this at
    # postgresql+asyncpg://... to use PostgreSQL + pgvector, which is what
    # production wants: an indexed vector search instead of an in-Python scan.
    database_url: str = "sqlite+aiosqlite:///./.data/docqa.db"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # ---- Blob storage -----------------------------------------------------
    # "UseDevelopmentStorage=true" targets Azurite. A "local:<path>" value uses
    # the filesystem instead, so the app runs with no storage container at all.
    azure_storage_connection_string: str = "local:./.data/blobs"
    azure_storage_container: str = "documents"

    # ---- AI provider ------------------------------------------------------
    # There is no provider to configure here: the app answers from documents
    # alone until a key is pasted into the UI, at which point that provider is
    # detected from the key and used for generation. These two settings only
    # control whether the pasted key outlives a restart.
    #
    # The file holds the key in plain text (same trust level as .env, and
    # gitignored). Set PERSIST_PROVIDER_KEY=false on a shared machine to keep
    # the key in memory only, at the cost of re-entering it after each restart.
    persist_provider_key: bool = True
    provider_key_file: str = "./.data/provider.json"

    # "mock" yields deterministic hash-based embeddings and an extractive answer
    # so the whole pipeline runs offline, in CI, and in tests without API keys.
    ai_provider: Literal["azure_openai", "mock"] = "mock"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_chat_deployment: str = "gpt-4o-mini"

    embedding_dimensions: int = 1536
    embedding_batch_size: int = 96
    embedding_batch_max_tokens: int = 60_000

    # ---- Chunking ---------------------------------------------------------
    chunk_target_tokens: int = 600
    chunk_max_tokens: int = 900
    chunk_overlap_tokens: int = 100

    # ---- Retrieval / generation ------------------------------------------
    retrieval_top_k: int = 12
    retrieval_final_k: int = 6
    retrieval_hybrid: bool = True
    max_context_tokens: int = 6000
    generation_temperature: float = 0.1
    generation_max_tokens: int = 1000
    history_messages: int = 4

    # ---- Uploads ----------------------------------------------------------
    max_upload_mb: int = 25
    # A document whose extracted text averages fewer characters than this per
    # page has no usable text layer, i.e. it is scanned.
    min_chars_per_page: int = 50

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def storage_is_local(self) -> bool:
        return self.azure_storage_connection_string.startswith("local:")

    @property
    def local_storage_root(self) -> str:
        return self.azure_storage_connection_string.removeprefix("local:") or "./.data/blobs"

    def require_azure_openai(self) -> None:
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_ENDPOINT", self.azure_openai_endpoint),
                ("AZURE_OPENAI_API_KEY", self.azure_openai_api_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"AI_PROVIDER=azure_openai requires {', '.join(missing)}. "
                "Set them in .env, or use AI_PROVIDER=mock for offline development."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    # ── Offline-only mode: Azure validation is skipped ─────────────────────
    # Uncomment when re-enabling the Azure provider:
    # if settings.ai_provider == "azure_openai":
    #     settings.require_azure_openai()
    return settings
