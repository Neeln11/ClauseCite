"""Blob storage.

Azure Blob in every deployed environment (and against Azurite locally, so the
same code path runs in dev and prod). A `local:<dir>` connection string selects a
filesystem backend instead, which exists purely so the app can be run and
demonstrated without Docker or an Azure account.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Protocol

from app.config import Settings, get_settings
from app.services.errors import NotFoundError


class Storage(Protocol):
    async def upload(self, path: str, data: bytes) -> None: ...

    async def download(self, path: str) -> bytes: ...

    async def delete(self, path: str) -> None: ...

    async def healthcheck(self) -> None: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        target = (self._root / path).resolve()
        # Defence in depth: blob paths are server-generated, but a path that can
        # escape its root is the kind of bug that only gets found by an attacker.
        if not target.is_relative_to(self._root):
            raise ValueError(f"Refusing to access path outside storage root: {path}")
        return target

    async def upload(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)

    async def download(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.exists():
            raise NotFoundError(f"Stored file not found: {path}")
        return await asyncio.to_thread(target.read_bytes)

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        await asyncio.to_thread(target.unlink, True)

    async def healthcheck(self) -> None:
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)


class AzureBlobStorage:
    def __init__(self, connection_string: str, container: str) -> None:
        self._connection_string = connection_string
        self._container_name = container
        self._client: object | None = None

    async def _container(self) -> object:
        from azure.core.exceptions import ResourceExistsError
        from azure.storage.blob.aio import BlobServiceClient

        if self._client is None:
            service = BlobServiceClient.from_connection_string(self._connection_string)
            container = service.get_container_client(self._container_name)
            # Creating a container that already exists is the steady state.
            with contextlib.suppress(ResourceExistsError):
                await container.create_container()
            self._client = container
        return self._client

    async def upload(self, path: str, data: bytes) -> None:
        container = await self._container()
        await container.upload_blob(name=path, data=data, overwrite=True)  # type: ignore[attr-defined]

    async def download(self, path: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError

        container = await self._container()
        try:
            stream = await container.download_blob(path)  # type: ignore[attr-defined]
            return await stream.readall()
        except ResourceNotFoundError as exc:
            raise NotFoundError(f"Stored file not found: {path}") from exc

    async def delete(self, path: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        container = await self._container()
        # Deleting an already-absent blob is a success, not an error.
        with contextlib.suppress(ResourceNotFoundError):
            await container.delete_blob(path)  # type: ignore[attr-defined]

    async def healthcheck(self) -> None:
        await self._container()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()  # type: ignore[attr-defined]
            self._client = None


_storage: Storage | None = None


def build_storage(settings: Settings) -> Storage:
    if settings.storage_is_local:
        return LocalStorage(settings.local_storage_root)
    return AzureBlobStorage(
        settings.azure_storage_connection_string, settings.azure_storage_container
    )


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = build_storage(get_settings())
    return _storage


async def close_storage() -> None:
    global _storage
    if _storage is not None and isinstance(_storage, AzureBlobStorage):
        await _storage.close()
    _storage = None
