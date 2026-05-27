"""
Advanced Retrieval Service.
Implements: Query Rewriting → Dense Embedding → Qdrant Search → Cohere Rerank.
"""
import asyncio
from typing import List, Dict, Any, Optional
import cohere
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from fastembed import TextEmbedding
from loguru import logger

from app.config import get_settings
from app.schemas import DocumentChunk
from app.services.ingestion import get_embedding_model

settings = get_settings()


class AdvancedRetriever:
    """
    Enterprise-grade retrieval engine implementing:
    1. Query Rewriting via Cohere command-a-03-2025
    2. Dense Vector Search via FastEmbed + Qdrant
    3. Cross-Encoder Reranking via Cohere rerank-english-v3.0
    """

    def __init__(self):
        self.cohere_client = cohere.AsyncClient(api_key=settings.COHERE_API_KEY)
        self.qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
        )
        # Reuse module-level singleton embedding model (loaded once)
        self.embedding_model: TextEmbedding = get_embedding_model()

    async def _rewrite_query(self, original_query: str) -> str:
        """
        Transform the user query to be more descriptive for vector search.
        Runs concurrently with the initial embedding in retrieve().
        """
        system_prompt = (
            "You are a search query optimizer. Given a user query, rewrite it to be "
            "as clear and descriptive as possible for a vector search engine. "
            "Output ONLY the optimized query, no conversational filler."
        )
        try:
            response = await self.cohere_client.chat(
                model="command-a-03-2025",
                message=original_query,
                preamble=system_prompt,
                temperature=0.0,
            )
            rewritten = response.text.strip()
            logger.debug(f"Query rewritten: '{original_query}' → '{rewritten}'")
            return rewritten
        except Exception as e:
            logger.warning(f"Query rewrite failed, using original. Error: {e}")
            return original_query

    async def _get_dense_embedding(self, text: str) -> List[float]:
        """
        Generate a 384-dim dense embedding using local FastEmbed.
        Offloaded to a thread pool to avoid blocking the asyncio event loop.
        """
        embeddings = await asyncio.to_thread(
            lambda: list(self.embedding_model.embed([text]))
        )
        return [float(x) for x in embeddings[0]]

    async def _search(
        self,
        dense_vector: List[float],
        filters: Optional[Dict[str, Any]],
    ) -> List[Any]:
        """Execute dense vector search in Qdrant with optional metadata filters."""
        qdrant_filter = None
        if filters:
            conditions = []
            for k, v in filters.items():
                # Prepend 'metadata.' if not already present to match the payload structure
                key_path = k if k.startswith("metadata.") else f"metadata.{k}"
                conditions.append(FieldCondition(key=key_path, match=MatchValue(value=v)))
            qdrant_filter = Filter(must=conditions)

        result = await self.qdrant_client.query_points(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            query=dense_vector,
            using="dense",
            query_filter=qdrant_filter,
            limit=settings.RETRIEVAL_TOP_K,
            with_payload=True,
        )
        logger.debug(f"Qdrant returned {len(result.points)} candidate chunks.")
        return result.points

    async def _rerank(
        self,
        query: str,
        documents: List[Any],
    ) -> List[DocumentChunk]:
        """
        Rerank broad Top-K results with Cohere Cross-Encoder to distill
        the most relevant RERANK_TOP_K chunks. Solves 'Lost in the Middle'.
        """
        if not documents:
            return []

        docs_text = [hit.payload.get("text", "") for hit in documents]

        rerank_response = await self.cohere_client.rerank(
            model="rerank-english-v3.0",
            query=query,
            documents=docs_text,
            top_n=settings.RERANK_TOP_K,
            return_documents=False,
        )

        reranked = []
        for result in rerank_response.results:
            hit = documents[result.index]
            reranked.append(
                DocumentChunk(
                    chunk_id=str(hit.id),
                    text=hit.payload.get("text", ""),
                    metadata=hit.payload.get("metadata", {}),
                    relevance_score=result.relevance_score,
                )
            )
        logger.debug(f"Reranked to top {len(reranked)} chunks.")
        return reranked

    async def retrieve(
        self,
        user_query: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """
        Full retrieval pipeline orchestrator:
        1. Parallelize: query rewrite + initial dense embedding
        2. Re-embed optimized query
        3. Dense search in Qdrant
        4. Cohere reranking
        """
        # Step 1: Run rewrite and baseline embedding in parallel
        rewrite_task = asyncio.create_task(self._rewrite_query(user_query))
        baseline_embed_task = asyncio.create_task(self._get_dense_embedding(user_query))

        optimized_query = await rewrite_task
        await baseline_embed_task  # discard baseline, use optimized below

        # Step 2: Embed the optimized query
        dense_vector = await self._get_dense_embedding(optimized_query)

        # Step 3: Search
        candidates = await self._search(dense_vector, filters)

        # Step 4: Rerank
        final_chunks = await self._rerank(user_query, candidates)

        return final_chunks
