import os
import re
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import chromadb
from chromadb.config import Settings

CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / "chroma_data"
COLLECTION_NAME = "resume"

_client = None


def get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def get_collection():
    return get_client().get_or_create_collection(COLLECTION_NAME)


def chunk_markdown(text: str) -> list[str]:
    """Split a markdown resume into chunks along its '## ' section headers."""
    sections = re.split(r"\n(?=## )", text)
    return [s.strip() for s in sections if s.strip()]


def ingest_resume(path: str) -> int:
    """Chunk the resume at `path` and (re)populate the ChromaDB collection. Returns chunk count."""
    text = Path(path).read_text()
    chunks = chunk_markdown(text)

    client = get_client()
    client.delete_collection(COLLECTION_NAME) if COLLECTION_NAME in {
        c.name for c in client.list_collections()
    } else None
    collection = client.get_or_create_collection(COLLECTION_NAME)

    collection.add(
        ids=[f"chunk-{i}" for i in range(len(chunks))],
        documents=chunks,
    )
    return len(chunks)


def query_resume(query_text: str, n_results: int = 3) -> list[str]:
    """Return the most relevant resume chunks for a given query (e.g. a job title/description)."""
    collection = get_collection()
    results = collection.query(query_texts=[query_text], n_results=n_results)
    return results["documents"][0]
