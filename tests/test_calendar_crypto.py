"""Testes unitários da criptografia de tokens (app/core/crypto.py) — sem rede/DB."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import settings


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_encryption_key", key)
    crypto._fernet_for.cache_clear()
    yield key
    crypto._fernet_for.cache_clear()


def test_round_trip_preserva_o_token(fernet_key):
    secret = "1//0gRefreshTokenExemplo-abc_DEF"
    blob = crypto.encrypt_token(secret)
    assert isinstance(blob, bytes)
    assert blob != secret.encode("utf-8")  # de fato cifrado
    assert crypto.decrypt_token(blob) == secret


def test_cifragem_nao_deterministica(fernet_key):
    # Fernet inclui IV/timestamp: duas cifragens do mesmo texto diferem.
    a = crypto.encrypt_token("mesmo-token")
    b = crypto.encrypt_token("mesmo-token")
    assert a != b
    assert crypto.decrypt_token(a) == crypto.decrypt_token(b) == "mesmo-token"


def test_sem_chave_levanta(monkeypatch):
    monkeypatch.setattr(settings, "token_encryption_key", "")
    crypto._fernet_for.cache_clear()
    with pytest.raises(crypto.TokenCryptoError):
        crypto.encrypt_token("x")


def test_chave_invalida_levanta(monkeypatch):
    monkeypatch.setattr(settings, "token_encryption_key", "isto-nao-e-uma-fernet-key")
    crypto._fernet_for.cache_clear()
    with pytest.raises(crypto.TokenCryptoError):
        crypto.encrypt_token("x")


def test_token_corrompido_levanta(fernet_key):
    with pytest.raises(crypto.TokenCryptoError):
        crypto.decrypt_token(b"conteudo-que-nao-e-fernet")


def test_chave_errada_nao_decifra(monkeypatch):
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode())
    crypto._fernet_for.cache_clear()
    blob = crypto.encrypt_token("segredo")
    # Troca a chave: decifrar deve falhar (não vaza o segredo).
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode())
    crypto._fernet_for.cache_clear()
    with pytest.raises(crypto.TokenCryptoError):
        crypto.decrypt_token(blob)
