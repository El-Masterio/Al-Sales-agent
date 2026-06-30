"""
app/services/security.py
========================
Password hashing, JWT issuance/verification, and Fernet-based encryption
for storing third-party API keys and OAuth tokens at rest.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =============================================================================
# Password hashing
# =============================================================================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# =============================================================================
# JWT
# =============================================================================

def create_access_token(user_id: uuid.UUID, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: uuid.UUID, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: Literal["access", "refresh"] = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise ValueError(f"Expected {expected_type} token, got {payload.get('type')}")

    return payload


# =============================================================================
# Encryption — for OAuth tokens and API keys at rest
# =============================================================================

def _get_fernet() -> Fernet:
    key_bytes = settings.ENCRYPTION_KEY.encode("utf-8")
    # Ensure key is valid base64 32-byte Fernet key; derive if not already formatted
    if len(key_bytes) != 44:  # standard Fernet key length when base64-encoded
        import hashlib
        digest = hashlib.sha256(key_bytes).digest()
        key_bytes = base64.urlsafe_b64encode(digest)
    return Fernet(key_bytes)


def encrypt_value(value: str) -> str:
    f = _get_fernet()
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted: str) -> str:
    f = _get_fernet()
    try:
        return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt value — invalid token or wrong key") from exc


def encrypt_json(data: dict[str, Any]) -> str:
    return encrypt_value(json.dumps(data))


def decrypt_json(encrypted: str) -> dict[str, Any]:
    return json.loads(decrypt_value(encrypted))


def key_preview(raw_key: str) -> str:
    """Last 4 chars, safe to display: sk-...a1b2"""
    if len(raw_key) <= 4:
        return "*" * len(raw_key)
    return f"...{raw_key[-4:]}"
