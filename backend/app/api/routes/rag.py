import hashlib
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile
from sqlmodel import Field, SQLModel, col, func, select

from app import crud
from app.api.deps import CurrentUser, EmbeddingDep, SessionDep
from app.core.rate_limit import limiter
from app.models import Document, DocumentChunk, DocumentPublic, DocumentsPublic, Message
from app.services import ingest as ingest_service
from app.services import rag as rag_service  # still used by /search

router = APIRouter(prefix="/rag", tags=["rag"])

ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Magic bytes (file header signatures) for supported binary types.
# text/plain has no reliable magic bytes so it is omitted.
_MAGIC_BYTES: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
}


def _validate_magic_bytes(content_type: str, data: bytes) -> bool:
    """Return True if the file header matches the declared MIME type."""
    magic = _MAGIC_BYTES.get(content_type)
    if magic is None:
        return True  # text/plain: no standard magic bytes
    return data[: len(magic)] == magic


def _safe_filename(raw: str | None) -> str:
    """Strip directory components from a filename to prevent path traversal."""
    name = Path(raw or "unknown").name
    return name or "unknown"


class SearchRequest(SQLModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)


class ChunkResult(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    content: str


@router.post("/ingest", response_model=DocumentPublic, status_code=202)
@limiter.limit("10/minute")
async def ingest_document(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    current_user: CurrentUser,
    file: UploadFile,
) -> Any:
    """Upload a document, parse its text, embed the chunks, and store in the database."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    safe_filename = _safe_filename(file.filename)
    raw_bytes = await file.read()

    if len(raw_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    if not _validate_magic_bytes(file.content_type, raw_bytes):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match declared type '{file.content_type}'.",
        )

    # Deduplication: return an already-processed copy without re-embedding.
    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    existing = crud.get_document_by_hash(
        session=session, file_hash=file_hash, owner_id=current_user.id
    )
    if existing:
        return existing

    # Clean up any stale 'failed' record for this file so re-uploads don't
    # leave orphaned rows in the database.
    crud.delete_failed_document_by_hash(
        session=session, file_hash=file_hash, owner_id=current_user.id
    )

    document = crud.create_document(
        session=session,
        owner_id=current_user.id,
        filename=safe_filename,
        file_type=file.content_type,
        file_size=len(raw_bytes),
        file_hash=file_hash,
    )

    # Schedule processing as a background task; return 202 immediately.
    background_tasks.add_task(
        ingest_service.process_document,
        document_id=document.id,
        raw_bytes=raw_bytes,
        content_type=file.content_type,
    )

    return document


@router.get("/documents", response_model=DocumentsPublic)
def list_documents(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """List all documents belonging to the current user."""
    count_statement = (
        select(func.count())
        .select_from(Document)
        .where(Document.owner_id == current_user.id)
    )
    count = session.exec(count_statement).one()
    statement = (
        select(Document)
        .where(Document.owner_id == current_user.id)
        .order_by(col(Document.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    documents = session.exec(statement).all()
    return DocumentsPublic(data=list(documents), count=count)


@router.get("/documents/{document_id}", response_model=DocumentPublic)
def get_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
) -> Any:
    """Get a single document (used for status polling after upload)."""
    document = crud.get_document(session=session, document_id=document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return document


@router.delete("/documents/{document_id}", response_model=Message)
def delete_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
) -> Any:
    """Delete a document and all its chunks (cascade)."""
    document = crud.get_document(session=session, document_id=document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    session.delete(document)
    session.commit()
    return Message(message="Document deleted successfully")


@router.post("/search", response_model=list[ChunkResult])
@limiter.limit("60/minute")
async def search_documents(
    *,
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
    embedding_client: EmbeddingDep,
    body: SearchRequest,
) -> Any:
    """Return the top-K most semantically relevant chunks for a query."""
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    vectors = await rag_service.embed_texts(embedding_client, [body.query])
    query_vector = vectors[0]

    chunks: list[DocumentChunk] = crud.search_document_chunks(
        session=session,
        embedding=query_vector,
        owner_id=current_user.id,
        limit=body.limit,
    )

    return [
        ChunkResult(id=chunk.id, document_id=chunk.document_id, content=chunk.content)
        for chunk in chunks
    ]
