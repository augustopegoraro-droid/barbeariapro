"""Regra de negócio da mensalidade/assinatura do CLIENTE FINAL.

Camada de serviço reutilizável (painel, cron e futuras tools do bot). Routers
ficam finos. Conceitos:

- Plano = combo fixo (lista de serviços) + N usos (NULL = ilimitado).
- Venda = grava ``ClientMembership`` com *snapshots* imutáveis do plano.
- Uso = baixa atômica de saldo + cria ``Appointment`` (um ``AppointmentItem``
  por serviço do combo, com ``price_charged`` = rateio do valor reconhecido) +
  ``MembershipUsage`` (vínculo 1:1 ao agendamento). A venda NÃO vira receita;
  cada uso reconhece ``unit_recognized_value`` (receita rateada no uso).

As funções de cálculo (``compute_*``/``rateio_*``/``build_*``) são puras e
testáveis isoladamente. As funções de I/O assumem uma ``AsyncSession`` já sob
RLS (org corrente definida pelo ``get_tenant_db``/``get_bot_db``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.scheduling import barber_has_conflict
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberService,
    Client,
    ClientMembership,
    MembershipPlan,
    MembershipStatus,
    MembershipUsage,
    Service,
    Unit,
)

_CENTS = Decimal("0.01")


# ─── cálculos puros ──────────────────────────────────────────────────────────

def compute_unit_value(
    price: Decimal,
    included_uses: Optional[int],
    unlimited_use_value: Optional[Decimal],
) -> Decimal:
    """Valor reconhecido por uso de pacote.

    Finito → ``price / included_uses``; ilimitado → ``unlimited_use_value``.
    """
    if included_uses is None:
        if unlimited_use_value is None:
            raise ValueError("Plano ilimitado exige unlimited_use_value.")
        return Decimal(unlimited_use_value).quantize(_CENTS, rounding=ROUND_HALF_UP)
    if included_uses <= 0:
        raise ValueError("included_uses deve ser positivo ou NULL (ilimitado).")
    return (Decimal(price) / Decimal(included_uses)).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )


def compute_end_at(start_at: datetime, duration_days: int) -> datetime:
    """Fim da vigência. v1: ``start_at + duration_days`` (UTC)."""
    return start_at + timedelta(days=duration_days)


def build_combo_snapshot(
    plan_items: Sequence[object], services_by_id: dict[int, Service]
) -> list[dict]:
    """``[{service_id, base_price, position}]`` ordenado por ``position``.

    ``base_price`` é serializado como string para preservar precisão no JSONB.
    """
    snapshot: list[dict] = []
    for item in sorted(plan_items, key=lambda i: i.position):
        svc = services_by_id[item.service_id]
        snapshot.append(
            {
                "service_id": item.service_id,
                "base_price": str(Decimal(svc.price).quantize(_CENTS)),
                "position": item.position,
            }
        )
    return snapshot


def rateio_price_charged(unit_value: Decimal, combo: Sequence[dict]) -> dict[int, Decimal]:
    """Distribui ``unit_value`` entre os serviços do combo.

    Proporcional ao ``base_price`` de cada serviço; o resíduo de arredondamento
    vai para o último item, garantindo ``sum(rateio) == unit_value`` exato — para
    que a receita (``AppointmentItem.price_charged``) e a comissão fiquem corretas.
    """
    unit_value = Decimal(unit_value).quantize(_CENTS)
    ordered = sorted(combo, key=lambda c: c["position"])
    total_base = sum(Decimal(c["base_price"]) for c in ordered)

    result: dict[int, Decimal] = {}
    allocated = Decimal("0")
    n = len(ordered)
    for idx, c in enumerate(ordered):
        if idx == n - 1:
            share = unit_value - allocated  # resíduo no último item
        elif total_base > 0:
            share = (unit_value * Decimal(c["base_price"]) / total_base).quantize(
                _CENTS, rounding=ROUND_HALF_UP
            )
            allocated += share
        else:  # combo todo grátis: divide igualmente
            share = (unit_value / n).quantize(_CENTS, rounding=ROUND_HALF_UP)
            allocated += share
        result[c["service_id"]] = share
    return result


# ─── helpers de I/O ──────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _default_unit(db: AsyncSession, organization_id: int) -> Unit:
    unit = (
        await db.execute(
            select(Unit)
            .where(Unit.organization_id == organization_id)
            .where(Unit.deleted_at.is_(None))
            .order_by(Unit.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not unit:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Nenhuma unidade configurada."
        )
    return unit


# ─── venda / leitura ─────────────────────────────────────────────────────────

async def sell_membership(
    db: AsyncSession,
    *,
    organization_id: int,
    client_id: int,
    plan_id: int,
    sold_by_user_id: Optional[int],
    start_at: Optional[datetime] = None,
) -> ClientMembership:
    """Contrata um plano para um cliente, gravando os snapshots imutáveis."""
    client = (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if not client or client.deleted_at is not None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    plan = (
        await db.execute(
            select(MembershipPlan)
            .where(MembershipPlan.id == plan_id)
            .options(selectinload(MembershipPlan.items))
        )
    ).scalar_one_or_none()
    if not plan or plan.deleted_at is not None or not plan.is_active:
        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND, "Plano não encontrado ou inativo."
        )
    if not plan.items:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Plano sem combo configurado (nenhum serviço).",
        )

    service_ids = [i.service_id for i in plan.items]
    services = (
        await db.execute(select(Service).where(Service.id.in_(service_ids)))
    ).scalars().all()
    services_by_id = {s.id: s for s in services}
    missing = [sid for sid in service_ids if sid not in services_by_id]
    if missing:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Combo referencia serviço inexistente.",
        )

    try:
        unit_value = compute_unit_value(
            plan.price, plan.included_uses, plan.unlimited_use_value
        )
    except ValueError as exc:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    combo = build_combo_snapshot(plan.items, services_by_id)
    start = start_at or _now_utc()
    if start.tzinfo is None:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "start_at deve incluir fuso horário.",
        )
    start = start.astimezone(timezone.utc)
    end = compute_end_at(start, plan.duration_days)

    membership = ClientMembership(
        organization_id=organization_id,
        client_id=client_id,
        plan_id=plan.id,
        status=MembershipStatus.ativa,
        start_at=start,
        end_at=end,
        price_paid=Decimal(plan.price),
        included_uses=plan.included_uses,
        used_uses=0,
        unit_recognized_value=unit_value,
        combo_snapshot=combo,
        duration_days=plan.duration_days,
        sold_by_user_id=sold_by_user_id,
    )
    db.add(membership)
    await db.flush()
    return membership


async def active_membership_for_client(
    db: AsyncSession, client_id: int
) -> Optional[ClientMembership]:
    """Assinatura vigente (ativa e não vencida) do cliente, se houver."""
    return (
        await db.execute(
            select(ClientMembership)
            .where(ClientMembership.client_id == client_id)
            .where(ClientMembership.status == MembershipStatus.ativa)
            .where(ClientMembership.end_at > func.now())
            .order_by(ClientMembership.end_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def remaining_uses(membership: ClientMembership) -> Optional[int]:
    """Pacotes restantes; ``None`` quando ilimitado."""
    if membership.included_uses is None:
        return None
    return max(0, membership.included_uses - membership.used_uses)


# ─── consumo de pacote ───────────────────────────────────────────────────────

async def consume_membership(
    db: AsyncSession,
    *,
    organization_id: int,
    membership_id: int,
    start_at: datetime,
    assignments: Sequence[dict],
    created_by_user_id: Optional[int],
) -> Appointment:
    """Consome 1 pacote: baixa o saldo e cria o agendamento do combo.

    ``assignments`` = ``[{"service_id": int, "barber_id": int}]`` — um por serviço
    do combo (nem mais, nem menos). Tudo roda na transação única do request: se
    qualquer passo após a baixa falhar, o rollback devolve o saldo.
    """
    if start_at.tzinfo is None:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "start_at deve incluir fuso horário.",
        )
    start_utc = start_at.astimezone(timezone.utc)

    # 1) Baixa atômica de saldo (impede double-spend, limite e uso vencido).
    row = (
        await db.execute(
            text(
                "UPDATE client_memberships "
                "SET used_uses = used_uses + 1 "
                "WHERE id = :id AND status = 'ativa' AND end_at > now() "
                "  AND (included_uses IS NULL OR used_uses < included_uses) "
                "RETURNING unit_recognized_value, combo_snapshot"
            ),
            {"id": membership_id},
        )
    ).first()
    if row is None:
        # Distingue inexistente (404) de indisponível (409).
        exists = (
            await db.execute(
                select(ClientMembership.id).where(
                    ClientMembership.id == membership_id
                )
            )
        ).first()
        if exists is None:
            raise HTTPException(
                http_status.HTTP_404_NOT_FOUND, "Assinatura não encontrada."
            )
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Assinatura sem saldo, vencida ou cancelada.",
        )

    unit_value = Decimal(row.unit_recognized_value)
    combo = list(row.combo_snapshot)

    # 2) O combo é fixo: os serviços do agendamento devem bater com o snapshot.
    combo_service_ids = {c["service_id"] for c in combo}
    assign_service_ids = [a["service_id"] for a in assignments]
    if len(assign_service_ids) != len(combo) or set(assign_service_ids) != combo_service_ids:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Os serviços informados não correspondem ao combo do plano.",
        )

    barber_by_service = {a["service_id"]: a["barber_id"] for a in assignments}

    # 3) Carregar serviços e validar vínculo barbeiro↔serviço.
    services = (
        await db.execute(select(Service).where(Service.id.in_(list(combo_service_ids))))
    ).scalars().all()
    services_by_id = {s.id: s for s in services}
    for sid in combo_service_ids:
        svc = services_by_id.get(sid)
        if not svc or not svc.is_active:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Serviço do combo inativo ou inexistente.",
            )
        bid = barber_by_service[sid]
        barber = (
            await db.execute(select(Barber).where(Barber.id == bid))
        ).scalar_one_or_none()
        if not barber or barber.deleted_at is not None:
            raise HTTPException(
                http_status.HTTP_404_NOT_FOUND, "Profissional não encontrado."
            )
        link = (
            await db.execute(
                select(BarberService)
                .where(BarberService.barber_id == bid)
                .where(BarberService.service_id == sid)
            )
        ).scalar_one_or_none()
        if not link:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Este profissional não realiza um dos serviços do combo.",
            )

    # 4) Janela do agendamento = soma das durações; conflito por profissional.
    total_duration = sum(
        services_by_id[c["service_id"]].default_duration_min for c in combo
    )
    end_utc = start_utc + timedelta(minutes=total_duration)
    for bid in set(barber_by_service.values()):
        if await barber_has_conflict(db, bid, start_utc, end_utc):
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                "Conflito de horário: profissional já tem agendamento ou folga.",
            )

    # 5) display_number sequencial com advisory lock (mesmo padrão da agenda).
    unit = await _default_unit(db, organization_id)
    await db.execute(text(f"SELECT pg_advisory_xact_lock({unit.id})"))
    next_num = (
        await db.execute(
            select(func.coalesce(func.max(Appointment.display_number), 0) + 1).where(
                Appointment.unit_id == unit.id
            )
        )
    ).scalar_one()

    # 6) Agendamento + itens com price_charged = rateio (receita/comissão).
    rateio = rateio_price_charged(unit_value, combo)
    appt = Appointment(
        organization_id=organization_id,
        unit_id=unit.id,
        client_id=(
            await db.execute(
                select(ClientMembership.client_id).where(
                    ClientMembership.id == membership_id
                )
            )
        ).scalar_one(),
        display_number=next_num,
        start_at=start_utc,
        end_at=end_utc,
        status=AppointmentStatus.agendado,
        total_amount=unit_value,
        created_by_user_id=created_by_user_id,
    )
    db.add(appt)
    await db.flush()

    for c in combo:
        sid = c["service_id"]
        db.add(
            AppointmentItem(
                appointment_id=appt.id,
                service_id=sid,
                barber_id=barber_by_service[sid],
                price_charged=rateio[sid],
                duration_minutes=services_by_id[sid].default_duration_min,
                position=c["position"],
            )
        )

    # 7) Registro do uso (vínculo 1:1 ao agendamento).
    db.add(
        MembershipUsage(
            organization_id=organization_id,
            membership_id=membership_id,
            appointment_id=appt.id,
            recognized_value=unit_value,
            created_by_user_id=created_by_user_id,
        )
    )
    await db.flush()
    return appt


async def usage_for_appointment(
    db: AsyncSession, appointment_id: int
) -> Optional[MembershipUsage]:
    """Uso de mensalidade vinculado a um agendamento (ativo, não revertido)."""
    return (
        await db.execute(
            select(MembershipUsage)
            .where(MembershipUsage.appointment_id == appointment_id)
            .where(MembershipUsage.reverted_at.is_(None))
        )
    ).scalar_one_or_none()


async def revert_usage(db: AsyncSession, appointment_id: int) -> bool:
    """Estorna o uso de um agendamento cancelado/faltou, devolvendo o saldo.

    Idempotente: um segundo estorno do mesmo agendamento não faz nada.
    """
    usage = await usage_for_appointment(db, appointment_id)
    if usage is None:
        return False
    await db.execute(
        text(
            "UPDATE client_memberships SET used_uses = used_uses - 1 "
            "WHERE id = :id AND used_uses > 0"
        ),
        {"id": usage.membership_id},
    )
    usage.reverted_at = _now_utc()
    await db.flush()
    return True


# ─── expiração (cron) ────────────────────────────────────────────────────────

async def expire_memberships(db: AsyncSession) -> dict:
    """Marca como 'vencida' toda assinatura ativa cuja vigência terminou.

    Pacotes não usados simplesmente expiram (sem rollover). Escopo de tenant
    garantido pela RLS da sessão. Retorna ``{"expired": n}``.
    """
    rows = (
        await db.execute(
            text(
                "UPDATE client_memberships SET status = 'vencida' "
                "WHERE status = 'ativa' AND end_at < now() RETURNING id"
            )
        )
    ).all()
    return {"expired": len(rows)}
