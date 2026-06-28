"""Fidelidade do cliente.

Fase 1 (legado, mantido p/ compat até o frontend migrar): snapshot derivado de
visitas/gasto com os eixos `nivel`/`categoria` e benefícios fixos.

Fase 2 (points-driven): PONTOS são a moeda única e auditável. O ledger
(`loyalty_point_ledger`) é append-only e a fonte de verdade do saldo; o tier do
cliente deriva do saldo via `loyalty_tiers` (configurável por org). `recalculate`
credita pontos por atendimento concluído (idempotente) e mantém os campos legados
populados durante a transição.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Appointment, AppointmentItem, AppointmentStatus
from models.enums import (
    LoyaltyCategoria,
    LoyaltyLedgerType,
    LoyaltyNivel,
    LoyaltyStatus,
    LoyaltyVoucherStatus,
)
from models.loyalty import (
    ClientLoyalty,
    LoyaltyPointEntry,
    LoyaltyRule,
    LoyaltyTier,
    LoyaltyVoucher,
)

# ---------------------------------------------------------------------------
# Defaults de configuração (lazy-seed por org)
# ---------------------------------------------------------------------------

# Ladder único default. (name, min_points, discount_pct, perks)
DEFAULT_TIERS: list[tuple[str, int, str, list[str]]] = [
    ("Bronze", 0, "0", ["acúmulo de pontos"]),
    ("Prata", 150, "0.05", ["5% de desconto"]),
    ("Ouro", 500, "0.10", ["10% de desconto", "prioridade de encaixe"]),
    ("Diamante", 1000, "0.15", ["15% de desconto", "brinde mensal"]),
    ("Black", 2000, "0.20", ["20% de desconto", "atendimento exclusivo"]),
]
DEFAULT_POINTS_PER_BRL = Decimal("1")
DEFAULT_POINTS_PER_VISIT = 10
DEFAULT_REDEMPTION_BRL_PER_POINT = Decimal("1")


# ===========================================================================
# Funções de cálculo puras — LEGADO (mantidas até o frontend migrar p/ tier)
# ===========================================================================

_NIVEL_BENEFIT: dict[LoyaltyNivel, str] = {
    LoyaltyNivel.vip: "10% desconto em produtos",
    LoyaltyNivel.fiel: "Café/bebida grátis",
    LoyaltyNivel.ativo: "Sem benefício",
    LoyaltyNivel.novo: "Sem benefício",
}

_CATEGORIA_BENEFIT: dict[LoyaltyCategoria, str] = {
    LoyaltyCategoria.diamante: "1 corte gratuito",
    LoyaltyCategoria.ouro: "10% desconto em produtos",
    LoyaltyCategoria.prata: "Café/bebida grátis",
    LoyaltyCategoria.bronze: "Sem benefício",
}

_BENEFIT_PRIORITY: dict[str, int] = {
    "Sem benefício": 0,
    "Café/bebida grátis": 1,
    "10% desconto em produtos": 2,
    "1 corte gratuito": 3,
}


def compute_nivel(visit_count: int, total_spent: Decimal) -> LoyaltyNivel:
    if total_spent >= 500 or visit_count >= 12:
        return LoyaltyNivel.vip
    if visit_count >= 5 or total_spent >= 150:
        return LoyaltyNivel.fiel
    if visit_count <= 1:
        return LoyaltyNivel.novo
    return LoyaltyNivel.ativo


def compute_status(last_visit_at: Optional[datetime]) -> LoyaltyStatus:
    if last_visit_at is None:
        return LoyaltyStatus.inativo
    lv = last_visit_at if last_visit_at.tzinfo else last_visit_at.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - lv).days
    if days <= 60:
        return LoyaltyStatus.ativo
    if days <= 120:
        return LoyaltyStatus.em_risco
    return LoyaltyStatus.inativo


def compute_categoria(visit_count: int) -> Optional[LoyaltyCategoria]:
    if visit_count == 0:
        return None
    if visit_count >= 20:
        return LoyaltyCategoria.diamante
    if visit_count >= 10:
        return LoyaltyCategoria.ouro
    if visit_count >= 5:
        return LoyaltyCategoria.prata
    return LoyaltyCategoria.bronze


def resolve_benefit(nivel: LoyaltyNivel, categoria: Optional[LoyaltyCategoria]) -> str:
    """Retorna o melhor benefício entre os dois eixos (legado)."""
    b_nivel = _NIVEL_BENEFIT[nivel]
    b_cat = _CATEGORIA_BENEFIT.get(categoria, "Sem benefício") if categoria else "Sem benefício"
    if _BENEFIT_PRIORITY[b_nivel] >= _BENEFIT_PRIORITY[b_cat]:
        return b_nivel
    return b_cat


def next_milestone(visit_count: int, total_spent: Decimal) -> dict[str, str]:
    """Mensagens de progresso para próximo tier de categoria e nível (legado)."""
    if visit_count < 5:
        cat_msg = f"Faltam {5 - visit_count} visita(s) para Prata."
    elif visit_count < 10:
        cat_msg = f"Faltam {10 - visit_count} visita(s) para Ouro."
    elif visit_count < 20:
        cat_msg = f"Faltam {20 - visit_count} visita(s) para Diamante."
    else:
        cat_msg = "Nível máximo de categoria atingido."

    if total_spent >= 500 or visit_count >= 12:
        nivel_msg = "Nível VIP atingido."
    elif total_spent >= 150 or visit_count >= 5:
        v_needed = max(0, 12 - visit_count)
        r_needed = max(Decimal("0"), Decimal("500") - total_spent)
        nivel_msg = f"Faltam {v_needed} visita(s) ou R$ {r_needed:.0f} em gastos para VIP."
    elif visit_count >= 2:
        v_needed = max(0, 5 - visit_count)
        r_needed = max(Decimal("0"), Decimal("150") - total_spent)
        nivel_msg = f"Faltam {v_needed} visita(s) ou R$ {r_needed:.0f} em gastos para Fiel."
    else:
        nivel_msg = f"Faltam {2 - visit_count} visita(s) para Ativo."

    return {"categoria": cat_msg, "nivel": nivel_msg}


# ===========================================================================
# Fidelidade por pontos (Fase 2) — funções puras
# ===========================================================================


def tier_for_points(balance: int, tiers: list[LoyaltyTier]) -> Optional[LoyaltyTier]:
    """Maior tier cujo `min_points` o saldo alcança."""
    melhor: Optional[LoyaltyTier] = None
    for t in tiers:
        if balance >= t.min_points and (melhor is None or t.min_points > melhor.min_points):
            melhor = t
    return melhor


def points_to_next_tier(balance: int, tiers: list[LoyaltyTier]) -> dict[str, object]:
    """Próximo tier acima do saldo e quantos pontos faltam (passada única)."""
    acima: Optional[LoyaltyTier] = None
    for t in tiers:
        if t.min_points > balance and (acima is None or t.min_points < acima.min_points):
            acima = t
    if acima is None:
        return {"next_tier": None, "points_needed": 0}
    return {"next_tier": acima.name, "points_needed": acima.min_points - balance}


def points_for_appointment(amount: Optional[Decimal], rule: LoyaltyRule) -> int:
    """Pontos de um atendimento: round(valor × points_per_brl) + points_per_visit."""
    base = Decimal(str(amount or 0)) * rule.points_per_brl
    return int(base.to_integral_value(rounding=ROUND_HALF_UP)) + int(rule.points_per_visit)


# ===========================================================================
# Config (lazy-seed por org)
# ===========================================================================


async def get_or_seed_rule(org_id: int, session: AsyncSession) -> LoyaltyRule:
    rule = (
        await session.execute(select(LoyaltyRule).where(LoyaltyRule.organization_id == org_id))
    ).scalar_one_or_none()
    if rule is None:
        rule = LoyaltyRule(
            organization_id=org_id,
            points_per_brl=DEFAULT_POINTS_PER_BRL,
            points_per_visit=DEFAULT_POINTS_PER_VISIT,
            redemption_brl_per_point=DEFAULT_REDEMPTION_BRL_PER_POINT,
        )
        session.add(rule)
        await session.flush()
    return rule


async def get_or_seed_tiers(org_id: int, session: AsyncSession) -> list[LoyaltyTier]:
    tiers = list(
        (
            await session.execute(
                select(LoyaltyTier)
                .where(LoyaltyTier.organization_id == org_id)
                .where(LoyaltyTier.is_active.is_(True))
                .order_by(LoyaltyTier.min_points)
            )
        ).scalars()
    )
    if not tiers:
        for i, (name, mp, disc, perks) in enumerate(DEFAULT_TIERS):
            session.add(
                LoyaltyTier(
                    organization_id=org_id,
                    name=name,
                    min_points=mp,
                    discount_pct=Decimal(disc),
                    perks=perks,
                    sort_order=i,
                )
            )
        await session.flush()
        tiers = list(
            (
                await session.execute(
                    select(LoyaltyTier)
                    .where(LoyaltyTier.organization_id == org_id)
                    .where(LoyaltyTier.is_active.is_(True))
                    .order_by(LoyaltyTier.min_points)
                )
            ).scalars()
        )
    return tiers


# ===========================================================================
# Ledger (append-only) — saldo nunca negativo
# ===========================================================================


async def _current_balance(client_id: int, session: AsyncSession) -> int:
    """Saldo = balance_after do último lançamento do cliente (0 se não houver)."""
    row = (
        await session.execute(
            select(LoyaltyPointEntry.balance_after)
            .where(LoyaltyPointEntry.client_id == client_id)
            .order_by(LoyaltyPointEntry.id.desc())
            .limit(1)
        )
    ).first()
    return int(row[0]) if row else 0


async def _append_entry(
    session: AsyncSession,
    *,
    org_id: int,
    client_id: int,
    type_: LoyaltyLedgerType,
    delta: int,
    reason: str,
    ref_appointment_id: Optional[int] = None,
    ref_voucher_id: Optional[int] = None,
    by_user_id: Optional[int] = None,
) -> LoyaltyPointEntry:
    """Insere um lançamento no ledger, garantindo saldo final >= 0."""
    balance_after = await _current_balance(client_id, session) + delta
    if balance_after < 0:
        raise ValueError("Saldo de pontos insuficiente.")
    entry = LoyaltyPointEntry(
        organization_id=org_id,
        client_id=client_id,
        type=type_,
        points_delta=delta,
        balance_after=balance_after,
        reason=reason,
        ref_appointment_id=ref_appointment_id,
        ref_voucher_id=ref_voucher_id,
        created_by_user_id=by_user_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _sync_loyalty_row(
    org_id: int, client_id: int, session: AsyncSession, tiers: Optional[list[LoyaltyTier]] = None
) -> ClientLoyalty:
    """Materializa points_balance + current_tier_id no snapshot do cliente."""
    if tiers is None:
        tiers = await get_or_seed_tiers(org_id, session)
    balance = await _current_balance(client_id, session)
    tier = tier_for_points(balance, tiers)

    loyalty = (
        await session.execute(select(ClientLoyalty).where(ClientLoyalty.client_id == client_id))
    ).scalar_one_or_none()
    if loyalty is None:
        loyalty = ClientLoyalty(client_id=client_id, organization_id=org_id)
        session.add(loyalty)
    loyalty.points_balance = balance
    loyalty.current_tier_id = tier.id if tier else None
    loyalty.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return loyalty


# ===========================================================================
# Operações de pontos
# ===========================================================================


async def redeem_points(
    org_id: int,
    client_id: int,
    points: int,
    session: AsyncSession,
    by_user_id: Optional[int] = None,
) -> LoyaltyVoucher:
    """Resgata pontos gerando um voucher/crédito. Saldo nunca fica negativo."""
    if points <= 0:
        raise ValueError("Quantidade de pontos inválida.")
    rule = await get_or_seed_rule(org_id, session)
    amount = (Decimal(points) * rule.redemption_brl_per_point).quantize(Decimal("0.01"))
    voucher = LoyaltyVoucher(
        organization_id=org_id,
        client_id=client_id,
        amount_brl=amount,
        points_spent=points,
        status=LoyaltyVoucherStatus.ativo,
    )
    session.add(voucher)
    await session.flush()
    await _append_entry(
        session,
        org_id=org_id,
        client_id=client_id,
        type_=LoyaltyLedgerType.redeem,
        delta=-points,
        reason="resgate de pontos",
        ref_voucher_id=voucher.id,
        by_user_id=by_user_id,
    )
    await _sync_loyalty_row(org_id, client_id, session)
    return voucher


async def adjust_points(
    org_id: int,
    client_id: int,
    delta: int,
    reason: str,
    session: AsyncSession,
    by_user_id: Optional[int] = None,
) -> LoyaltyPointEntry:
    """Ajuste manual de pontos (crédito ou débito), com saldo >= 0."""
    if delta == 0:
        raise ValueError("Ajuste de pontos não pode ser zero.")
    entry = await _append_entry(
        session,
        org_id=org_id,
        client_id=client_id,
        type_=LoyaltyLedgerType.adjust,
        delta=delta,
        reason=reason or "ajuste manual",
        by_user_id=by_user_id,
    )
    await _sync_loyalty_row(org_id, client_id, session)
    return entry


# ===========================================================================
# Persistência do snapshot (chamada ao concluir atendimento)
# ===========================================================================


async def recalculate(client_id: int, org_id: int, session: AsyncSession) -> ClientLoyalty:
    """Recalcula o snapshot de fidelidade do cliente.

    Mantém os campos LEGADOS (visit_count/total_spent/last_visit/status/preferred
    e nivel/categoria para compat) e credita PONTOS por atendimento concluído de
    forma idempotente (1 'earn' por agendamento, via UNIQUE no ledger), derivando
    o tier do saldo. Deve ser chamado sempre que um agendamento for concluído.
    """
    # --- Agregados legados ---
    stats_row = (
        await session.execute(
            select(
                func.count(Appointment.id).label("visit_count"),
                func.coalesce(func.sum(Appointment.total_amount), 0).label("total_spent"),
                func.max(Appointment.start_at).label("last_visit_at"),
            )
            .where(Appointment.client_id == client_id)
            .where(Appointment.status == AppointmentStatus.concluido)
        )
    ).one()
    visit_count: int = stats_row.visit_count or 0
    total_spent = Decimal(str(stats_row.total_spent or 0))
    last_visit_at: Optional[datetime] = stats_row.last_visit_at

    fav_barber_row = (
        await session.execute(
            select(AppointmentItem.barber_id)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(Appointment.client_id == client_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .group_by(AppointmentItem.barber_id)
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()
    preferred_barber_id: Optional[int] = fav_barber_row[0] if fav_barber_row else None

    fav_svc_row = (
        await session.execute(
            select(AppointmentItem.service_id)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(Appointment.client_id == client_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .group_by(AppointmentItem.service_id)
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()
    preferred_service_id: Optional[int] = fav_svc_row[0] if fav_svc_row else None

    nivel = compute_nivel(visit_count, total_spent)
    loyalty_status = compute_status(last_visit_at)
    categoria = compute_categoria(visit_count)

    # --- Pontos: credita atendimentos concluídos ainda sem 'earn' (idempotente) ---
    rule = await get_or_seed_rule(org_id, session)
    earned_subq = (
        select(LoyaltyPointEntry.ref_appointment_id)
        .where(LoyaltyPointEntry.client_id == client_id)
        .where(LoyaltyPointEntry.type == LoyaltyLedgerType.earn)
        .where(LoyaltyPointEntry.ref_appointment_id.is_not(None))
    )
    pendentes = (
        await session.execute(
            select(Appointment.id, Appointment.total_amount)
            .where(Appointment.client_id == client_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(Appointment.id.not_in(earned_subq))
            .order_by(Appointment.start_at)
        )
    ).all()
    for appt_id, amount in pendentes:
        pts = points_for_appointment(amount, rule)
        if pts > 0:
            await _append_entry(
                session,
                org_id=org_id,
                client_id=client_id,
                type_=LoyaltyLedgerType.earn,
                delta=pts,
                reason="atendimento concluído",
                ref_appointment_id=appt_id,
            )

    balance = await _current_balance(client_id, session)
    tiers = await get_or_seed_tiers(org_id, session)
    tier = tier_for_points(balance, tiers)

    # --- Upsert do snapshot ---
    loyalty = (
        await session.execute(select(ClientLoyalty).where(ClientLoyalty.client_id == client_id))
    ).scalar_one_or_none()
    if loyalty is None:
        loyalty = ClientLoyalty(client_id=client_id, organization_id=org_id)
        session.add(loyalty)

    loyalty.visit_count = visit_count
    loyalty.total_spent = total_spent
    loyalty.last_visit_at = last_visit_at
    loyalty.nivel = nivel
    loyalty.status = loyalty_status
    loyalty.categoria = categoria
    loyalty.preferred_barber_id = preferred_barber_id
    loyalty.preferred_service_id = preferred_service_id
    loyalty.points_balance = balance
    loyalty.current_tier_id = tier.id if tier else None
    loyalty.updated_at = datetime.now(timezone.utc)

    await session.flush()
    return loyalty
