"""Cálculo e persistência do snapshot de fidelidade do cliente."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Appointment, AppointmentItem, AppointmentStatus
from models.enums import LoyaltyCategoria, LoyaltyNivel, LoyaltyStatus
from models.loyalty import ClientLoyalty

# ---------------------------------------------------------------------------
# Funções de cálculo puras (sem I/O)
# ---------------------------------------------------------------------------

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
    """Retorna o melhor benefício entre os dois eixos."""
    b_nivel = _NIVEL_BENEFIT[nivel]
    b_cat = _CATEGORIA_BENEFIT.get(categoria, "Sem benefício") if categoria else "Sem benefício"
    if _BENEFIT_PRIORITY[b_nivel] >= _BENEFIT_PRIORITY[b_cat]:
        return b_nivel
    return b_cat


def next_milestone(visit_count: int, total_spent: Decimal) -> dict[str, str]:
    """Retorna mensagens de progresso para próximo tier de categoria e nível."""
    # Próxima categoria
    if visit_count < 5:
        cat_msg = f"Faltam {5 - visit_count} visita(s) para Prata."
    elif visit_count < 10:
        cat_msg = f"Faltam {10 - visit_count} visita(s) para Ouro."
    elif visit_count < 20:
        cat_msg = f"Faltam {20 - visit_count} visita(s) para Diamante."
    else:
        cat_msg = "Nível máximo de categoria atingido."

    # Próximo nível
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


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------


async def recalculate(client_id: int, org_id: int, session: AsyncSession) -> ClientLoyalty:
    """Recalcula e persiste o snapshot de fidelidade de um cliente.

    Deve ser chamado sempre que um agendamento for marcado como concluído.
    """
    # Agrega dados de visitas concluídas
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

    # Barbeiro preferido (mode)
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

    # Serviço preferido (mode)
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

    # Calcula dimensões
    nivel = compute_nivel(visit_count, total_spent)
    loyalty_status = compute_status(last_visit_at)
    categoria = compute_categoria(visit_count)

    # Upsert
    loyalty = (
        await session.execute(
            select(ClientLoyalty).where(ClientLoyalty.client_id == client_id)
        )
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
    loyalty.updated_at = datetime.now(timezone.utc)

    await session.flush()
    return loyalty
