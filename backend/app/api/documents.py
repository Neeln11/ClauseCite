"""Document upload, listing, retrieval, and deletion."""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Chunk, Document
from app.observability import get_logger
from app.schemas import DocumentDetail, DocumentOut, UploadAccepted
from app.services.errors import DocumentTooLargeError, NotFoundError, UnsupportedDocumentError
from app.services.storage import get_storage
from app.workers.ingest import ingest_document

router = APIRouter(prefix="/api/documents", tags=["documents"])
log = get_logger(__name__)

_READ_CHUNK = 1024 * 1024
_PDF_MAGIC = b"%PDF-"


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read the upload, refusing to buffer more than `limit` bytes.

    Trusting `content-length` would let a lying client push an arbitrarily large
    body into memory, so the cap is enforced against bytes actually read.
    """
    buffer = bytearray()
    while chunk := await upload.read(_READ_CHUNK):
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise DocumentTooLargeError(
                f"This file exceeds the {limit // (1024 * 1024)} MB upload limit."
            )
    return bytes(buffer)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=UploadAccepted)
async def upload_document(
    background_tasks: BackgroundTasks,
    response: Response,
    file: Annotated[UploadFile, File(description="A text-layer PDF")],
    session: AsyncSession = Depends(get_session),
) -> UploadAccepted:
    settings = get_settings()
    filename = (file.filename or "document.pdf").strip()

    if not filename.lower().endswith(".pdf"):
        raise UnsupportedDocumentError(
            "Only PDF files are supported.", title="Unsupported file type"
        )

    data = await _read_limited(file, settings.max_upload_bytes)
    if not data:
        raise UnsupportedDocumentError("The uploaded file is empty.", title="Empty file")
    if not data.startswith(_PDF_MAGIC):
        # An .pdf extension is a claim, not evidence.
        raise UnsupportedDocumentError(
            "This file is not a PDF, despite its extension.", title="Unsupported file type"
        )

    digest = hashlib.sha256(data).hexdigest()
    existing = (
        await session.execute(select(Document).where(Document.sha256 == digest))
    ).scalar_one_or_none()
    if existing is not None:
        # Costs one line and prevents the classic demo moment where the same
        # contract gets uploaded twice and every answer is cited twice.
        log.info("document.duplicate", document_id=str(existing.id), filename=filename)
        response.status_code = status.HTTP_200_OK
        return UploadAccepted(
            id=existing.id,
            filename=existing.filename,
            status=existing.status,
            duplicate_of=existing.id,
        )

    document_id = uuid.uuid4()
    blob_path = f"{digest[:2]}/{digest}.pdf"
    await get_storage().upload(blob_path, data)

    document = Document(
        id=document_id,
        filename=filename,
        blob_path=blob_path,
        byte_size=len(data),
        sha256=digest,
        status="pending",
    )
    session.add(document)
    await session.commit()

    background_tasks.add_task(ingest_document, document_id)
    log.info(
        "document.accepted",
        document_id=str(document_id),
        filename=filename,
        bytes=len(data),
    )
    return UploadAccepted(id=document_id, filename=filename, status="pending")


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    session: AsyncSession = Depends(get_session),
) -> list[Document]:
    result = await session.execute(select(Document).order_by(Document.created_at.desc()))
    return list(result.scalars())


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> DocumentDetail:
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFoundError(f"No document with id {document_id}.")
    chunk_count = int(
        (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            )
        ).scalar()
        or 0
    )
    return DocumentDetail(
        **DocumentOut.model_validate(document).model_dump(), chunk_count=chunk_count
    )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    """Serve the PDF bytes.

    Proxied through the API rather than redirected to a Blob SAS URL. A redirect
    saves egress through the container, but pdf.js then fetches cross-origin and
    every range request needs CORS rules on the storage account. For documents
    capped at 25 MB the proxy is the simpler correct choice; the SAS redirect is
    the optimisation to reach for when document sizes or traffic justify it.
    """
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFoundError(f"No document with id {document_id}.")
    data = await get_storage().download(document.blob_path)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{document.filename}"',
            # Content-addressed storage means the bytes for an id never change.
            "Cache-Control": "private, max-age=3600",
            "Accept-Ranges": "none",
        },
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFoundError(f"No document with id {document_id}.")

    blob_path = document.blob_path
    sha = document.sha256
    await session.delete(document)  # chunks cascade
    await session.commit()

    # Only drop the blob when no other row references those bytes; content
    # addressing means two documents can legitimately share a path.
    still_referenced = (
        await session.execute(select(Document.id).where(Document.sha256 == sha).limit(1))
    ).scalar_one_or_none()
    if still_referenced is None:
        await get_storage().delete(blob_path)

    log.info("document.deleted", document_id=str(document_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
