"""
Session Memory Manager.
Provides in-process TTL-based conversation history for multi-turn RAG.
Drop-in replaceable with Redis (redis-py) for distributed deployments.
"""
import uuid
from typing import List, Dict, Optional
from cachetools import TTLCache
from loguru import logger

from app.config import get_settings

settings = get_settings()

# TTL cache: max 1000 concurrent sessions, each expired after SESSION_TTL_SECONDS
_session_store: TTLCache = TTLCache(
    maxsize=1000,
    ttl=settings.SESSION_TTL_SECONDS
)

class Turn:
    """Represents a single conversation exchange."""
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}

def create_session() -> str:
    """Generate a new unique session ID."""
    session_id = str(uuid.uuid4())
    _session_store[session_id] = []
    logger.info(f"New session created: {session_id}")
    return session_id

def get_history(session_id: str) -> List[Dict[str, str]]:
    """Retrieve the conversation history for a session."""
    history = _session_store.get(session_id, [])
    return [t.to_dict() for t in history]

def add_turn(session_id: str, user_message: str, assistant_response: str) -> None:
    """
    Append a user/assistant exchange to the session.
    Auto-creates the session if it doesn't exist.
    Trims history to the configured rolling window (MAX_SESSION_HISTORY turns).
    """
    if session_id not in _session_store:
        _session_store[session_id] = []

    history: List[Turn] = _session_store[session_id]
    history.append(Turn(role="user", content=user_message))
    history.append(Turn(role="assistant", content=assistant_response))

    # Rolling window: keep only the last N turns (pairs) to control context length
    max_messages = settings.MAX_SESSION_HISTORY * 2
    if len(history) > max_messages:
        history = history[-max_messages:]

    _session_store[session_id] = history
    logger.debug(f"Session {session_id}: {len(history) // 2} turn(s) in memory.")

def build_context_with_history(session_id: Optional[str], current_query: str) -> str:
    """
    Build a contextually-aware query string by prepending conversation history.
    This helps the LLM understand follow-up questions.
    """
    if not session_id:
        return current_query

    history = get_history(session_id)
    if not history:
        return current_query

    history_text = "\n".join(
        f"{turn['role'].capitalize()}: {turn['content']}"
        for turn in history[-6:]  # last 3 turns for context injection
    )
    return f"[CONVERSATION HISTORY]\n{history_text}\n\n[CURRENT QUERY]\n{current_query}"

def delete_session(session_id: str) -> None:
    """Explicitly remove a session from the store."""
    _session_store.pop(session_id, None)
    logger.info(f"Session deleted: {session_id}")
