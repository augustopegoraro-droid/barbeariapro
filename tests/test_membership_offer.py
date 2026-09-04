"""Order bumps do clube de assinatura (migration 0065).

Cobre: campos de vitrine/segmentação no catálogo (audience/headline/badge/
is_featured/display_order/perks), recomendação contextual de plano
(`GET /memberships/oferta`), log append-only de eventos de oferta
(`POST /memberships/oferta/evento`) e o agregado de conversão
(`GET /memberships/conversao`), incluindo RBAC.

Autocontido: cria o próprio cliente/plano, exercita e limpa ao final.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio


def _uniq_phone() -> str:
    return "+55119" + str(time.time_ns())[-8:]


async def _two_services(client, auth_headers):
    resp = await client.get("/servicos", headers=auth_headers)
    if resp.status_code != 200:
        pytest.skip("Serviços indisponíveis no seed.")
    active = [s for s in resp.json() if s["is_active"]]
    corte = next((s for s in active if s.get("category") == "cabelo"), None)
    barba = next((s for s in active if s.get("category") == "barba"), None)
    if not corte or not barba:
        pytest.skip("Seed precisa de 1 serviço 'cabelo' e 1 'barba' ativos.")
    return corte, barba


async def _make_client(client, auth_headers, name="Cliente Oferta"):
    resp = await client.post(
        "/clientes",
        json={"name": name, "phone": _uniq_phone()},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_featured_plan(client, auth_headers, service_ids, **over):
    body = {
        "name": "Corte & Barba Clube",
        "price": "139.90",
        "included_uses": 4,
        "duration_days": 30,
        "service_ids": service_ids,
        "audience": "masculino",
        "category": "Corte & Barba",
        "headline": "2 cortes + 2 barbas todo mês",
        "perks": ["10% em produtos", "sem fila"],
        "badge": "Mais vendido",
        "display_order": 1,
        "is_featured": True,
    }
    body.update(over)
    resp = await client.post("/memberships/planos", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _cleanup(client, auth_headers, *, plan_id=None, client_id=None, membership_ids=()):
    for mid in membership_ids:
        await client.post(f"/memberships/{mid}/cancelar", headers=auth_headers)
    if plan_id is not None:
        await client.delete(f"/memberships/planos/{plan_id}", headers=auth_headers)
    if client_id is not None:
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)


# ─── catálogo: campos novos ─────────────────────────────────────────────────

async def test_catalogo_grava_e_devolve_campos_de_vitrine(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _create_featured_plan(client, auth_headers, [corte["id"], barba["id"]])
    try:
        assert plan["audience"] == "masculino"
        assert plan["headline"] == "2 cortes + 2 barbas todo mês"
        assert plan["badge"] == "Mais vendido"
        assert plan["perks"] == ["10% em produtos", "sem fila"]
        assert plan["display_order"] == 1
        assert plan["is_featured"] is True

        # PATCH parcial mantém o resto
        patched = await client.patch(
            f"/memberships/planos/{plan['id']}",
            json={"badge": "Melhor custo", "is_featured": False},
            headers=auth_headers,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["badge"] == "Melhor custo"
        assert patched.json()["is_featured"] is False
        assert patched.json()["audience"] == "masculino"  # inalterado

        listed = await client.get("/memberships/planos", headers=auth_headers)
        row = next(p for p in listed.json() if p["id"] == plan["id"])
        assert row["headline"] == "2 cortes + 2 barbas todo mês"
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"])


async def test_plano_default_e_unissex_e_nao_featured(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    resp = await client.post(
        "/memberships/planos",
        json={
            "name": "Plano Simples",
            "price": "89.90",
            "included_uses": 2,
            "duration_days": 30,
            "service_ids": [corte["id"], barba["id"]],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    plan = resp.json()
    try:
        assert plan["audience"] == "unissex"
        assert plan["is_featured"] is False
        assert plan["perks"] == []
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"])


# ─── recomendação contextual (GET /memberships/oferta) ──────────────────────

async def test_oferta_recomenda_plano_featured_com_economia(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _create_featured_plan(client, auth_headers, [corte["id"], barba["id"]])
    client_id = await _make_client(client, auth_headers)
    try:
        resp = await client.get(
            "/memberships/oferta",
            params={"client_id": client_id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["plan"] is not None
        assert data["plan"]["id"] == plan["id"]
        expected_avulso = round(float(corte["price"]) + float(barba["price"]), 2)
        assert data["plan"]["avulso_equivalente"] == pytest.approx(expected_avulso)
        assert data["recent_completed"] == 0
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"], client_id=client_id)


async def test_oferta_nula_quando_cliente_ja_assina(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _create_featured_plan(client, auth_headers, [corte["id"], barba["id"]])
    client_id = await _make_client(client, auth_headers)
    sell = await client.post(
        "/memberships",
        json={"client_id": client_id, "plan_id": plan["id"]},
        headers=auth_headers,
    )
    assert sell.status_code == 201, sell.text
    membership_id = sell.json()["id"]
    try:
        resp = await client.get(
            "/memberships/oferta",
            params={"client_id": client_id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["plan"] is None
    finally:
        await _cleanup(
            client, auth_headers,
            plan_id=plan["id"], client_id=client_id, membership_ids=[membership_id],
        )


async def test_oferta_nula_quando_nenhum_plano_em_destaque(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    # Isolamento: este teste afirma "nenhum plano em destaque" globalmente — pula
    # se o ambiente já tem algum (resíduo de execução anterior interrompida).
    existing = await client.get("/memberships/planos", headers=auth_headers)
    if any(p.get("is_featured") for p in existing.json()):
        pytest.skip("Ambiente já tem plano em destaque; teste não isolável.")
    # plano NÃO featured
    plan = await _create_featured_plan(
        client, auth_headers, [corte["id"], barba["id"]], is_featured=False
    )
    client_id = await _make_client(client, auth_headers)
    try:
        resp = await client.get(
            "/memberships/oferta",
            params={"client_id": client_id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["plan"] is None
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"], client_id=client_id)


# ─── log de eventos + conversão ─────────────────────────────────────────────

async def test_evento_de_oferta_e_conversao(client, auth_headers):
    # `membership_offer_events` é append-only (nunca limpa): mede o DELTA da
    # janela, não valores absolutos, para não depender de execuções anteriores.
    corte, barba = await _two_services(client, auth_headers)
    plan = await _create_featured_plan(client, auth_headers, [corte["id"], barba["id"]])
    client_id = await _make_client(client, auth_headers)
    inicio = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    def _bucket(payload):
        return payload["by_surface"].get(
            "conclusao", {"shown": 0, "accepted": 0, "dismissed": 0}
        )

    try:
        fim = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        base = await client.get(
            "/memberships/conversao",
            params={"inicio": inicio, "fim": fim},
            headers=auth_headers,
        )
        assert base.status_code == 200, base.text
        b0 = _bucket(base.json())

        for outcome in ("shown", "shown", "accepted", "dismissed"):
            r = await client.post(
                "/memberships/oferta/evento",
                json={
                    "surface": "conclusao",
                    "outcome": outcome,
                    "plan_id": plan["id"],
                    "client_id": client_id,
                    "shown_amount": "70.00",
                },
                headers=auth_headers,
            )
            assert r.status_code == 204, r.text

        fim = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        conv = await client.get(
            "/memberships/conversao",
            params={"inicio": inicio, "fim": fim},
            headers=auth_headers,
        )
        assert conv.status_code == 200, conv.text
        b1 = _bucket(conv.json())
        assert b1["shown"] - b0["shown"] == 2
        assert b1["accepted"] - b0["accepted"] == 1
        assert b1["dismissed"] - b0["dismissed"] == 1
        assert 0.0 <= b1["conversion_rate"] <= 1.0
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"], client_id=client_id)


# ─── RBAC ──────────────────────────────────────────────────────────────────

async def test_oferta_exige_permissao_de_venda(client, auth_headers, barber_headers):
    if barber_headers is None:
        pytest.skip("Barbeiro semeado indisponível.")
    corte, barba = await _two_services(client, auth_headers)
    plan = await _create_featured_plan(client, auth_headers, [corte["id"], barba["id"]])
    client_id = await _make_client(client, auth_headers)
    try:
        resp = await client.get(
            "/memberships/oferta",
            params={"client_id": client_id},
            headers=barber_headers,
        )
        assert resp.status_code == 403
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"], client_id=client_id)


async def test_conversao_restrita_a_gestor(client, auth_headers, reception_headers):
    if reception_headers is None:
        pytest.skip("Recepção semeada indisponível.")
    inicio = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    fim = datetime.now(timezone.utc).isoformat()
    resp = await client.get(
        "/memberships/conversao",
        params={"inicio": inicio, "fim": fim},
        headers=reception_headers,
    )
    assert resp.status_code == 403
