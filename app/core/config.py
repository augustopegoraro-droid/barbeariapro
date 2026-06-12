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

    # Fuso horário de referência para agregações por dia (dashboard/financeiro/agenda)
    app_timezone: str = "America/Sao_Paulo"

    # CORS: origens permitidas, separadas por vírgula
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    # Endpoints de debug (ex.: /bot/debounce/debug-set-session) — manter False em produção
    enable_debug_endpoints: bool = False

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

    # Lembrete de agendamento (anti no-show)
    reminder_lead_hours: int = 24   # antecedência do lembrete
    reminder_window_hours: int = 2  # largura da janela (sobrepõe cron horário)


settings = Settings()  # type: ignore[call-arg]
