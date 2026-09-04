"""Bump A (checkout do agendamento) + Bump C (add-ons em /assinatura) — site
público (D-104 Fase 4, migration 0066).

Cobre: `GET /public/{sub}/oferta` (recomendação sem exigir sessão — o
visitante pode ainda não estar identificado), `POST /public/{sub}/oferta/
evento` (log append-only), `GET /public/{sub}/planos` devolvendo `addons` só
para planos `is_featured`, e o checkout com `addon_ids` somando no
`amount_cents` + o webhook aplicando o snapshot na assinatura recém-criada e
logando `accepted` em `membership_offer_events`.

Reaproveita a infraestrutura de `tests/test_connect_checkout.py` (mock
provider, `connect_on`, `_set_connect_state`, `_post_event`) e de
`tests/test_public_site.py` (`public_seed`, `_create_session`).
"""
from __future__ import annotations

import time
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, set_current_org
from models import MembershipOfferEvent, MembershipPlan, MembershipPlanItem
from tests.conftest import SEED_ORG_ID
from tests.test_connect_checkout import (  # noqa: F401
    ACCOUNT_ID,
    _cleanup_orders,
    _event,
    _order_by_public_id,
    _post_event,
    _set_connect_state,
    connect_on,
)
from tests.test_public_site import BASE, _create_session, public_seed  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _make_variant(client, auth_headers, *, price="19.90", stock="5"):
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Pomada Bump Teste {time.time_ns()}",
            "tracks_stock": True,
            "variants": [{"name": "Único", "price": price}],
        },
    )
    assert resp.status_code == 201, resp.text
    variant_id = resp.json()["variants"][0]["id"]
    if Decimal(stock) > 0:
        resp = await client.post(
            "/estoque/movimentacoes",
            headers=auth_headers,
            json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": stock},
        )
        assert resp.status_code == 201, resp.text
    return variant_id


