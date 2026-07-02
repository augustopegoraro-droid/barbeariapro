"""Gestão inteligente de equipe (doc gestaointeligente; migration 0025).

Cobre: cálculo de folha/cobertura (service, com mutação em sessão revertida),
endpoint /admin/gestor/folha (auth + shape) e configuração do modelo de trabalho
via /equipe (PATCH válido/ inválido). Determinístico — sem LLM.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, set_current_org
from app.services.management import payroll_summary, recurring_coverage, resolve_period
from models import Barber

ORG = 1


# ─── service (mutação em sessão com rollback) ───────────────────────────────────

@pytest.mark.asyncio
async def test_payroll_e_coverage_calculo():
    async with AsyncSessionLocal() as s:
        await set_current_org(s, ORG)
        barber = (
            await s.execute(
                select(Barber).where(Barber.deleted_at.is_(None)).order_by(Barber.id).limit(1)
            )
        ).scalar_one()
        barber.work_model = "clt"
        barber.monthly_cost = Decimal("2000.00")
        barber.chair_rent = Decimal("300.00")
        await s.flush()

        df, dt, _ = resolve_period("mes")
        folha = await payroll_summary(s, df, dt)
        me = next(t for t in folha["team"] if t["barber_id"] == barber.id)
        assert me["work_model"] == "clt"
        assert me["monthly_cost"] == 2000.0
        assert me["chair_rent"] == 300.0
        assert folha["fixed_total"] >= 2000.0
        assert folha["net_cost"] == pytest.approx(
            folha["payroll_total"] - folha["chair_rent_income"]
        )

        cov = await recurring_coverage(s)
        assert cov["fixed_payroll"] >= 2000.0
        assert cov["net_fixed_payroll"] == pytest.approx(
            cov["fixed_payroll"] - cov["chair_rent_income"]
        )
        assert cov["surplus"] == pytest.approx(cov["mrr"] - cov["net_fixed_payroll"])
        assert isinstance(cov["covered"], bool)

        await s.rollback()  # staging intacto


@pytest.mark.asyncio
async def test_work_model_null_vira_comissionado():
    async with AsyncSessionLocal() as s:
        await set_current_org(s, ORG)
        df, dt, _ = resolve_period("mes")
        folha = await payroll_summary(s, df, dt)
        assert all(t["work_model"] in
                   {"clt", "mei", "comissionado", "aluguel_cadeira", "hibrido"}
                   for t in folha["team"])


# ─── endpoints ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_folha_exige_auth(client):
    r = await client.get("/admin/gestor/folha")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_folha_endpoint_shape(client, auth_headers):
    r = await client.get("/admin/gestor/folha?period=mes", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"team", "fixed_total", "payroll_total", "net_cost", "coverage"} <= body.keys()
    assert {"mrr", "covered", "surplus", "net_fixed_payroll"} <= body["coverage"].keys()


@pytest.mark.asyncio
async def test_equipe_configura_modelo_de_trabalho(client, auth_headers):
    # pega um barbeiro
    eq = (await client.get("/equipe", headers=auth_headers)).json()
    bid = eq["barbers"][0]["id"]

    # configura CLT com custo fixo
    r = await client.patch(
        f"/equipe/barbeiros/{bid}",
        json={"work_model": "clt", "monthly_cost": 1800.5},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["work_model"] == "clt"
    assert r.json()["monthly_cost"] == 1800.5

    # a folha reflete
    folha = (await client.get("/admin/gestor/folha", headers=auth_headers)).json()
    assert folha["fixed_total"] >= 1800.5

    # volta ao default (comissão pura) p/ não sujar o staging
    r2 = await client.patch(
        f"/equipe/barbeiros/{bid}",
        json={"work_model": "comissionado", "monthly_cost": 0},
        headers=auth_headers,
    )
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_equipe_work_model_invalido_422(client, auth_headers):
    eq = (await client.get("/equipe", headers=auth_headers)).json()
    bid = eq["barbers"][0]["id"]
    r = await client.patch(
        f"/equipe/barbeiros/{bid}",
        json={"work_model": "freelancer"},
        headers=auth_headers,
    )
    assert r.status_code == 422
