"""Compra online de assinatura (Stripe Connect, Feature 2) — fluxo do dinheiro.

Tudo roda com `MockConnectProvider` (o `registry` devolve o mock sem
`STRIPE_CONNECT_SECRET_KEY`), então nenhuma chave real é necessária.

O invariante que estes testes protegem é um só: **ninguém ganha assinatura sem
pagamento confirmado**. O checkout grava um pedido `pending`; só o webhook —
com dupla idempotência (`event_id` e `provider_session_id`) — cria o
`ClientMembership`.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from app.services.connect.mock_provider import MOCK_SIGNATURE
from app.services.connect.service import estimate_stripe_fee_cents, resolve_fee_cents
from app.services.public_cache import plans_cache_key
from models import (
    AppointmentItem,
    ClientMembership,
    MembershipOrder,
    MembershipPlan,
    MembershipPlanItem,
    Organization,
    Payment,
)
from tests.conftest import SEED_ORG_ID
from tests.test_public_site import BASE, _create_session, public_seed  # noqa: F401

ACCOUNT_ID = f"acct_mock_{SEED_ORG_ID}"
WEBHOOK_URL = "/connect/webhooks/stripe"


# ─── fixtures ────────────────────────────────────────────────────────────────


async def _clear_plans_cache() -> None:
    try:
        from app.db.redis import get_redis

        await get_redis().delete(plans_cache_key(SEED_ORG_ID))
    except Exception:
        pass


@pytest_asyncio.fixture
async def plano(public_seed):  # noqa: F811
    """Plano de catálogo com combo real (o serviço vinculado do seed)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            p = MembershipPlan(
                organization_id=SEED_ORG_ID,
                name=f"Connect Teste {uuid.uuid4().hex[:6]}",
                price=Decimal("150.00"),
                included_uses=4,
                duration_days=30,
            )
            s.add(p)
            await s.flush()
            s.add(
                MembershipPlanItem(
                    organization_id=SEED_ORG_ID,
                    plan_id=p.id,
                    service_id=public_seed["service_id"],
                    position=1,
                )
            )
            plan_id, plan_name, plan_price = p.id, p.name, p.price

    yield {"id": plan_id, "name": plan_name, "price": plan_price}

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            row = (
                await s.execute(select(MembershipPlan).where(MembershipPlan.id == plan_id))
            ).scalar_one_or_none()
            if row is not None:
                row.deleted_at = datetime.now(timezone.utc)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_orders(public_seed):  # noqa: F811
    """Limpa pedidos/assinaturas criados pelos testes.

    `membership_orders` e `client_memberships` não têm GRANT de DELETE ao
    `barber_app` (registro financeiro), então a limpeza vai pela role admin —
    e precisa rodar ANTES do teardown de `public_seed`, que apaga os clientes
    (`client_memberships.client_id` é FK RESTRICT).
    """
    await _clear_plans_cache()
    yield
    await _purge()
    await _clear_plans_cache()


async def _purge() -> None:
    admin_url = os.environ.get("ADMIN_DATABASE_URL")
    if not admin_url:
        return
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(admin_url)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM membership_orders"))
        await conn.execute(
            text(
                "DELETE FROM client_memberships WHERE client_id IN "
                "(SELECT id FROM clients WHERE phone_e164 LIKE '+5563999%')"
            )
        )
        await conn.execute(
            text("DELETE FROM webhook_events WHERE provider = 'stripe_connect'")
        )
    await eng.dispose()


async def _set_connect_state(
    *, account_id: str | None = ACCOUNT_ID, charges: bool = True
) -> None:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            org = (
                await s.execute(select(Organization).where(Organization.id == SEED_ORG_ID))
            ).scalar_one()
            org.stripe_connected_account_id = account_id
            org.stripe_connect_charges_enabled = charges
            org.platform_fee_pct = None


@pytest.fixture
def connect_on(monkeypatch):
    monkeypatch.setattr(settings, "connect_enabled", True)
    monkeypatch.setattr(settings, "stripe_connect_secret_key", "")
    monkeypatch.setattr(settings, "public_site_url", "https://site.test")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_connect_state():
    yield
    await _set_connect_state(account_id=None, charges=False)


