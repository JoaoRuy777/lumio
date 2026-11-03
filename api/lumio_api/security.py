"""Senhas (argon2), tokens JWT e cifra da community SNMP (Fernet)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

_hasher = PasswordHasher()

# Hash fixo para comparar quando o e-mail não existe: o login leva o mesmo
# tempo com ou sem usuário, e ninguém descobre e-mails cadastrados pelo relógio.
_DUMMY_HASH = _hasher.hash("lumio-usuario-inexistente")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_token(secret: str, *, user_id: UUID, tenant_id: UUID, role: str, ttl_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "tid": str(tenant_id), "role": role,
              "iat": now, "exp": now + timedelta(minutes=ttl_minutes)}
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> dict:
    """Levanta jwt.PyJWTError se o token for inválido ou expirado."""
    return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "tid", "exp"]})


class Cipher:
    def __init__(self, key: str):
        self._fernet = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as e:
            raise ValueError("community cifrada com outra chave (LUMIO_SECRET_KEY mudou?)") from e
