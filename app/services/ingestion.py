"""
Document Ingestion & ETL Pipeline.
Supports PDF and DOCX document parsing, semantic chunking, 
dense embedding via FastEmbed, and upsert into Qdrant.
"""
import uuid
import asyncio
from typing import List, Dict, Any
from io import BytesIO
from loguru import logger

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from app.config import get_settings

settings = get_settings()

# Module-level shared embedding model (loaded once, reused across requests)
_embedding_model: TextEmbedding | None = None

def get_embedding_model() -> TextEmbedding:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding()
        logger.info("FastEmbed embedding model loaded.")
    return _embedding_model

# ---------------------------------------------------------------------------
# Document Parsers
# ---------------------------------------------------------------------------

def parse_pdf(file_bytes: bytes) -> str:
    """Extract raw text from a PDF file using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n".join(page.get_text("text") for page in doc)
        doc.close()
        return text.strip()
    except ImportError:
        raise RuntimeError("PyMuPDF is not installed. Run: pip install pymupdf")

def parse_docx(file_bytes: bytes) -> str:
    """Extract raw text from a DOCX file using python-docx."""
    try:
        from docx import Document
        doc = Document(BytesIO(file_bytes))
        text = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
        return text.strip()
    except ImportError:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")

def parse_text(file_bytes: bytes) -> str:
    """Decode plain text file."""
    return file_bytes.decode("utf-8", errors="ignore").strip()

def parse_document(file_bytes: bytes, filename: str) -> str:
    """Route to the correct parser based on file extension."""
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return parse_pdf(file_bytes)
    elif ext == "docx":
        return parse_docx(file_bytes)
    elif ext in ("txt", "md"):
        return parse_text(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Supported: pdf, docx, txt, md")

# ---------------------------------------------------------------------------
# Semantic / Overlap Chunker
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    Split text into overlapping chunks for granular vector indexing.
    Each chunk carries the document metadata for filtering.
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP
    metadata = metadata or {}

    chunks = []
    start = 0
    chunk_index = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk_text_str = text[start:end].strip()

        if chunk_text_str:
            chunks.append({
                "text": chunk_text_str,
                "metadata": {
                    **metadata,
                    "chunk_index": chunk_index,
                    "chunk_start_char": start,
                    "chunk_end_char": end,
                }
            })
            chunk_index += 1

        # Slide forward with overlap to preserve cross-boundary context
        start += chunk_size - chunk_overlap

    return chunks

# ---------------------------------------------------------------------------
# Embedding & Upsert
# ---------------------------------------------------------------------------

async def embed_and_upsert(
    chunks: List[Dict[str, Any]],
    qdrant_client: AsyncQdrantClient,
) -> int:
    """
    Embed chunks using local FastEmbed and upsert into Qdrant.
    Returns number of successfully ingested chunks.
    """
    embedding_model = get_embedding_model()
    texts = [c["text"] for c in chunks]

    logger.info(f"Generating embeddings for {len(texts)} chunks...")
    embeddings = await asyncio.to_thread(
        lambda: list(embedding_model.embed(texts))
    )

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={"dense": [float(x) for x in embedding]},
                payload={
                    "text": chunk["text"],
                    "metadata": chunk["metadata"],
                }
            )
        )

    await qdrant_client.upsert(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points=points
    )
    logger.success(f"Upserted {len(points)} chunks to Qdrant.")
    return len(points)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def ingest_file(
    file_bytes: bytes,
    filename: str,
    extra_metadata: Dict[str, Any] = None,
) -> int:
    """
    Full ETL pipeline:
    1. Parse file (PDF / DOCX / TXT)
    2. Semantic overlap chunking
    3. Embed with FastEmbed
    4. Upsert into Qdrant

    Returns the number of chunks ingested.
    """
    logger.info(f"Starting ingestion for: {filename}")

    # Step 1: Parse
    raw_text = parse_document(file_bytes, filename)
    if not raw_text:
        raise ValueError(f"No text extracted from {filename}. File may be empty or image-based PDF.")

    # Step 2: Chunk
    metadata = {"source": filename, **(extra_metadata or {})}
    chunks = chunk_text(raw_text, metadata=metadata)
    logger.info(f"Generated {len(chunks)} chunks from {filename}.")

    # Step 3 & 4: Embed & Upsert
    qdrant_client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY
    )
    try:
        count = await embed_and_upsert(chunks, qdrant_client)
    finally:
        await qdrant_client.close()

    return count