async def _make_addon(client, auth_headers, *, variant_id, price="19.90"):
    resp = await client.post(
        "/memberships/addons",
        json={"name": "Add-on Bump", "kind": "produto", "variant_id": variant_id, "price": price},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _featured_plan(client, auth_headers, service_id, *, price="150.00"):
    resp = await client.post(
        "/memberships/planos",
        json={
            "name": "Plano Bump Teste",
            "price": price,
            "included_uses": 4,
            "duration_days": 30,
            "service_ids": [service_id],
            "is_featured": True,
            "display_order": 0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _cleanup_catalog(client, auth_headers, *, plan_id=None, addon_id=None):
    if addon_id is not None:
        await client.delete(f"/memberships/addons/{addon_id}", headers=auth_headers)
    if plan_id is not None:
        await client.delete(f"/memberships/planos/{plan_id}", headers=auth_headers)


# ─── Bump A: GET /oferta + POST /oferta/evento ───────────────────────────────


async def test_oferta_publica_sem_sessao_recomenda_plano(
    client, auth_headers, public_seed, connect_on  # noqa: F811
):
    await _set_connect_state()
    plan = await _featured_plan(client, auth_headers, public_seed["service_id"])
    try:
        resp = await client.get(
            f"{BASE}/oferta", params={"servico_id": public_seed["service_id"]}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan"] is not None
        assert body["plan"]["id"] == plan["id"]
        assert body["plan"]["avulso_equivalente"] >= body["plan"]["price"]
    finally:
        await _cleanup_catalog(client, auth_headers, plan_id=plan["id"])


async def test_oferta_publica_sem_connect_devolve_null(
    client, auth_headers, public_seed  # noqa: F811
):
    await _set_connect_state(account_id=None, charges=False)
    plan = await _featured_plan(client, auth_headers, public_seed["service_id"])
    try:
        resp = await client.get(
            f"{BASE}/oferta", params={"servico_id": public_seed["service_id"]}
        )
        assert resp.status_code == 200
        assert resp.json()["plan"] is None
    finally:
        await _cleanup_catalog(client, auth_headers, plan_id=plan["id"])


async def test_oferta_evento_grava_sem_exigir_sessao(
    client, auth_headers, public_seed, connect_on  # noqa: F811
):
    await _set_connect_state()
    plan = await _featured_plan(client, auth_headers, public_seed["service_id"])
    try:
        resp = await client.post(
            f"{BASE}/oferta/evento", json={"outcome": "shown", "plan_id": plan["id"]}
        )
        assert resp.status_code == 204, resp.text

        async with AsyncSessionLocal() as s:
            await set_current_org(s, SEED_ORG_ID)
            rows = (
                await s.execute(
                    select(MembershipOfferEvent).where(
                        MembershipOfferEvent.plan_id == plan["id"],
                        MembershipOfferEvent.surface == "booking",
                        MembershipOfferEvent.outcome == "shown",
                    )
                )
            ).scalars().all()
        assert len(rows) == 1
        assert rows[0].client_session_id is None  # visitante não identificado
    finally:
        await _cleanup_catalog(client, auth_headers, plan_id=plan["id"])


# ─── Bump C: addons na vitrine + checkout ────────────────────────────────────


async def test_planos_publicos_devolvem_addons_so_para_featured(
    client, auth_headers, public_seed, connect_on  # noqa: F811
):
    await _set_connect_state()
    variant_id = await _make_variant(client, auth_headers)
    addon = await _make_addon(client, auth_headers, variant_id=variant_id)
    featured = await _featured_plan(client, auth_headers, public_seed["service_id"])
    not_featured = await client.post(
        "/memberships/planos",
        json={
            "name": "Plano Sem Destaque",
            "price": "80.00",
            "included_uses": 2,
            "duration_days": 30,
            "service_ids": [public_seed["service_id"]],
        },
        headers=auth_headers,
    )
    assert not_featured.status_code == 201, not_featured.text
    not_featured = not_featured.json()
    try:
        resp = await client.get(f"{BASE}/planos")
        assert resp.status_code == 200
        plans = {p["id"]: p for p in resp.json()["plans"]}
        assert any(a["id"] == addon["id"] for a in plans[featured["id"]]["addons"])
        assert plans[not_featured["id"]]["addons"] == []
    finally:
        await _cleanup_catalog(client, auth_headers, addon_id=addon["id"])
        await _cleanup_catalog(client, auth_headers, plan_id=featured["id"])
        await _cleanup_catalog(client, auth_headers, plan_id=not_featured["id"])


async def test_checkout_com_addon_soma_amount_e_grava_snapshot(
    client, auth_headers, public_seed, connect_on  # noqa: F811
):
    await _set_connect_state()
    variant_id = await _make_variant(client, auth_headers, price="19.90", stock="5")
    addon = await _make_addon(client, auth_headers, variant_id=variant_id, price="19.90")
    plan = await _featured_plan(client, auth_headers, public_seed["service_id"], price="150.00")
    try:
        await _create_session(client)
        resp = await client.post(
            f"{BASE}/memberships/checkout",
            json={"plan_id": plan["id"], "addon_ids": [addon["id"]]},
        )
        assert resp.status_code == 201, resp.text
        order = await _order_by_public_id(resp.json()["order_public_id"])
        assert order.amount_cents == 15_000 + 1_990
        assert len(order.addons_snapshot) == 1
        assert order.addons_snapshot[0]["addon_id"] == addon["id"]
    finally:
        await _cleanup_catalog(client, auth_headers, addon_id=addon["id"], plan_id=plan["id"])


async def test_webhook_aplica_addon_e_loga_conversao_accepted(
    client, auth_headers, public_seed, connect_on  # noqa: F811
):
    await _set_connect_state()
    variant_id = await _make_variant(client, auth_headers, price="19.90", stock="5")
    addon = await _make_addon(client, auth_headers, variant_id=variant_id, price="19.90")
    plan = await _featured_plan(client, auth_headers, public_seed["service_id"], price="150.00")
    try:
        await _create_session(client)
        checkout = await client.post(
            f"{BASE}/memberships/checkout",
            json={"plan_id": plan["id"], "addon_ids": [addon["id"]]},
        )
        assert checkout.status_code == 201, checkout.text
        order = await _order_by_public_id(checkout.json()["order_public_id"])

        resp = await _post_event(
            client,
            _event(
                "checkout.session.completed",
                {"id": order.provider_session_id, "payment_status": "paid"},
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paid"

        async with AsyncSessionLocal() as s:
            await set_current_org(s, SEED_ORG_ID)
            atualizado = (
                await s.execute(
                    select(type(order)).where(type(order).id == order.id)
                )
            ).scalar_one()
            membership_id = atualizado.client_membership_id
            assert membership_id is not None

            from models import ClientMembership, ClientMembershipAddon

            membership = (
                await s.execute(
                    select(ClientMembership).where(ClientMembership.id == membership_id)
                )
            ).scalar_one()
            assert membership.price_paid == Decimal("169.90")  # 150.00 + 19.90

            contratados = (
                await s.execute(
                    select(ClientMembershipAddon).where(
                        ClientMembershipAddon.client_membership_id == membership_id
                    )
                )
            ).scalars().all()
            assert len(contratados) == 1
            assert contratados[0].addon_id == addon["id"]

            eventos = (
                await s.execute(
                    select(MembershipOfferEvent).where(
                        MembershipOfferEvent.plan_id == plan["id"],
                        MembershipOfferEvent.surface == "assinatura",
                        MembershipOfferEvent.outcome == "accepted",
                    )
                )
            ).scalars().all()
        assert len(eventos) == 1
    finally:
        await _cleanup_catalog(client, auth_headers, addon_id=addon["id"], plan_id=plan["id"])