def _event(event_type: str, obj: dict, *, account: str | None = ACCOUNT_ID) -> dict:
    ev = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "data": {"object": obj},
    }
    if account is not None:
        ev["account"] = account
    return ev


async def _post_event(client, event: dict, *, sig: str = MOCK_SIGNATURE):
    return await client.post(
        WEBHOOK_URL,
        content=json.dumps(event).encode("utf-8"),
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )


async def _order_by_public_id(public_id: str) -> MembershipOrder:
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        return (
            await s.execute(
                select(MembershipOrder).where(
                    MembershipOrder.public_id == uuid.UUID(public_id)
                )
            )
        ).scalar_one()


async def _memberships_of(client_id: int) -> list[ClientMembership]:
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        return list(
            (
                await s.execute(
                    select(ClientMembership).where(ClientMembership.client_id == client_id)
                )
            )
            .scalars()
            .all()
        )


async def _checkout(client, plano, expect=201):
    resp = await client.post(f"{BASE}/memberships/checkout", json={"plan_id": plano["id"]})
    assert resp.status_code == expect, resp.text
    return resp


# ─── cálculo puro da taxa ────────────────────────────────────────────────────


def _org(pct):
    org = Organization()
    org.platform_fee_pct = pct
    return org


def _zero_stripe_fee(monkeypatch):
    """Zera a estimativa de taxa da Stripe p/ testar a % alvo isoladamente."""
    monkeypatch.setattr(settings, "stripe_domestic_fee_pct", "0")
    monkeypatch.setattr(settings, "stripe_domestic_fee_fixed_cents", 0)


def test_fee_usa_pct_da_org_quando_definido(monkeypatch):
    _zero_stripe_fee(monkeypatch)
    monkeypatch.setattr(settings, "platform_fee_pct_default", "10.0")
    assert resolve_fee_cents(_org(Decimal("5.00")), 10_000) == 500


def test_fee_cai_no_default_quando_org_nao_define(monkeypatch):
    _zero_stripe_fee(monkeypatch)
    monkeypatch.setattr(settings, "platform_fee_pct_default", "10.0")
    assert resolve_fee_cents(_org(None), 10_000) == 1_000


def test_fee_trunca_centavos_para_baixo(monkeypatch):
    _zero_stripe_fee(monkeypatch)
    monkeypatch.setattr(settings, "platform_fee_pct_default", "10.0")
    # 3,33 * 10% = 0,333 → 33 centavos (floor), nunca 34
    assert resolve_fee_cents(_org(None), 333) == 33
    assert resolve_fee_cents(_org(Decimal("7.50")), 1_999) == 149


def test_fee_nunca_negativo_nem_maior_que_o_total(monkeypatch):
    _zero_stripe_fee(monkeypatch)
    monkeypatch.setattr(settings, "platform_fee_pct_default", "10.0")
    assert resolve_fee_cents(_org(Decimal("0")), 10_000) == 0
    assert resolve_fee_cents(_org(Decimal("100.00")), 10_000) == 10_000
    assert resolve_fee_cents(_org(None), 0) == 0
    # default corrompido no .env não vira exceção nem taxa negativa
    monkeypatch.setattr(settings, "platform_fee_pct_default", "abc")
    assert resolve_fee_cents(_org(None), 10_000) == 0


# ─── alvo total (Stripe + comissão) — "minha comissão é o que sobra até X%" ──


def test_estimate_stripe_fee_cents_taxa_padrao():
    # 3,99% + R$0,39 sobre R$120,00 (stripe.com/br/pricing)
    assert estimate_stripe_fee_cents(12_000) == 518
    assert estimate_stripe_fee_cents(0) == 0


def test_fee_alvo_total_desconta_taxa_stripe_estimada(monkeypatch):
    # Alvo 5% de R$120,00 = R$6,00; a taxa da Stripe (R$5,18) sai primeiro,
    # a plataforma fica só com o restante (R$0,82).
    monkeypatch.setattr(settings, "platform_fee_pct_default", "5.0")
    assert resolve_fee_cents(_org(None), 12_000) == 600 - 518


