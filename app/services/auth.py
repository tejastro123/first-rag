"""
JWT-based Authentication Service.
Provides token generation and verification for API security.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from loguru import logger

from app.config import get_settings

settings = get_settings()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token scheme for Swagger UI compatibility
bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Demo user store — replace with a real database (PostgreSQL) in production
# ---------------------------------------------------------------------------
DEMO_USERS: dict[str, str] = {
    "admin": pwd_context.hash("admin123"),
    "user": pwd_context.hash("user"),
}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def authenticate_user(username: str, password: str) -> Optional[str]:
    """Returns the username if credentials are valid, else None."""
    hashed = DEMO_USERS.get(username)
    if not hashed:
        return None
    if not verify_password(password, hashed):
        return None
    return username

def create_access_token(subject: str) -> str:
    """Create a signed JWT access token for the given subject (username)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """
    FastAPI dependency: Validates the Bearer JWT token on protected routes.
    Raises HTTP 401 if the token is missing, expired, or invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise credentials_exception
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise credentials_exception
