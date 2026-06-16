"""
Testes do endpoint /dashboard/operacional (métricas de CRM/IA):
volume de leads, serviços realizados, picos de demanda e fluxo comercial
vs fora do horário comercial.

Rodam contra o Postgres semeado (org 3) sob RLS. Fixtures de conftest.
"""
from __future__ import annotations

import pytest

STAGES = ["novo_contato", "conversando", "agendado", "concluido", "perdido"]


@pytest.mark.asyncio
async def test_operacional_sem_token_401(client):
    resp = await client.get("/dashboard/operacional")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_operacional_estrutura_e_consistencia(client, auth_headers):
    resp = await client.get("/dashboard/operacional?period=30d", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # estágios do funil completos e na ordem
    assert [c["stage"] for c in body["leads_por_estagio"]] == STAGES

    # série diária preenchida (30 dias)
    assert len(body["leads_por_dia"]) == 30

    # picos de demanda: horas válidas 0..23
    for p in body["picos_demanda"]:
        assert 0 <= p["hour"] <= 23
        assert p["count"] >= 0

    # serviços realizados é uma lista
    assert isinstance(body["servicos_realizados"], list)

    # fluxo: comercial + fora == total de leads do período; pct somam ~100 (ou 0)
    fluxo = body["fluxo"]
    assert fluxo["comercial"] + fluxo["fora"] == body["leads_total"]
    if body["leads_total"] > 0:
        assert round(fluxo["comercial_pct"] + fluxo["fora_pct"]) == 100


@pytest.mark.asyncio
async def test_operacional_conta_leads_criados(client, auth_headers):
    base = (
        await client.get("/dashboard/operacional?period=30d", headers=auth_headers)
    ).json()["leads_total"]

    ids = []
    for nome in ("Op Lead 1", "Op Lead 2"):
        r = await client.post("/crm/leads", json={"name": nome}, headers=auth_headers)
        assert r.status_code == 201
        ids.append(r.json()["id"])

    after = (
        await client.get("/dashboard/operacional?period=30d", headers=auth_headers)
    ).json()
    assert after["leads_total"] == base + 2
    # consistência do fluxo após inserções
    assert after["fluxo"]["comercial"] + after["fluxo"]["fora"] == after["leads_total"]

    # cleanup
    for lead_id in ids:
        await client.delete(f"/crm/leads/{lead_id}", headers=auth_headers)


@pytest.mark.asyncio
async def test_operacional_lead_novo_aparece_no_estagio(client, auth_headers):
    r = await client.post(
        "/crm/leads", json={"name": "Estagio Lead", "stage": "conversando"},
        headers=auth_headers,
    )
    lead_id = r.json()["id"]

    body = (
        await client.get("/dashboard/operacional?period=30d", headers=auth_headers)
    ).json()
    conversando = next(c for c in body["leads_por_estagio"] if c["stage"] == "conversando")
    assert conversando["count"] >= 1

    await client.delete(f"/crm/leads/{lead_id}", headers=auth_headers)