def test_fee_alvo_menor_que_taxa_stripe_vira_zero(monkeypatch):
    # Valor baixo: o fixo de R$0,39 da Stripe sozinho já passa dos 5% alvo —
    # a comissão da plataforma nunca fica negativa, só zera.
    monkeypatch.setattr(settings, "platform_fee_pct_default", "5.0")
    assert resolve_fee_cents(_org(None), 500) == 0


# ─── gate: org sem charges_enabled não vende ─────────────────────────────────


@pytest.mark.asyncio
async def test_planos_vazio_com_feature_desligada(client, public_seed, plano):  # noqa: F811
    await _set_connect_state(charges=True)
    resp = await client.get(f"{BASE}/planos")
    assert resp.status_code == 200
    assert resp.json()["plans"] == []


@pytest.mark.asyncio
async def test_planos_vazio_sem_charges_enabled(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state(charges=False)
    resp = await client.get(f"{BASE}/planos")
    assert resp.json()["plans"] == []


@pytest.mark.asyncio
async def test_planos_lista_quando_habilitado(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state()
    resp = await client.get(f"{BASE}/planos")
    assert resp.status_code == 200
    encontrado = next(p for p in resp.json()["plans"] if p["id"] == plano["id"])
    assert encontrado["price"] == 150.0
    assert encontrado["included_uses"] == 4
    assert encontrado["services"], "plano sem combo não deveria ser vendável"


@pytest.mark.asyncio
async def test_checkout_503_sem_charges_enabled(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state(charges=False)
    await _create_session(client)
    await _checkout(client, plano, expect=503)


@pytest.mark.asyncio
async def test_checkout_401_sem_sessao(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state()
    resp = await client.post(f"{BASE}/memberships/checkout", json={"plan_id": plano["id"]})
    assert resp.status_code == 401


# ─── checkout: pedido pendente, sem pacote fantasma ──────────────────────────


@pytest.mark.asyncio
async def test_checkout_cria_pedido_pendente_e_nenhuma_assinatura(
    client, public_seed, plano, connect_on  # noqa: F811
):
    await _set_connect_state()
    resp_sessao, _ = await _create_session(client)
    resp = await _checkout(client, plano)
    body = resp.json()
    assert body["checkout_url"].startswith("https://checkout.mock.local/")

    order = await _order_by_public_id(body["order_public_id"])
    assert order.status == "pending"
    assert order.client_membership_id is None
    assert order.provider == "stripe_connect"
    assert order.provider_session_id.startswith("cs_mock_")
    assert order.connected_account_id == ACCOUNT_ID
    # snapshots do plano no momento do pedido
    assert order.plan_name == plano["name"]
    assert order.price == Decimal("150.00")
    assert order.amount_cents == 15_000
    assert order.application_fee_cents == resolve_fee_cents(
        _org(None), 15_000
    )
    assert order.expires_at is not None

    # NINGUÉM ganha assinatura por iniciar o checkout
    assert await _memberships_of(order.client_id) == []
    assert resp_sessao.status_code == 201


@pytest.mark.asyncio
async def test_checkout_409_com_assinatura_ativa(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state()
    await _create_session(client)
    resp = await _checkout(client, plano)
    order = await _order_by_public_id(resp.json()["order_public_id"])

    await _post_event(
        client,
        _event(
            "checkout.session.completed",
            {"id": order.provider_session_id, "payment_status": "paid"},
        ),
    )
    # com a assinatura vigente, comprar de novo pelo site é 409 (renovação
    # pelo site fica fora da v1)
    await _checkout(client, plano, expect=409)


@pytest.mark.asyncio
async def test_checkout_plano_inexistente_404(client, public_seed, connect_on):  # noqa: F811
    await _set_connect_state()
    await _create_session(client)
    resp = await client.post(f"{BASE}/memberships/checkout", json={"plan_id": 999_999_999})
    assert resp.status_code == 404


# ─── confirmação pelo webhook ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_confirma_e_cria_exatamente_uma_assinatura(
    client, public_seed, plano, connect_on  # noqa: F811
):
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])

    resp = await _post_event(
        client,
        _event(
            "checkout.session.completed",
            {
                "id": order.provider_session_id,
                "payment_status": "paid",
                "payment_intent": "pi_mock_1",
                "payment_method_types": ["card"],
            },
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"

    memberships = await _memberships_of(order.client_id)
    assert len(memberships) == 1
    m = memberships[0]
    assert m.plan_id == plano["id"]
    assert m.price_paid == Decimal("150.00")
    assert m.included_uses == 4
    assert m.used_uses == 0
    assert m.sold_by_user_id is None  # compra do próprio cliente, sem operador

    atualizado = await _order_by_public_id(str(order.public_id))
    assert atualizado.status == "paid"
    assert atualizado.paid_at is not None
    assert atualizado.client_membership_id == m.id
    assert atualizado.provider_payment_intent_id == "pi_mock_1"
    assert atualizado.payment_method_detail == "card"

    # o cliente enxerga a assinatura na rota de polling da página de sucesso
    minha = await client.get(f"{BASE}/me/assinatura")
    assert minha.status_code == 200
    assert minha.json()["public_id"] == str(m.public_id)


@pytest.mark.asyncio
async def test_webhook_idempotente_por_event_id(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])
    evento = _event(
        "checkout.session.completed",
        {"id": order.provider_session_id, "payment_status": "paid"},
    )

    primeira = await _post_event(client, evento)
    segunda = await _post_event(client, evento)  # replay do gateway
    assert primeira.json()["status"] == "paid"
    assert segunda.json()["status"] == "duplicate"
    assert len(await _memberships_of(order.client_id)) == 1


@pytest.mark.asyncio
async def test_webhook_idempotente_por_session_id(client, public_seed, plano, connect_on):  # noqa: F811
    """Evento NOVO (id diferente) sobre a MESMA sessão não duplica a assinatura."""
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])
    obj = {"id": order.provider_session_id, "payment_status": "paid"}

    await _post_event(client, _event("checkout.session.completed", obj))
    segunda = await _post_event(
        client, _event("checkout.session.async_payment_succeeded", obj)
    )
    assert segunda.json()["status"] == "already_processed"
    assert len(await _memberships_of(order.client_id)) == 1


@pytest.mark.asyncio
async def test_webhook_completed_sem_pagamento_nao_confirma(
    client, public_seed, plano, connect_on  # noqa: F811
):
    """`payment_status != paid` (pix/boleto pendente) espera o async_succeeded."""
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])

    resp = await _post_event(
        client,
        _event(
            "checkout.session.completed",
            {"id": order.provider_session_id, "payment_status": "unpaid"},
        ),
    )
    assert resp.json()["status"] == "ignored"
    assert await _memberships_of(order.client_id) == []


