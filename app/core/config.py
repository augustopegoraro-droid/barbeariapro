# file: app/core/config.py
"""Configuração da aplicação (lida de variáveis de ambiente / .env)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App / JWT
    secret_key: str = Field(..., description="Chave HMAC para assinar o JWT.")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Conexão do APP: role NÃO-superuser e NÃO-dona das tabelas (RLS ativo).
    # Driver async psycopg3: postgresql+psycopg://...
    database_url: str = Field(..., description="URL async da role do app.")

    # Bot / n8n chatbot
    bot_api_key: str = ""
    bot_organization_id: int = 0
    bot_unit_id: int = 0

    # Evolution API (envio de mensagens WhatsApp)
    evolution_api_url: str = ""
    evolution_instance_name: str = ""
    evolution_api_key: str = ""

    # Reativação de clientes
    reactivation_trigger_days: int = 60
    reactivation_cooldown_days: int = 60


settings = Settings()  # type: ignore[call-arg]
