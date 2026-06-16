from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hmac
import hashlib
import json
import time

import bcrypt
try:
    from jose import JWTError, jwt
except ModuleNotFoundError:  # pragma: no cover - fallback for source recovery/local dev
    JWTError = Exception
    jwt = None

from app.core.config import get_settings


PASSWORD_HASH_PREFIX = "bcrypt-sha256$"


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_password_digest(password), bcrypt.gensalt())
    return f"{PASSWORD_HASH_PREFIX}{hashed.decode('utf-8')}"


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        if password_hash.startswith(PASSWORD_HASH_PREFIX):
            encoded = password_hash.removeprefix(PASSWORD_HASH_PREFIX).encode("utf-8")
            return bcrypt.checkpw(_password_digest(password), encoded)
        return _verify_legacy_bcrypt_password(password, password_hash)
    except ValueError:
        return False


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": subject, "exp": expires_at}
    if jwt is not None:
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return _encode_hs256(payload, settings.jwt_secret)


def decode_access_token(token: str) -> str | None:
    settings = get_settings()
    try:
        if jwt is not None:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        else:
            payload = _decode_hs256(token, settings.jwt_secret)
    except JWTError:
        return None
    subject = payload.get("sub")
    return str(subject) if subject is not None else None


def _password_digest(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def _verify_legacy_bcrypt_password(password: str, password_hash: str) -> bool:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        return False
    return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))


def _encode_hs256(payload: dict, secret: str) -> str:
    normalized = dict(payload)
    if isinstance(normalized.get("exp"), datetime):
        normalized["exp"] = int(normalized["exp"].timestamp())
    header = {"alg": "HS256", "typ": "JWT"}
    head = _b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = _b64(json.dumps(normalized, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(signature)}"


def _decode_hs256(token: str, secret: str) -> dict:
    head, body, signature = token.split(".")
    expected = hmac.new(secret.encode("utf-8"), f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(expected), signature):
        raise JWTError("Invalid signature")
    payload = json.loads(_unb64(body))
    if payload.get("exp") is not None and int(payload["exp"]) < int(time.time()):
        raise JWTError("Token expired")
    return payload


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))
