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
    # Curto por desenho (D-68, Fase 3): a revogação real vive no refresh token/sessions,
    # não em esperar o access expirar. Ver app/core/security.py e app/api/auth.py.
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Redis (D-68, Fase 3): rate-limit/lockout de login, tickets de SSE de uso único,
    # denylist curta de jti no logout. Dado 100% efêmero — a fonte de verdade de
    # sessão/revogação é a tabela `sessions` no Postgres (ver models/session.py).
    redis_url: str = "redis://redis:6379/0"

    # Lockout de login (V2/V13): contadores por IP e por IP+email no Redis.
    login_max_attempts: int = 5
    login_lockout_window_seconds: int = 900
    login_lockout_duration_seconds: int = 900

    # Rate limiting (V2, slowapi). Desligar só em teste/staging automatizado —
    # o cliente ASGI de teste compartilha "IP" (127.0.0.1) entre TODOS os
    # testes da suíte, então o limite real estouraria em segundos.
    rate_limit_enabled: bool = True

    # /docs, /redoc, /openapi.json — desligados por padrão (V12); ligar só em dev/staging.
    docs_enabled: bool = False

    # Conexão do APP: role NÃO-superuser e NÃO-dona das tabelas (RLS ativo).
    # Driver async psycopg3: postgresql+psycopg://...
    database_url: str = Field(..., description="URL async da role do app.")

    # Fuso horário de referência para agregações por dia (dashboard/financeiro/agenda)
    app_timezone: str = "America/Sao_Paulo"

    # CORS: origens permitidas, separadas por vírgula
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    # CORS: regex de origem (opcional) — casa origens dinâmicas como os
    # subdomínios de tenant do SaaS multi-tenant (ex.: https://<org>.taylorethedy.com).
    # Vazio = desligado (só a lista acima vale). É OR com cors_origins.
    cors_origin_regex: str = ""

    # Endpoints de debug (ex.: /bot/debounce/debug-set-session) — manter False em produção
    enable_debug_endpoints: bool = False

    # Billing do SaaS (superadmin M7). 'mock' é o default fail-safe: sem chave
    # Stripe o sistema opera com o provider de desenvolvimento. Enforcement de
    # limites de plano: off (não checa) | log (permite e loga) | hard (bloqueia).
    billing_provider: str = "mock"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    billing_grace_days_past_due: int = 7
    billing_enforcement: str = "log"

    # Bot / n8n chatbot
    bot_api_key: str = ""
    bot_organization_id: int = 0
    bot_unit_id: int = 0

    # Evolution API (envio de mensagens WhatsApp)
    evolution_api_url: str = ""
    evolution_instance_name: str = ""
    evolution_api_key: str = ""

    # Kernel IA (assistente in-app, /kernel-ia/query). Provedor: Anthropic (Claude).
    # Vazio → endpoint responde mensagem amigável "IA não configurada" (sem crash).
    anthropic_api_key: str = ""
    kernel_ia_model: str = "claude-opus-4-8"

    # Webhook direto Evolution → FastAPI (substitui debounce do n8n para o CRM)
    # N8N_WEBHOOK_URL: URL base do n8n para forward (ex: http://host.docker.internal:5678)
    # WA_WEBHOOK_SECRET: se definido, valida o header X-Webhook-Secret em /bot/wa-webhook
    n8n_webhook_url: str = ""
    wa_webhook_secret: str = ""

    # Chatwoot (D-49 — camada de atendimento/omnichannel). Defaults vazios: inerte.
    # CHATWOOT_WEBHOOK_TOKEN: segredo do header X-Chatwoot-Token em /chatwoot/webhook
    #   (obrigatório p/ o endpoint operar; vazio → 503).
    # Os demais (api_url/account_id/api_token) servem ao envio reverso (Fase 4 completa).
    chatwoot_webhook_token: str = ""
    chatwoot_api_url: str = ""
    chatwoot_account_id: int = 0
    chatwoot_api_token: str = ""

    # Google Calendar (Fase 2 — OAuth2 + sync de eventos). Default vazio:
    # sem credenciais, o módulo de integração fica inerte (não afeta produção).
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    google_calendar_scopes: str = "https://www.googleapis.com/auth/calendar.events"
    # Chave Fernet (urlsafe-base64, 32 bytes) p/ cifrar tokens OAuth em repouso.
    token_encryption_key: str = ""
    # URL do frontend para redirecionar após o callback OAuth (ex.: /admin/configuracoes).
    # Se vazio, o callback devolve JSON (útil em testes de API diretos).
    google_frontend_success_url: str = ""

    # Site público do cliente final (D-79). Cookie de sessão de longa duração:
    # Domain compartilhado apex ↔ api. (ex.: ".taylorethedy.com"); vazio em dev
    # (cookie host-only). 400 dias = teto aceito pelo Safari p/ cookie de servidor.
    public_cookie_domain: str = ""
    public_session_max_age_days: int = 400
    # Antecedência mínima (horas) para o cliente cancelar pelo site (fixo na v1).
    public_cancel_min_hours: int = 2

    # Reativação de clientes
    reactivation_trigger_days: int = 60
    reactivation_cooldown_days: int = 60

    # Lembrete de agendamento (anti no-show)
    reminder_lead_hours: int = 24   # antecedência do lembrete
    reminder_window_hours: int = 2  # largura da janela (sobrepõe cron horário)


settings = Settings()  # type: ignore[call-arg]
