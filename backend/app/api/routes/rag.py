import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from sqlmodel import SQLModel, col, func, select

from app import crud
from app.api.deps import CurrentUser, EmbeddingDep, SessionDep
from app.core.rate_limit import limiter
from app.models import Document, DocumentChunk, DocumentPublic, DocumentsPublic, Message
from app.services import rag as rag_service

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
    limit: int = 5


class ChunkResult(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    content: str


@router.post("/ingest", response_model=DocumentPublic)
@limiter.limit("10/minute")
async def ingest_document(
    *,
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
    embedding_client: EmbeddingDep,
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

    if file.content_type == "text/plain":
        content = raw_bytes.decode("utf-8", errors="replace")
    elif file.content_type == "application/pdf":
        # PDF parsing (PyMuPDF) — Phase 2
        raise HTTPException(status_code=501, detail="PDF parsing not yet implemented.")
    else:
        # DOCX parsing (python-docx) — Phase 2
        raise HTTPException(status_code=501, detail="DOCX parsing not yet implemented.")

    document = crud.create_document(
        session=session,
        owner_id=current_user.id,
        filename=safe_filename,
        file_type=file.content_type,
        file_size=len(raw_bytes),
    )

    try:
        chunk_pairs = await rag_service.prepare_chunks(embedding_client, content)

        for chunk_text, vector in chunk_pairs:
            crud.create_document_chunk(
                session=session,
                document_id=document.id,
                content=chunk_text,
                embedding=vector,
            )

        document.status = "done"
        session.add(document)
        session.commit()
        session.refresh(document)
    except Exception as e:
        document.status = "failed"
        document.error_message = str(e)
        session.add(document)
        session.commit()
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}") from e

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
