import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def generate_device_token() -> tuple[str, str, str]:
    """Generate a structured device token.

    Returns ``(full_token, prefix, hashed_secret)``.

    Token format: ``midscale_device_<prefix>_<secret>`` where prefix is
    8 URL-safe chars (not secret, used for fast DB lookup) and secret is
    48 URL-safe chars (bcrypt-hashed in the database).
    """
    raw_prefix = secrets.token_urlsafe(6)
    prefix = raw_prefix[:8]
    secret = secrets.token_urlsafe(36)
    full_token = f"midscale_device_{prefix}_{secret}"
    hashed_secret = hash_password(secret)
    return full_token, prefix, hashed_secret


def create_access_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def create_refresh_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


def encrypt_private_key(key: str) -> str:
    f = Fernet(settings.encryption_key.encode())
    return f.encrypt(key.encode()).decode()


def decrypt_private_key(encrypted: str) -> str:
    f = Fernet(settings.encryption_key.encode())
    return f.decrypt(encrypted.encode()).decode()
