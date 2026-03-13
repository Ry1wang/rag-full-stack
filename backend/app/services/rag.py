import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=50,
    separators=["\n\n", "\n", " ", ""],
    keep_separator=False,
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def embed_texts(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    """Call Embedding API (SiliconFlow/BGE-M3) to get vectors in batch. Retries up to 3 times."""
    if not texts:
        return []

    response = await client.post(
        "/embeddings",
        json={
            "model": settings.EMBEDDING_MODEL,
            "input": texts,
            "encoding_format": "float",
        },
    )
    response.raise_for_status()
    data = response.json()
    return [item["embedding"] for item in data["data"]]


async def prepare_chunks(
    client: httpx.AsyncClient,
    content: str,
) -> list[tuple[str, list[float]]]:
    """Split text into chunks and embed them. Returns (text, vector) pairs.

    Raises on embedding failure after retries. Does not touch the database —
    the caller is responsible for persisting the returned data.
    """
    chunks = text_splitter.split_text(content)
    if not chunks:
        return []

    embeddings = await embed_texts(client, chunks)
    return list(zip(chunks, embeddings))
