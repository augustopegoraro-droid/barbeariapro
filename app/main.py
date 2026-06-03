# file: app/main.py
"""Ponto de entrada da API BarbeariaPro (P0)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, bot, health
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="BarbeariaPro API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(bot.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "BarbeariaPro API", "docs": "/docs"}
