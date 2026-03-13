"""Background document ingestion: text extraction → embedding → DB write.

This module owns the async orchestration logic so the HTTP route can return
202 immediately and delegate the slow work to a FastAPI BackgroundTask.
"""

import hashlib
import uuid

import httpx
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.services.rag import embed_texts, text_splitter


def _extract_text(raw_bytes: bytes, content_type: str) -> str:
    """Parse raw file bytes to plain text."""
    if content_type == "text/plain":
        return raw_bytes.decode("utf-8", errors="replace")
    elif content_type == "application/pdf":
        import fitz  # PyMuPDF — imported lazily to keep startup fast

        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        return "\n\n".join(page.get_text() for page in doc)  # type: ignore[union-attr]
    else:  # DOCX
        import io

        from docx import Document as DocxDocument

        doc_x = DocxDocument(io.BytesIO(raw_bytes))
        return "\n\n".join(p.text for p in doc_x.paragraphs if p.text.strip())


async def process_document(
    *,
    document_id: uuid.UUID,
    raw_bytes: bytes,
    content_type: str,
) -> None:
    """Orchestrate full ingestion pipeline for a single document.

    Designed to run as a FastAPI BackgroundTask — opens its own DB session
    since the route's session is closed before the background task runs.

    Steps:
      1. Extract plain text from raw bytes.
      2. Split text into chunks.
      3. Embed all chunks via the Embedding API (batched, ≤32 per request).
      4. Persist chunks and mark the document as 'done'.

    On any failure the document status is set to 'failed' with an error message.
    """
    with Session(engine) as session:
        document = crud.get_document(session=session, document_id=document_id)
        if not document:
            return

        # Idempotency: remove any partial chunks from a previous failed attempt.
        crud.delete_document_chunks(session=session, document_id=document_id)

        try:
            content = _extract_text(raw_bytes, content_type)
            chunks = text_splitter.split_text(content)
            if not chunks:
                raise ValueError("No text content extracted from document.")

            # ── Embedding cache ──────────────────────────────────────────────
            # Compute SHA-256 per chunk. Chunks whose hash already exists in
            # the DB reuse the stored vector without an API call.
            chunk_hashes = [
                hashlib.sha256(c.encode()).hexdigest() for c in chunks
            ]
            embeddings: list[list[float] | None] = []
            uncached_indices: list[int] = []
            uncached_texts: list[str] = []

            for i, (chunk_text, h) in enumerate(zip(chunks, chunk_hashes)):
                cached = crud.get_embedding_by_content_hash(
                    session=session, content_hash=h
                )
                if cached is not None:
                    embeddings.append(cached)
                else:
                    embeddings.append(None)
                    uncached_indices.append(i)
                    uncached_texts.append(chunk_text)

            if uncached_texts:
                async with httpx.AsyncClient(
                    base_url=settings.EMBEDDING_BASE_URL,
                    timeout=httpx.Timeout(60.0),
                    headers=(
                        {"Authorization": f"Bearer {settings.EMBEDDING_API_KEY}"}
                        if settings.EMBEDDING_API_KEY
                        else {}
                    ),
                ) as client:
                    # Embed in batches of 32 to stay within provider limits.
                    BATCH_SIZE = 32
                    new_embeddings: list[list[float]] = []
                    for start in range(0, len(uncached_texts), BATCH_SIZE):
                        batch = uncached_texts[start : start + BATCH_SIZE]
                        new_embeddings.extend(await embed_texts(client, batch))

                for pos, emb in zip(uncached_indices, new_embeddings):
                    embeddings[pos] = emb

            for chunk_text, emb, h in zip(chunks, embeddings, chunk_hashes):
                assert emb is not None  # all slots filled by cache or API
                crud.create_document_chunk(
                    session=session,
                    document_id=document_id,
                    content=chunk_text,
                    embedding=emb,
                    content_hash=h,
                )

            document.status = "done"
            session.add(document)
            session.commit()

        except Exception as exc:
            document.status = "failed"
            document.error_message = str(exc)[:500]
            session.add(document)
            session.commit()
