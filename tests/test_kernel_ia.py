"""Kernel IA — endpoint (/kernel-ia/query), RBAC por papel e camada de tools.

Não mocka o LLM. Cobre: exige auth; caminho gracioso sem OPENAI_API_KEY; o RBAC de
capacidade (tools filtradas por papel — default-deny p/ barbeiro); e o dispatch das
tools contra a sessão RLS.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import kernel_ia
from app.services.kernel_ia import KernelCtx

ORG = 1


def _tool_names(role: str) -> set[str]:
    return {t["function"]["name"] for t in kernel_ia._tools_for_role(role)}


# ─── RBAC por capacidade (puro, sem DB nem LLM) ─────────────────────────────────

def test_rbac_gestor_tem_tools_de_negocio():
    names = _tool_names("owner")
    assert "financeiro" in names and "mrr" in names and "resumo_clientes" in names
    assert "solicitar_remarcacao_turno" not in names  # gestor não pede remarcação


def test_rbac_barbeiro_nao_tem_financeiro():
    names = _tool_names("barber")
    assert "financeiro" not in names and "mrr" not in names  # default-deny
    assert "solicitar_remarcacao_turno" in names
    assert "buracos_agenda" in names


# ─── endpoint ──────────────────────────────────────────────────────────────────

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
    assert r.json()["intent"] == "config"


# ─── dispatch das tools (contra RLS) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_financeiro_dispatch():
    ctx = KernelCtx(role="owner", org_id=ORG)
    async with AsyncSessionLocal() as s:
        await set_current_org(s, ORG)
        out = await kernel_ia._dispatch("financeiro", {"period": "mes"}, s, ctx)
    assert {"revenue", "commissions", "expenses", "net", "periodo"} <= out.keys()


@pytest.mark.asyncio
async def test_tool_resumo_clientes_dispatch():
    ctx = KernelCtx(role="owner", org_id=ORG)
    async with AsyncSessionLocal() as s:
        await set_current_org(s, ORG)
        out = await kernel_ia._dispatch("resumo_clientes", {}, s, ctx)
    assert set(out.keys()) == {"total", "com_email", "com_nascimento"}
