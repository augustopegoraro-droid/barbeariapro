"""
Smoke-tests dos endpoints de leitura que alimentam as telas do painel
(dashboard, agenda/appointments, equipe/settings, serviços, financeiro/analytics).

Garantem que cada tela tem backend respondendo 200 sob auth/RLS com a org semeada.
Não validam regra de negócio profunda — apenas contrato e disponibilidade.
"""
from __future__ import annotations

import pytest

HOJE = "2026-06-15"
MES = "2026-06"


@pytest.mark.asyncio
async def test_dashboard_responde(client, auth_headers):
    resp = await client.get("/dashboard?period=30d", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


@pytest.mark.asyncio
async def test_servicos_lista(client, auth_headers):
    resp = await client.get("/servicos", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_servicos_inclui_inativos(client, auth_headers):
    resp = await client.get("/servicos?include_inactive=true", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_equipe_lista(client, auth_headers):
    resp = await client.get("/equipe", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


@pytest.mark.asyncio
async def test_agenda_do_dia(client, auth_headers):
    resp = await client.get(f"/agenda?date={HOJE}", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_agenda_barbers_e_services(client, auth_headers):
    b = await client.get("/agenda/barbers", headers=auth_headers)
    s = await client.get("/agenda/services", headers=auth_headers)
    assert b.status_code == 200 and isinstance(b.json(), list)
    assert s.status_code == 200 and isinstance(s.json(), list)


@pytest.mark.asyncio
async def test_agenda_sem_date_422(client, auth_headers):
    resp = await client.get("/agenda", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_financeiro_do_dia(client, auth_headers):
    resp = await client.get(f"/financeiro?date={HOJE}", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


@pytest.mark.asyncio
async def test_financeiro_mensal(client, auth_headers):
    resp = await client.get(f"/financeiro/mensal?month={MES}", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_endpoints_sem_token_401(client):
    for path in ("/dashboard", "/servicos", "/equipe", f"/agenda?date={HOJE}"):
        resp = await client.get(path)
        assert resp.status_code == 401, path
