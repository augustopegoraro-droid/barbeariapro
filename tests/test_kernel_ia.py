"""Kernel IA (navegação + finanças) — RBAC por papel, catálogo de rotas e endpoint.

O Kernel IA encaminha o usuário para a página certa (não responde dados → menos
alucinação), exceto para owner/manager perguntando finanças, que ganham
`consultar_financas` (D-58 — dados determinísticos, ver `test_kernel_ia_finance.py`
pro formatador/guardrail). Testes cobrem o RBAC de capacidade (rotas/tools por
papel), o dispatch de navegação/finanças (fail-closed) e o endpoint (auth +
caminho sem key). O LLM não é mockado.
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
    assert {t["name"] for t in kernel_ia._tools_for_role("owner")} == {
        "navegar",
        "consultar_financas",
        "consultar_estoque",
    }
    assert {t["name"] for t in kernel_ia._tools_for_role("barber")} == {
        "navegar",
        "solicitar_remarcacao_turno",
    }


def test_tools_por_papel_financas_gestor():
    for role in ("owner", "manager"):
        names = {t["name"] for t in kernel_ia._tools_for_role(role)}
        assert "consultar_financas" in names


def test_tools_por_papel_financas_recepcao_bloqueada():
    # regressão: FULL_ACCESS inclui reception (navegação + estoque), mas dados
    # financeiros são MANAGER_ACCESS apenas — recepção não ganha consultar_financas.
    names = {t["name"] for t in kernel_ia._tools_for_role("reception")}
    assert names == {"navegar", "consultar_estoque"}
    assert "consultar_financas" not in names


def test_tools_por_papel_financas_barbeiro_bloqueado():
    names = {t["name"] for t in kernel_ia._tools_for_role("barber")}
    assert "consultar_financas" not in names


def test_tools_por_papel_estoque_full_access():
    # diferente do financeiro: recepção TEM consultar_estoque (opera estoque na UI).
    for role in ("owner", "manager", "reception"):
        names = {t["name"] for t in kernel_ia._tools_for_role(role)}
        assert "consultar_estoque" in names


def test_tools_por_papel_estoque_barbeiro_bloqueado():
    names = {t["name"] for t in kernel_ia._tools_for_role("barber")}
    assert "consultar_estoque" not in names


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


@pytest.mark.asyncio
async def test_consultar_financas_dispatch_barbeiro_bloqueado():
    ctx = KernelCtx(role="barber", org_id=1, barber_id=5)
    # db=None prova que o RBAC é checado ANTES de qualquer query.
    out = await kernel_ia._dispatch(
        "consultar_financas", {"topico": "financeiro", "periodo": "mes"}, None, ctx
    )
    assert "erro" in out
    assert ctx.finance_data_block is None


@pytest.mark.asyncio
async def test_consultar_financas_dispatch_recepcao_bloqueada():
    # regressão explícita do gap FULL_ACCESS (inclui reception) vs. MANAGER_ACCESS.
    ctx = KernelCtx(role="reception", org_id=1)
    out = await kernel_ia._dispatch(
        "consultar_financas", {"topico": "financeiro", "periodo": "mes"}, None, ctx
    )
    assert "erro" in out
    assert ctx.finance_data_block is None


@pytest.mark.asyncio
async def test_consultar_financas_dispatch_topico_desconhecido():
    ctx = KernelCtx(role="owner", org_id=1)
    out = await kernel_ia._dispatch(
        "consultar_financas", {"topico": "bogus", "periodo": "mes"}, None, ctx
    )
    assert "erro" in out
    assert ctx.finance_data_block is None


@pytest.mark.asyncio
async def test_consultar_estoque_dispatch_barbeiro_bloqueado():
    ctx = KernelCtx(role="barber", org_id=1, barber_id=5)
    # db=None prova que o RBAC é checado ANTES de qualquer query.
    out = await kernel_ia._dispatch("consultar_estoque", {"topico": "alertas"}, None, ctx)
    assert "erro" in out
    assert ctx.stock_data_block is None


@pytest.mark.asyncio
async def test_consultar_estoque_dispatch_topico_desconhecido():
    ctx = KernelCtx(role="owner", org_id=1)
    out = await kernel_ia._dispatch("consultar_estoque", {"topico": "bogus"}, None, ctx)
    assert "erro" in out
    assert ctx.stock_data_block is None


@pytest.mark.asyncio
async def test_consultar_estoque_dispatch_recepcao_passa_do_rbac(monkeypatch):
    # regressão-chave: diferente do financeiro, recepção passa a checagem de
    # RBAC (o erro, se houver, viria do fetch de dados — mockado aqui — não do RBAC).
    async def _fake_fetch(db, topic, periodo):
        return "bloco de estoque falso"

    monkeypatch.setattr(kernel_ia.kernel_ia_stock, "fetch_and_format", _fake_fetch)
    ctx = KernelCtx(role="reception", org_id=1)
    out = await kernel_ia._dispatch("consultar_estoque", {"topico": "alertas"}, None, ctx)
    assert out == {"ok": True}
    assert ctx.stock_topic == "alertas"
    assert ctx.stock_data_block == "bloco de estoque falso"


# ─── endpoint ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_exige_auth(client):
    r = await client.post("/kernel-ia/query", json={"prompt": "abrir agenda"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_query_sem_key_responde_gracioso(client, auth_headers):
    if settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY configurada; teste cobre o caminho SEM key.")
    r = await client.post(
        "/kernel-ia/query", json={"prompt": "abrir agenda"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "config"
