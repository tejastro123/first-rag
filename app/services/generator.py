"""
Generation Service.
Handles grounded LLM response synthesis with session-aware conversation history.
Supports standard and streaming (SSE) responses via Cohere command-a-03-2025.
"""
from typing import List, AsyncGenerator
import cohere
from loguru import logger

from app.config import get_settings
from app.schemas import DocumentChunk

settings = get_settings()

SYSTEM_PROMPT = (
    "You are an elite enterprise AI assistant with access to a curated knowledge base. "
    "Answer the user's query ONLY using the provided RELEVANT CONTEXT. "
    "If the answer is not contained in the context, state exactly: "
    "'I cannot answer this based on the available documentation.' "
    "Do not hallucinate or invent facts. "
    "Cite sources inline using [1], [2] format corresponding to the document numbers."
)

SYSTEM_PROMPT_STREAM = (
    "You are an elite enterprise AI assistant. Answer the user's query ONLY "
    "using the provided RELEVANT CONTEXT. "
    "If the answer is not in the context, state: 'I cannot answer this based on the available documentation.' "
    "Cite sources using [1], [2] format."
)


class GenerationService:
    """
    LLM generation engine with:
    - Grounded context injection
    - Citation enforcement
    - Multi-turn session history awareness
    - Async streaming support
    """

    def __init__(self):
        self.cohere_client = cohere.AsyncClient(api_key=settings.COHERE_API_KEY)

    def _build_context_block(self, chunks: List[DocumentChunk]) -> str:
        """Format retrieved chunks as a numbered reference list."""
        if not chunks:
            return "RELEVANT CONTEXT:\n---\n(No relevant documents found.)\n"

        context_str = "RELEVANT CONTEXT:\n---\n"
        for i, chunk in enumerate(chunks):
            context_str += f"Document [{i + 1}] (Relevance: {chunk.relevance_score:.2f}):\n"
            context_str += f"{chunk.text}\n---\n"
        return context_str

    def _build_user_message(
        self,
        query: str,
        chunks: List[DocumentChunk],
        conversation_context: str | None = None,
    ) -> str:
        """
        Compose the full user message incorporating:
        1. Contextual conversation history (if session-aware)
        2. Retrieved document chunks
        3. The current user query
        """
        parts = []
        if conversation_context:
            parts.append(conversation_context)
        parts.append(self._build_context_block(chunks))
        parts.append(f"USER QUERY: {query}")
        return "\n\n".join(parts)

    async def generate_answer(
        self,
        query: str,
        chunks: List[DocumentChunk],
        conversation_context: str | None = None,
    ) -> str:
        """Generates a complete, non-streaming grounded response."""
        user_content = self._build_user_message(query, chunks, conversation_context)

        response = await self.cohere_client.chat(
            model="command-a-03-2025",
            message=user_content,
            preamble=SYSTEM_PROMPT,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
        answer = response.text
        logger.debug(f"Generated answer ({len(answer)} chars) for query: '{query[:60]}...'")
        return answer

    async def generate_stream(
        self,
        query: str,
        chunks: List[DocumentChunk],
        conversation_context: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yields text chunks as an async generator for Server-Sent Events streaming."""
        user_content = self._build_user_message(query, chunks, conversation_context)

        stream = self.cohere_client.chat_stream(
            model="command-a-03-2025",
            message=user_content,
            preamble=SYSTEM_PROMPT_STREAM,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )

        async for event in stream:
            if event.event_type == "text-generation":
                yield event.text
