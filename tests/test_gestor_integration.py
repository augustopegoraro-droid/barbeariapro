"""Integração das tools de gestão (D-52).

Dashboard (JWT) reutiliza o `auth_headers` (owner da org semeada). Gating do bot
é testado sem precisar de telefone real cadastrado: um número desconhecido NÃO é
gestor → whoami=false e as tools sensíveis retornam 403.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.config import settings


# ─── dashboard (JWT + RBAC) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_financeiro_owner_ok(client, auth_headers):
    r = await client.get("/admin/gestor/financeiro?period=mes", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"revenue", "commissions", "expenses", "net", "by_method"} <= body.keys()
    assert body["period"] == "mês"


@pytest.mark.asyncio
async def test_dashboard_ranking_owner_ok(client, auth_headers):
    r = await client.get("/admin/gestor/ranking?period=mes", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["barbers"], list)


@pytest.mark.asyncio
async def test_dashboard_exige_auth(client):
    r = await client.get("/admin/gestor/financeiro?period=hoje")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_financeiro_mes_bate_com_financeiro_mensal(client, auth_headers):
    """Garante que a extração de barber_revenue_rows não regrediu: a receita do
    período 'mes' (dia 1→hoje) deve igualar a receita do mês corrente em
    /financeiro/mensal (dias futuros não têm atendimento concluído)."""
    month = date.today().strftime("%Y-%m")
    a = await client.get("/admin/gestor/financeiro?period=mes", headers=auth_headers)
    b = await client.get(f"/financeiro/mensal?month={month}", headers=auth_headers)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["revenue"] == pytest.approx(b.json()["total_revenue"])
    assert a.json()["commissions"] == pytest.approx(b.json()["total_commission"])


# ─── gating do bot (X-Bot-Token + telefone) ───────────────────────────────────

def _bot_headers():
    if not settings.bot_api_key or not settings.bot_organization_id:
        pytest.skip("BOT_API_KEY/BOT_ORGANIZATION_ID não configurados no ambiente.")
    return {"X-Bot-Token": settings.bot_api_key}


@pytest.mark.asyncio
async def test_bot_whoami_numero_desconhecido_nao_e_gestor(client):
    headers = _bot_headers()
    r = await client.get("/bot/gestor/whoami?phone=+5563999990000", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_manager"] is False


@pytest.mark.asyncio
async def test_bot_financeiro_sem_gestor_403(client):
    headers = _bot_headers()
    r = await client.get(
        "/bot/gestor/financeiro?requester_phone=+5563999990000&period=hoje",
        headers=headers,
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_bot_financeiro_token_invalido_401(client):
    if not settings.bot_api_key:
        pytest.skip("BOT_API_KEY não configurado.")
    r = await client.get(
        "/bot/gestor/financeiro?requester_phone=+5563999990000&period=hoje",
        headers={"X-Bot-Token": "token-errado"},
    )
    assert r.status_code == 401, r.text


# ─── Fase B — dashboard (JWT) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_inativos_ok(client, auth_headers):
    r = await client.get("/admin/gestor/inativos?limit=5", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "count" in body and isinstance(body["clients"], list)


@pytest.mark.asyncio
async def test_dashboard_buracos_ok(client, auth_headers):
    r = await client.get("/admin/gestor/buracos", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["barbers"], list)


@pytest.mark.asyncio
async def test_dashboard_ia_faturamento_ok(client, auth_headers):
    r = await client.get("/admin/gestor/ia-faturamento?period=mes", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"appointments", "revenue", "leads_after_hours"} <= body.keys()


@pytest.mark.asyncio
async def test_dashboard_mrr_ok(client, auth_headers):
    r = await client.get("/admin/gestor/mrr", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["active_count"], int)
    assert isinstance(body["mrr"], (int, float))


@pytest.mark.asyncio
async def test_dashboard_disparar_exige_auth(client):
    # Não dispara campanha real: apenas confirma que exige autenticação.
    r = await client.post("/admin/gestor/inativos/disparar")
    assert r.status_code in (401, 403)


# ─── Fase B — gating do bot ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bot_mrr_sem_gestor_403(client):
    headers = _bot_headers()
    r = await client.get(
        "/bot/gestor/mrr?requester_phone=+5563999990000", headers=headers
    )
    assert r.status_code == 403, r.text


# ─── Fase C — endpoints internos (cron) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_internal_resumo_diario_ok(client):
    headers = _bot_headers()
    r = await client.post("/internal/gestor/resumo-diario", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Sem telefone de gestor cadastrado no seed → nenhum envio.
    assert body["sent"] == 0
    assert "digest" in body


@pytest.mark.asyncio
async def test_internal_alertas_ok(client):
    headers = _bot_headers()
    r = await client.post("/internal/gestor/alertas", headers=headers)
    assert r.status_code == 200, r.text
    assert body_keys(r) >= {"alerts", "recipients", "sent"}


def body_keys(resp):
    return set(resp.json().keys())


@pytest.mark.asyncio
async def test_internal_resumo_diario_token_invalido_401(client):
    if not settings.bot_api_key:
        pytest.skip("BOT_API_KEY não configurado.")
    r = await client.post(
        "/internal/gestor/resumo-diario", headers={"X-Bot-Token": "errado"}
    )
    assert r.status_code == 401
