import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from app.core.security import get_password_hash, verify_password
from app.models import Document, DocumentChunk, Item, ItemCreate, User, UserCreate, UserUpdate


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


# --- RAG CRUD ---


def create_document(
    *,
    session: Session,
    owner_id: uuid.UUID,
    filename: str,
    file_type: str,
    file_size: int,
    file_hash: str | None = None,
) -> Document:
    db_doc = Document(
        owner_id=owner_id,
        filename=filename,
        file_type=file_type,
        file_size=file_size,
        file_hash=file_hash,
        status="pending",
    )
    session.add(db_doc)
    session.commit()
    session.refresh(db_doc)
    return db_doc


def get_document(*, session: Session, document_id: uuid.UUID) -> Document | None:
    return session.get(Document, document_id)


def get_document_by_hash(
    *, session: Session, file_hash: str, owner_id: uuid.UUID
) -> Document | None:
    """Return a successfully processed document with the given SHA-256 hash owned by user."""
    statement = select(Document).where(
        Document.file_hash == file_hash,
        Document.owner_id == owner_id,
        Document.status == "done",
    )
    return session.exec(statement).first()


def create_document_chunk(
    *,
    session: Session,
    document_id: uuid.UUID,
    content: str,
    embedding: list[float],
    metadata: dict[str, Any] | None = None,
) -> DocumentChunk:
    """Add a chunk to the session without committing. Caller manages the transaction."""
    db_chunk = DocumentChunk(
        document_id=document_id,
        content=content,
        embedding=embedding,
        metadata_json=metadata or {},
    )
    session.add(db_chunk)
    return db_chunk


def delete_document_chunks(*, session: Session, document_id: uuid.UUID) -> None:
    """Delete all chunks for a document. Used for idempotent re-ingestion on retry."""
    chunks = list(
        session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
    )
    for chunk in chunks:
        session.delete(chunk)
    session.commit()


def search_document_chunks(
    *,
    session: Session,
    embedding: list[float],
    owner_id: uuid.UUID,
    limit: int = 5,
    ef_search: int = 100,
) -> list[DocumentChunk]:
    """Return top-K chunks ordered by cosine distance to the query embedding.

    ef_search controls the HNSW dynamic candidate list size at query time.
    Higher values improve recall at the cost of latency (pgvector default is 40).
    """
    session.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))
    statement = (
        select(DocumentChunk)
        .join(Document)
        .where(Document.owner_id == owner_id)
        .order_by(DocumentChunk.embedding.cosine_distance(embedding))  # type: ignore[attr-defined]
        .limit(limit)
    )
    return list(session.exec(statement).all())
