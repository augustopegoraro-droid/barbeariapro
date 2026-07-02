"""Kernel IA — endpoint (/kernel-ia/query) + camada de tools.

Não mocka o LLM (custaria uma chamada real). Cobre: exige auth; caminho gracioso
sem OPENAI_API_KEY; e o dispatch das tools contra a sessão RLS (a parte que integra
com `management.py`).
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import kernel_ia

ORG = 1


@pytest.mark.asyncio
async def test_query_exige_auth(client):
    r = await client.post("/kernel-ia/query", json={"prompt": "faturamento do mês"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_query_sem_key_responde_gracioso(client, auth_headers):
    if settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY configurada; teste cobre o caminho SEM key.")
    r = await client.post(
        "/kernel-ia/query", json={"prompt": "faturamento do mês"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "config"
    assert "configurad" in body["message"].lower()


@pytest.mark.asyncio
async def test_tool_financeiro_dispatch():
    async with AsyncSessionLocal() as s:
        await set_current_org(s, ORG)
        out = await kernel_ia._dispatch("financeiro", {"period": "mes"}, s, None)
    assert {"revenue", "commissions", "expenses", "net", "periodo"} <= out.keys()


@pytest.mark.asyncio
async def test_tool_resumo_clientes_dispatch():
    async with AsyncSessionLocal() as s:
        await set_current_org(s, ORG)
        out = await kernel_ia._dispatch("resumo_clientes", {}, s, None)
    assert set(out.keys()) == {"total", "com_email", "com_nascimento"}
    assert out["total"] >= 0