@pytest.mark.asyncio
async def test_webhook_failed_e_expired_marcam_o_pedido(
    client, public_seed, plano, connect_on  # noqa: F811
):
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])

    resp = await _post_event(
        client,
        _event(
            "checkout.session.async_payment_failed", {"id": order.provider_session_id}
        ),
    )
    assert resp.json()["status"] == "failed"
    assert (await _order_by_public_id(str(order.public_id))).status == "failed"
    assert await _memberships_of(order.client_id) == []


@pytest.mark.asyncio
async def test_webhook_assinatura_invalida_400_e_nada_gravado(client, public_seed):  # noqa: F811
    evento = _event("checkout.session.completed", {"id": "cs_qualquer"})
    resp = await _post_event(client, evento, sig="assinatura-errada")
    assert resp.status_code == 400

    async with AsyncSessionLocal() as s:
        total = (
            await s.execute(
                text(
                    "SELECT count(*) FROM webhook_events "
                    "WHERE provider = 'stripe_connect' AND event_id = :e"
                ),
                {"e": evento["id"]},
            )
        ).scalar_one()
    assert total == 0, "payload não autenticado não pode entrar no log"


@pytest.mark.asyncio
async def test_webhook_sem_account_e_de_conta_desconhecida(client, public_seed):  # noqa: F811
    sem_conta = await _post_event(
        client, _event("checkout.session.completed", {"id": "cs_x"}, account=None)
    )
    assert sem_conta.status_code == 200
    assert sem_conta.json()["status"] == "skipped"

    outra = await _post_event(
        client,
        _event("checkout.session.completed", {"id": "cs_y"}, account="acct_de_outra_org"),
    )
    assert outra.status_code == 200
    assert outra.json()["status"] == "orphan"


