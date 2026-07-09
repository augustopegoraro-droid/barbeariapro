# file: app/main.py
"""Ponto de entrada da API BarbeariaPro (P0)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import agenda, auth, barbeiro, billing, platform_billing, bot, chatwoot, clientes, conversations, crm, dashboard, debts, empresa, equipe, financeiro, gestor, health, imports, integracoes, kernel_ia, loyalty, memberships, platform, reminders, reschedule, security, servicos, wa_webhook
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="BarbeariaPro API",
    version="0.1.0",
    lifespan=lifespan,
    # V12: /docs, /redoc e /openapi.json desligados por padrão em produção
    # (settings.docs_enabled=False); ligar só em dev/staging via env.
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(bot.router)
app.include_router(wa_webhook.router)
app.include_router(chatwoot.router)
app.include_router(loyalty.router)
app.include_router(loyalty.internal_router)
app.include_router(reminders.internal_router)
app.include_router(memberships.router)
app.include_router(memberships.internal_router)
app.include_router(agenda.router)
app.include_router(barbeiro.router)
app.include_router(financeiro.router)
app.include_router(gestor.router)
app.include_router(gestor.internal_router)
app.include_router(equipe.router)
app.include_router(clientes.router)
app.include_router(dashboard.router)
app.include_router(servicos.router)
app.include_router(empresa.router)
app.include_router(crm.router)
app.include_router(conversations.router)
app.include_router(integracoes.router)
app.include_router(imports.router)
app.include_router(debts.router)
app.include_router(kernel_ia.router)
app.include_router(reschedule.router)
app.include_router(platform.router)
app.include_router(billing.router)
app.include_router(billing.internal_router)
app.include_router(platform_billing.router)
app.include_router(security.router)
app.include_router(security.internal_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "BarbeariaPro API", "docs": "/docs" if settings.docs_enabled else "disabled"}
