from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    """
    Core application settings with environment variable injection.
    Production systems strictly separate config from code.
    """
    PROJECT_NAME: str = "OmniForge Advanced RAG"
    API_V1_STR: str = "/api/v1"

    # API Keys (Loaded from .env or Secrets Manager)
    OPENAI_API_KEY: str | None = None
    COHERE_API_KEY: str
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None

    # RAG Tuning Parameters
    QDRANT_COLLECTION_NAME: str = "enterprise_knowledge_base"
    RETRIEVAL_TOP_K: int = 40        # Broad initial fetch
    RERANK_TOP_K: int = 5            # Highly relevant chunks passed to LLM
    MAX_TOKENS: int = 1500           # Output limit
    TEMPERATURE: float = 0.1         # Low temp for factual grounding

    # Chunking Parameters
    CHUNK_SIZE: int = 512            # Characters per chunk
    CHUNK_OVERLAP: int = 64          # Overlap between chunks for context continuity

    # JWT Auth Settings
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_openssl_rand_-hex_32"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 20  # Max requests per IP per minute

    # Session Memory
    SESSION_TTL_SECONDS: int = 3600  # Session expires after 1 hour of inactivity
    MAX_SESSION_HISTORY: int = 10    # Max conversation turns kept in memory

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    """Dependency injection for settings to ensure singleton pattern."""
    return Settings()
