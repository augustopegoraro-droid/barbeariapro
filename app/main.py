# file: app/main.py
"""Ponto de entrada da API BarbeariaPro (P0)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agenda, auth, barbeiro, bot, chatwoot, clientes, conversations, crm, dashboard, empresa, equipe, financeiro, gestor, health, integracoes, loyalty, memberships, reminders, servicos, wa_webhook
from app.core.config import settings
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="BarbeariaPro API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
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


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "BarbeariaPro API", "docs": "/docs"}
