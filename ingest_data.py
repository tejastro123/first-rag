import asyncio
import uuid
from typing import List, Dict, Any
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct
from fastembed import TextEmbedding

from app.config import get_settings

async def ingest_documents(documents: List[Dict[str, Any]]):
    settings = get_settings()
    
    if not settings.QDRANT_URL:
        print("Error: QDRANT_URL is not set.")
        return

    qdrant_client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY
    )
    
    # Initialize FastEmbed locally
    embedding_model = TextEmbedding()
    
    points = []
    print(f"Generating local FastEmbed embeddings for {len(documents)} sample document chunks...")
    
    for i, doc in enumerate(documents):
        text = doc.get("text", "")
        metadata = doc.get("metadata", {})
        
        try:
            # Generate embedding in a thread pool as it is CPU bound and synchronous
            embeddings = await asyncio.to_thread(lambda: list(embedding_model.embed([text])))
            embedding = [float(x) for x in embeddings[0]]
            
            point_id = str(uuid.uuid4())
            points.append(
                PointStruct(
                    id=point_id,
                    vector={"dense": embedding},
                    payload={
                        "text": text,
                        "metadata": metadata
                    }
                )
            )
            print(f"Processed chunk {i+1}/{len(documents)}")
        except Exception as e:
            print(f"Failed to process chunk {i+1}: {e}")
            await qdrant_client.close()
            return
        
    print(f"Uploading {len(points)} points to '{settings.QDRANT_COLLECTION_NAME}' collection...")
    try:
        await qdrant_client.upsert(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points=points
        )
        print("Ingestion completed successfully!")
    except Exception as e:
        print(f"Failed to upsert points: {e}")
        
    await qdrant_client.close()

# Sample data containing information about our OmniForge system for verification
sample_data = [
    {
        "text": "OmniForge Advanced RAG uses local FastEmbed (BAAI/bge-small-en-v1.5) for dense embeddings with a dimension size of 384. This model captures rich semantic features from text.",
        "metadata": {"source": "architecture_guide", "topic": "embeddings"}
    },
    {
        "text": "The retrieval pipeline uses Cohere rerank-english-v3.0 to rerank initial results down to top-5 chunks. This solves the 'Lost in the Middle' problem common in long context windows.",
        "metadata": {"source": "retrieval_ops", "topic": "reranking"}
    },
    {
        "text": "The temperature of the generation service is configured to 0.1. This ensures high factual grounding and minimizes hallucinations by preventing creative output generation.",
        "metadata": {"source": "generation_ops", "topic": "temperature"}
    }
]

if __name__ == "__main__":
    asyncio.run(ingest_documents(sample_data))
