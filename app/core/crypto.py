# file: app/core/crypto.py
"""Criptografia simétrica de tokens de integração (Fernet).

Cifra access/refresh tokens de OAuth antes de persistir em
`integration_accounts.token_encrypted` / `refresh_token_encrypted` (LargeBinary).

A chave vem de `settings.token_encryption_key` (Fernet key urlsafe-base64 de
32 bytes — gere com `cryptography.fernet.Fernet.generate_key()`). Em ambientes
sem a chave configurada, qualquer uso levanta `TokenCryptoError` explícito; o
import nunca quebra (produção ainda não usa Calendar).
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TokenCryptoError(RuntimeError):
    """Erro de configuração ou uso da criptografia de tokens."""


@lru_cache(maxsize=4)
def _fernet_for(key: str) -> Fernet:
    """Constrói (e cacheia por valor de chave) o Fernet. Cache permite trocar a
    chave em testes via `_fernet_for.cache_clear()`."""
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise TokenCryptoError(f"TOKEN_ENCRYPTION_KEY inválida: {exc}") from exc


def _fernet() -> Fernet:
    key = settings.token_encryption_key
    if not key:
        raise TokenCryptoError(
            "TOKEN_ENCRYPTION_KEY não configurada — defina uma chave Fernet "
            "(Fernet.generate_key()) no ambiente antes de cifrar/decifrar tokens."
        )
    return _fernet_for(key)


def encrypt_token(plaintext: str) -> bytes:
    """Cifra uma string de token e devolve bytes prontos para LargeBinary."""
    if plaintext is None:
        raise TokenCryptoError("plaintext não pode ser None")
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_token(token: bytes) -> str:
    """Decifra bytes cifrados de volta para a string original do token."""
    try:
        return _fernet().decrypt(bytes(token)).decode("utf-8")
    except InvalidToken as exc:
        raise TokenCryptoError(
            "token cifrado inválido ou chave de criptografia incorreta"
        ) from exc