@pytest.mark.asyncio
async def test_webhook_de_outra_conta_nao_confirma_pedido_desta_org(
    client, public_seed, plano, connect_on  # noqa: F811
):
    """Um evento de connected account alheia não pode confirmar o pedido daqui."""
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])

    resp = await _post_event(
        client,
        _event(
            "checkout.session.completed",
            {"id": order.provider_session_id, "payment_status": "paid"},
            account="acct_mock_999999",
        ),
    )
    assert resp.json()["status"] == "orphan"
    assert (await _order_by_public_id(str(order.public_id))).status == "pending"
    assert await _memberships_of(order.client_id) == []


@pytest.mark.asyncio
async def test_account_updated_atualiza_flags(client, public_seed, connect_on, monkeypatch):  # noqa: F811
    chamadas: list[tuple[int, list[str]]] = []

    async def _spy(org_id: int, tags: list[str]) -> None:
        chamadas.append((org_id, tags))

    monkeypatch.setattr("app.api.connect.invalidate_public_tags", _spy)
    await _set_connect_state(charges=False)

    resp = await _post_event(
        client,
        _event(
            "account.updated",
            {
                "id": ACCOUNT_ID,
                "charges_enabled": True,
                "payouts_enabled": True,
                "details_submitted": True,
            },
        ),
    )
    assert resp.json()["status"] == "account_updated"

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        org = (
            await s.execute(select(Organization).where(Organization.id == SEED_ORG_ID))
        ).scalar_one()
        assert org.stripe_connect_charges_enabled is True
        assert org.stripe_connect_synced_at is not None
    assert chamadas == [(SEED_ORG_ID, ["public-info", "public-plans"])]


@pytest.mark.asyncio
async def test_evento_irrelevante_e_ignorado(client, public_seed):  # noqa: F811
    await _set_connect_state()
    resp = await _post_event(client, _event("charge.refunded", {"id": "ch_1"}))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


# ─── não-regressão financeira ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compra_online_nao_cria_payment_nem_appointment_item(
    client, public_seed, plano, connect_on  # noqa: F811
):
    async def _contagens() -> tuple[int, int]:
        async with AsyncSessionLocal() as s:
            await set_current_org(s, SEED_ORG_ID)
            pagamentos = (
                await s.execute(select(func.count()).select_from(Payment))
            ).scalar_one()
            itens = (
                await s.execute(select(func.count()).select_from(AppointmentItem))
            ).scalar_one()
            return pagamentos, itens

    antes = await _contagens()

    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])
    await _post_event(
        client,
        _event(
            "checkout.session.completed",
            {"id": order.provider_session_id, "payment_status": "paid"},
        ),
    )

    assert len(await _memberships_of(order.client_id)) == 1
    assert await _contagens() == antes, (
        "venda online não pode tocar payments/appointment_items — a receita do "
        "pacote é reconhecida no USO, não na venda"
    )


# ─── RLS ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rls_isola_pedidos_entre_orgs(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID + 999_000)
        rows = (
            await s.execute(select(MembershipOrder).where(MembershipOrder.id == order.id))
        ).scalars().all()
    assert rows == []


# ─── cron de expiração ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cron_expira_pedido_vencido(client, public_seed, plano, connect_on):  # noqa: F811
    await _set_connect_state()
    await _create_session(client)
    order = await _order_by_public_id((await _checkout(client, plano)).json()["order_public_id"])

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            row = (
                await s.execute(
                    select(MembershipOrder).where(MembershipOrder.id == order.id)
                )
            ).scalar_one()
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    if not settings.bot_api_key:
        pytest.skip("BOT_API_KEY não configurado no ambiente de teste.")
    negado = await client.post(
        "/internal/connect/expire-orders", headers={"X-Bot-Token": "errado"}
    )
    assert negado.status_code == 401

    resp = await client.post(
        "/internal/connect/expire-orders",
        headers={"X-Bot-Token": settings.bot_api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["expired"] >= 1
    assert (await _order_by_public_id(str(order.public_id))).status == "expired"
