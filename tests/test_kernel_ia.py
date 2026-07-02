"""Kernel IA (navegação) — RBAC por papel, catálogo de rotas e endpoint.

O Kernel IA encaminha o usuário para a página certa (não responde dados → menos
alucinação). Testes cobrem o RBAC de capacidade (rotas/tools por papel), o dispatch
de navegação e o endpoint (auth + caminho sem key). O LLM não é mockado.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import kernel_ia
from app.services.kernel_ia import KernelCtx


# ─── RBAC por capacidade (puro) ─────────────────────────────────────────────────

def test_rotas_por_papel():
    gestor = kernel_ia._routes_for_role("owner")
    assert {"financeiro", "gestor", "assinaturas", "clientes"} <= set(gestor)
    barber = kernel_ia._routes_for_role("barber")
    assert set(barber) == {"agenda"}          # barbeiro só a própria agenda
    assert "financeiro" not in barber          # default-deny


def test_tools_por_papel():
    assert {t["function"]["name"] for t in kernel_ia._tools_for_role("owner")} == {"navegar"}
    assert {t["function"]["name"] for t in kernel_ia._tools_for_role("barber")} == {
        "navegar",
        "solicitar_remarcacao_turno",
    }


@pytest.mark.asyncio
async def test_navegar_dispatch_seta_rota():
    ctx = KernelCtx(role="owner", org_id=1)
    out = await kernel_ia._dispatch("navegar", {"pagina": "financeiro"}, None, ctx)
    assert out.get("ok") is True
    assert ctx.route == "/admin/financeiro"


@pytest.mark.asyncio
async def test_navegar_barbeiro_nao_alcanca_financeiro():
    ctx = KernelCtx(role="barber", org_id=1, barber_id=5)
    out = await kernel_ia._dispatch("navegar", {"pagina": "financeiro"}, None, ctx)
    assert "erro" in out and ctx.route is None  # rota não existe no catálogo do barbeiro


# ─── endpoint ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_exige_auth(client):
    r = await client.post("/kernel-ia/query", json={"prompt": "abrir agenda"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_query_sem_key_responde_gracioso(client, auth_headers):
    if settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY configurada; teste cobre o caminho SEM key.")
    r = await client.post(
        "/kernel-ia/query", json={"prompt": "abrir agenda"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "config"
