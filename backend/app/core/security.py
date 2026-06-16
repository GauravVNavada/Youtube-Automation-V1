from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings


PASSWORD_HASH_PREFIX = "bcrypt-sha256$"


def hash_password(password: str) -> str:
    password_bytes = _password_digest(password)
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return f"{PASSWORD_HASH_PREFIX}{hashed.decode('utf-8')}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith(PASSWORD_HASH_PREFIX):
            expected = password_hash.removeprefix(PASSWORD_HASH_PREFIX).encode("utf-8")
            return bcrypt.checkpw(_password_digest(password), expected)
        return _verify_legacy_bcrypt_password(password, password_hash)
    except (TypeError, ValueError):
        return False


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None


def _password_digest(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def _verify_legacy_bcrypt_password(password: str, password_hash: str) -> bool:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        return False
    return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
