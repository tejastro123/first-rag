import asyncio
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import get_settings

async def main():
    settings = get_settings()
    
    if not settings.QDRANT_URL:
        print("Error: QDRANT_URL is not set in settings.")
        return

    print(f"Initializing Qdrant client at {settings.QDRANT_URL}...")
    client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY
    )

    collection_name = settings.QDRANT_COLLECTION_NAME

    # Check if collection already exists
    try:
        exists = await client.collection_exists(collection_name=collection_name)
    except Exception as e:
        print(f"Failed to check collection existence: {e}")
        return

    if exists:
        print(f"Collection '{collection_name}' already exists. Deleting it to recreate with 384 dimensions...")
        try:
            await client.delete_collection(collection_name=collection_name)
            print(f"Collection '{collection_name}' deleted.")
        except Exception as e:
            print(f"Failed to delete collection: {e}")
            return

    print(f"Creating collection '{collection_name}' with a 384-dimension 'dense' vector...")
    try:
        await client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": VectorParams(
                    size=384,
                    distance=Distance.COSINE
                )
            }
        )
        print(f"Successfully created collection '{collection_name}'.")
        
        # Create payload index for keyword matching to satisfy strict filtering requirements
        from qdrant_client.http import models as http_models
        await client.create_payload_index(
            collection_name=collection_name,
            field_name="metadata.department",
            field_schema=http_models.PayloadSchemaType.KEYWORD,
        )
        print("Successfully created payload index on 'metadata.department'.")
    except Exception as e:
        print(f"Failed to create collection: {e}")
        await client.close()
        return

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
