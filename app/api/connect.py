# file: app/api/connect.py
"""Stripe Connect — onboarding da barbearia, webhook e cron.

Três superfícies com autenticações diferentes (molde `app/api/billing.py`):

- `/connect/*` (tenant): JWT + permissão nomeada (`billing.view`/`billing.manage`,
  já no catálogo desde o D-67; `manage` é owner-only — semântica certa, mexe em
  conta bancária). Toda escrita é auditada.
- `/connect/webhooks/stripe`: SEM sessão/JWT — a autenticidade é a ASSINATURA
  criptográfica verificada pelo provider. Endpoint e segredo **separados** do
  `/billing/webhooks/{provider}` do D-61 (outra conta Stripe, outro domínio de
  dinheiro), mas reaproveitando a tabela `webhook_events` com
  `provider="stripe_connect"` — o `UNIQUE (provider, event_id)` isola os dois.
- `/internal/connect/expire-orders`: cron (n8n) com `X-Bot-Token` em tempo
  constante.

Invariante do dinheiro: **nenhum `ClientMembership` nasce sem confirmação de
pagamento**. O checkout (em `app/api/public.py`) só grava o pedido `pending`;
é aqui, no webhook, que a assinatura é criada — sob `SELECT ... FOR UPDATE` e
com dupla idempotência (`event_id` na `webhook_events`, `client_membership_id`
já preenchido na própria order).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    status as http_status,
)
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.core.config import settings
from app.core.security import secrets_match
from app.db.session import AsyncSessionLocal, set_current_org
from app.deps import get_current_user, get_tenant_db
from app.services import webhook_log
from app.services.audit import record_event
from app.services.connect import service as connect_svc
from app.services.connect.provider import ConnectProviderError
from app.services.connect.registry import get_connect_provider
from app.services.membership import apply_membership_addons, create_membership, log_offer_event
from app.services.public_cache import PLANS_TAG, REVALIDATE_TAG, invalidate_public_tags
from app.services.tenant import org_id_by_connected_account
from models import (
    MembershipOfferOutcome,
    MembershipOfferSurface,
    MembershipOrder,
    Organization,
    User,
)

router = APIRouter(prefix="/connect", tags=["connect"])
internal_router = APIRouter(prefix="/internal/connect", tags=["connect-internal"])

logger = logging.getLogger(__name__)

VIEW = "billing.view"
MANAGE = "billing.manage"

PROVIDER = "stripe_connect"
# Tags invalidadas quando a capacidade de cobrar muda: a vitrine (`/info`) e a
# lista de planos (`/planos`) dependem do `charges_enabled`.
CAPABILITY_TAGS = [REVALIDATE_TAG, PLANS_TAG]


# ─── schemas ────────────────────────────────────────────────────────────────


class ConnectStatusOut(BaseModel):
    enabled: bool
    has_account: bool
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    platform_fee_pct: Optional[float] = None


class AccountOut(BaseModel):
    account_id: str


class AccountSessionOut(BaseModel):
    client_secret: str
    publishable_key: str


# ─── helpers ────────────────────────────────────────────────────────────────


async def _load_org(db: AsyncSession, org_id: int) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Organização não encontrada.")
    return org


def _status_out(org: Organization) -> ConnectStatusOut:
    return ConnectStatusOut(
        enabled=settings.connect_enabled,
        has_account=bool(org.stripe_connected_account_id),
        charges_enabled=bool(org.stripe_connect_charges_enabled),
        payouts_enabled=bool(org.stripe_connect_payouts_enabled),
        details_submitted=bool(org.stripe_connect_details_submitted),
        platform_fee_pct=(
            float(org.platform_fee_pct) if org.platform_fee_pct is not None else None
        ),
    )


def _require_enabled() -> None:
    """503 explícito com o kill switch desligado — nunca um 500 obscuro."""
    if not settings.connect_enabled:
        raise HTTPException(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "Recebimentos online ainda não estão habilitados nesta instalação.",
        )


# ─── rotas de tenant ────────────────────────────────────────────────────────


@router.get("/status", response_model=ConnectStatusOut)
async def status_connect(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ConnectStatusOut:
    """Estado local (não bate na Stripe). Sincronizar é `POST /connect/sync`."""
    await require_permission(db, current_user, VIEW)
    return _status_out(await _load_org(db, current_user.organization_id))


@router.post("/account", response_model=AccountOut)
async def criar_conta(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AccountOut:
    """Cria (ou devolve) a connected account da barbearia — idempotente."""
    await require_permission(db, current_user, MANAGE)
    _require_enabled()
    org = await _load_org(db, current_user.organization_id)

    ja_tinha = bool(org.stripe_connected_account_id)
    try:
        account_id = await connect_svc.ensure_account(db, org)
    except ConnectProviderError as exc:
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    if not ja_tinha:
        record_event(
            organization_id=org.id,
            actor_user_id=current_user.id,
            action="connect.account.create",
            resource_type="organization",
            resource_id=org.id,
            after={"account_id": account_id},
        )
    return AccountOut(account_id=account_id)


@router.post("/account-session", response_model=AccountSessionOut)
async def criar_sessao_de_conta(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AccountSessionOut:
    """Segredo efêmero p/ o onboarding embutido no painel."""
    await require_permission(db, current_user, MANAGE)
    _require_enabled()
    org = await _load_org(db, current_user.organization_id)
    if not org.stripe_connected_account_id:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Crie a conta de recebimentos antes (POST /connect/account).",
        )
    try:
        data = await connect_svc.account_session(db, org)
    except ConnectProviderError as exc:
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    record_event(
        organization_id=org.id,
        actor_user_id=current_user.id,
        action="connect.session.create",
        resource_type="organization",
        resource_id=org.id,
    )
    return AccountSessionOut(
        client_secret=data["client_secret"],
        publishable_key=settings.stripe_connect_publishable_key,
    )


@router.post("/sync", response_model=ConnectStatusOut)
async def sincronizar(
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ConnectStatusOut:
    """Relê os flags na Stripe. Mudança em `charges_enabled` invalida a vitrine."""
    await require_permission(db, current_user, MANAGE)
    _require_enabled()
    org = await _load_org(db, current_user.organization_id)
    if not org.stripe_connected_account_id:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Crie a conta de recebimentos antes (POST /connect/account).",
        )
    try:
        mudou = await connect_svc.sync_account_status(db, org)
    except ConnectProviderError as exc:
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    await db.flush()

    record_event(
        organization_id=org.id,
        actor_user_id=current_user.id,
        action="connect.sync",
        resource_type="organization",
        resource_id=org.id,
        after={"charges_enabled": org.stripe_connect_charges_enabled},
    )
    if mudou:
        background_tasks.add_task(invalidate_public_tags, org.id, CAPABILITY_TAGS)
    return _status_out(org)


# ─── webhook (sem auth de sessão — assinatura é a autenticidade) ────────────


@router.post("/webhooks/stripe", status_code=http_status.HTTP_200_OK)
async def receber_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")

    provider = get_connect_provider()
    try:
        event = provider.parse_webhook(body, sig)
    except ConnectProviderError as exc:
        # 400 e NADA gravado: um payload não autenticado não entra no log.
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "Assinatura inválida.") from exc

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    if not event_id or not event_type:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "Evento malformado.")
    try:
        raw_payload = json.loads(body.decode("utf-8"))
    except Exception:  # payload já autenticado; fallback defensivo
        raw_payload = {}

    webhook_id = await webhook_log.record_raw_event(
        provider=PROVIDER, event_id=event_id, event_type=event_type, payload=raw_payload
    )
    if webhook_id is None:
        # Replay do gateway: já processado numa entrega anterior.
        return {"status": "duplicate"}

    obj: dict[str, Any] = (event.get("data") or {}).get("object") or {}
    # Em eventos de connected account o tenant vem no campo `account`,
    # TOP-LEVEL do Event (não dentro de `data.object`).
    account_id = event.get("account") or obj.get("account")
    if not account_id:
        await webhook_log.mark_event(webhook_id, "skipped")
        return {"status": "skipped"}

    async with AsyncSessionLocal() as session:
        org_id = await org_id_by_connected_account(session, str(account_id))
    if org_id is None:
        # Conta que não é de nenhuma org daqui (ex.: ambiente compartilhado).
        logger.warning("connect: evento %s de conta desconhecida", event_id)
        await webhook_log.mark_event(webhook_id, "skipped", error="conta sem org")
        return {"status": "orphan"}

    try:
        resultado = await _process_event(org_id, event_type, obj, background_tasks)
    except Exception as exc:  # noqa: BLE001 — evento ruim não derruba o endpoint
        logger.exception("connect: falha ao processar %s", event_id)
        await webhook_log.mark_event(
            webhook_id, "failed", org_id=org_id, error=str(exc)[:500]
        )
        return {"status": "failed"}

    await webhook_log.mark_event(
        webhook_id,
        "processed" if resultado not in {"ignored", "order_not_found"} else "skipped",
        org_id=org_id,
    )
    return {"status": resultado}


async def _process_event(
    org_id: int,
    event_type: str,
    obj: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> str:
    if event_type == "account.updated":
        return await _apply_account_updated(org_id, obj, background_tasks)

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        if event_type == "checkout.session.completed" and obj.get("payment_status") != "paid":
            # Sessão concluída sem pagamento confirmado (boleto/pix pendente):
            # quem confirma é o `async_payment_succeeded`.
            return "ignored"
        return await _confirm_order(org_id, obj)

    if event_type == "checkout.session.async_payment_failed":
        return await _set_order_status(org_id, obj, "failed")
    if event_type == "checkout.session.expired":
        return await _set_order_status(org_id, obj, "expired")

    # `charge.refunded`/`charge.dispute.created` etc.: ficam registrados na
    # `webhook_events` mas NÃO cancelam a assinatura automaticamente (decisão
    # consciente da v1 — cancelar direito de uso exige decisão humana).
    return "ignored"


async def _apply_account_updated(
    org_id: int, obj: dict[str, Any], background_tasks: BackgroundTasks
) -> str:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            org = (
                await session.execute(
                    select(Organization).where(Organization.id == org_id)
                )
            ).scalar_one_or_none()
            if org is None:
                return "ignored"
            mudou = connect_svc.apply_account_flags(org, obj)
    if mudou:
        background_tasks.add_task(invalidate_public_tags, org_id, CAPABILITY_TAGS)
    return "account_updated"


async def _load_order_for_update(
    session: AsyncSession, session_id: str
) -> Optional[MembershipOrder]:
    return (
        await session.execute(
            select(MembershipOrder)
            .where(MembershipOrder.provider == PROVIDER)
            .where(MembershipOrder.provider_session_id == session_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _confirm_order(org_id: int, obj: dict[str, Any]) -> str:
    """Cria a assinatura e marca o pedido como pago — na MESMA transação."""
    session_id = str(obj.get("id") or "")
    if not session_id:
        return "ignored"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            order = await _load_order_for_update(session, session_id)
            if order is None:
                # Nada é criado a partir de um evento sem pedido local: o
                # `client_id`/`plan_id` viriam de onde?
                logger.warning("connect: sessão %s sem pedido local", session_id)
                return "order_not_found"
            if order.client_membership_id is not None:
                return "already_processed"

            membership = await create_membership(
                session,
                organization_id=org_id,
                client_id=order.client_id,
                sold_by_user_id=None,  # compra do próprio cliente, sem operador
                plan_id=order.plan_id,
            )
            await session.flush()

            # Add-ons escolhidos no checkout (Bump C, D-104 Fase 4) — snapshot
            # já travado em `order.addons_snapshot`, não re-resolve
            # `MembershipAddon` (pode ter sido arquivado nesse meio-tempo).
            if order.addons_snapshot:
                await apply_membership_addons(
                    session, membership, order.addons_snapshot
                )
            await log_offer_event(
                session,
                organization_id=org_id,
                surface=MembershipOfferSurface.assinatura,
                outcome=MembershipOfferOutcome.accepted,
                plan_id=order.plan_id,
                client_id=order.client_id,
                client_session_id=order.client_session_id,
            )

            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            order.client_membership_id = membership.id
            order.provider_payment_intent_id = _intent_id(obj)
            order.provider_charge_id = _charge_id(obj)
            order.payment_method_detail = _payment_method_detail(obj)
            # Ler DEPOIS do commit levantaria DetachedInstanceError
            # (expire_on_commit); capturar aqui é obrigatório.
            order_id = order.id
            client_id = order.client_id
            membership_id = membership.id

    record_event(
        organization_id=org_id,
        actor_kind="client",
        action="memberships.online_purchase",
        resource_type="membership_order",
        resource_id=order_id,
        after={"client_id": client_id, "membership_id": membership_id},
    )
    return "paid"


def _intent_id(obj: dict[str, Any]) -> Optional[str]:
    """A Stripe manda `payment_intent` como id (string) ou objeto expandido."""
    pi = obj.get("payment_intent")
    if isinstance(pi, dict):
        return pi.get("id")
    return str(pi) if pi else None


def _charge_id(obj: dict[str, Any]) -> Optional[str]:
    pi = obj.get("payment_intent")
    if isinstance(pi, dict) and pi.get("latest_charge"):
        latest = pi["latest_charge"]
        return latest.get("id") if isinstance(latest, dict) else str(latest)
    latest = obj.get("latest_charge")
    return str(latest) if latest else None


def _payment_method_detail(obj: dict[str, Any]) -> Optional[str]:
    tipos = obj.get("payment_method_types")
    if not tipos:
        return None
    return ",".join(str(t) for t in tipos)[:100]


async def _set_order_status(org_id: int, obj: dict[str, Any], novo: str) -> str:
    session_id = str(obj.get("id") or "")
    if not session_id:
        return "ignored"
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            order = await _load_order_for_update(session, session_id)
            if order is None:
                return "order_not_found"
            # Pedido já pago nunca regride (evento fora de ordem).
            if order.status == "paid" or order.client_membership_id is not None:
                return "already_processed"
            order.status = novo
    return novo


# ─── cron interno (n8n) ─────────────────────────────────────────────────────


@internal_router.post("/expire-orders")
async def expirar_pedidos(
    x_bot_token: Annotated[Optional[str], Header(alias="X-Bot-Token")] = None,
) -> dict:
    """Rede de segurança: pedidos abandonados viram `expired` mesmo se o
    `checkout.session.expired` da Stripe se perder. Só mexe em `pending` —
    nunca reabre nem cancela nada já pago."""
    if not settings.bot_api_key or not secrets_match(
        x_bot_token or "", settings.bot_api_key
    ):
        raise HTTPException(http_status.HTTP_401_UNAUTHORIZED, "Token inválido.")

    now = datetime.now(timezone.utc)
    # `membership_orders` tem RLS: uma varredura sem tenant não veria linha
    # alguma. Roda org a org, listando-as pelo SECURITY DEFINER de plataforma
    # (mesmo molde de `billing.service.run_lifecycle`).
    async with AsyncSessionLocal() as plain:
        org_ids = [
            int(r)
            for r in (
                await plain.execute(text("SELECT app_platform_active_org_ids()"))
            ).scalars().all()
        ]

    total = 0
    for org_id in org_ids:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await set_current_org(session, org_id)
                res = await session.execute(
                    update(MembershipOrder)
                    .where(MembershipOrder.status == "pending")
                    .where(MembershipOrder.expires_at.is_not(None))
                    .where(MembershipOrder.expires_at < now)
                    .values(status="expired")
                )
                total += res.rowcount or 0
    return {"expired": total}
