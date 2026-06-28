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

from collections import namedtuple
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
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

# Sentinela p/ distinguir "campo não informado" de "definido como None" nos
# overrides da venda (ex.: tornar o plano ilimitado = included_uses None).
_UNSET = object()

# Item leve p/ reusar build_combo_snapshot com um combo arbitrário (custom).
_ComboItem = namedtuple("_ComboItem", ["service_id", "position"])

# Categorias que um pacote do CATÁLOGO pode cobrir (corte/barba/corte+barba).
# `combo` = um único serviço que já representa corte+barba.
_COMBO_BASE_CATEGORIES = {"cabelo", "barba", "combo"}


# ─── cálculos puros ──────────────────────────────────────────────────────────


def validate_combo_shape(categories: Sequence[str]) -> None:
    """Valida que o combo de um PLANO DE CATÁLOGO é corte, barba ou corte+barba.

    Regra (cada uso = 1 serviço): 1 serviço ∈ {cabelo, barba, combo}; ou 2
    serviços que sejam exatamente {cabelo, barba}. Química/estética e combos
    arbitrários são rejeitados. NÃO se aplica a pacotes personalizados (combo
    livre). Levanta ``ValueError`` (o router traduz p/ HTTP 422).
    """
    cats = list(categories)
    if not cats:
        raise ValueError("Combo do plano não pode ser vazio.")
    if any(c not in _COMBO_BASE_CATEGORIES for c in cats):
        raise ValueError(
            "Combo do plano só pode conter corte, barba ou corte+barba "
            "(sem química/estética)."
        )
    if len(cats) == 1:
        return
    if len(cats) == 2 and set(cats) == {"cabelo", "barba"}:
        return
    raise ValueError(
        "Combo do plano deve ser um serviço (corte, barba ou corte+barba) "
        "ou exatamente corte + barba."
    )

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

async def create_membership(
    db: AsyncSession,
    *,
    organization_id: int,
    client_id: int,
    sold_by_user_id: Optional[int],
    start_at: Optional[datetime] = None,
    plan_id: Optional[int] = None,
    combo_service_ids: Optional[Sequence[int]] = None,
    included_uses=_UNSET,
    unlimited_use_value=_UNSET,
    price=_UNSET,
    duration_days=_UNSET,
) -> ClientMembership:
    """Cria uma assinatura gravando os snapshots imutáveis a partir de uma spec.

    Dois caminhos convergentes:
    - **Catálogo (com override opcional):** passe ``plan_id``; os campos da spec
      presentes sobrescrevem os do plano (combo/usos/preço/duração).
    - **Personalizado (do zero):** ``plan_id=None`` + ``combo_service_ids`` +
      ``price`` + ``duration_days`` + (``included_uses`` ou ``unlimited_use_value``).

    ``unit_recognized_value`` é SEMPRE recomputado da spec final (nunca herdado
    do plano). Sem restrição de forma do combo aqui — isso é só do catálogo.
    """
    client = (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if not client or client.deleted_at is not None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    plan: Optional[MembershipPlan] = None
    if plan_id is not None:
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

    # ── resolve a spec final (override > plano) ──────────────────────────────
    if combo_service_ids is not None:
        final_combo_ids = list(combo_service_ids)
    elif plan is not None:
        final_combo_ids = [
            i.service_id for i in sorted(plan.items, key=lambda i: i.position)
        ]
    else:
        final_combo_ids = []
    if not final_combo_ids:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Pacote sem combo (nenhum serviço).",
        )
    if len(set(final_combo_ids)) != len(final_combo_ids):
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Serviço repetido no combo."
        )

    final_price = price if price is not _UNSET else (plan.price if plan else None)
    final_duration = (
        duration_days if duration_days is not _UNSET
        else (plan.duration_days if plan else None)
    )
    if included_uses is not _UNSET or unlimited_use_value is not _UNSET:
        final_included = included_uses if included_uses is not _UNSET else None
        final_unit_value = (
            unlimited_use_value if unlimited_use_value is not _UNSET else None
        )
    elif plan is not None:
        final_included = plan.included_uses
        final_unit_value = plan.unlimited_use_value
    else:
        final_included = None
        final_unit_value = None

    if final_price is None or final_duration is None:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Pacote personalizado exige preço e duração.",
        )

    # ── carrega/valida serviços do combo e monta o snapshot ──────────────────
    services = (
        await db.execute(select(Service).where(Service.id.in_(final_combo_ids)))
    ).scalars().all()
    services_by_id = {s.id: s for s in services}
    missing = [sid for sid in final_combo_ids if sid not in services_by_id]
    if missing:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Combo referencia serviço inexistente nesta organização.",
        )
    for sid in final_combo_ids:
        if not services_by_id[sid].is_active:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Combo referencia serviço inativo.",
            )

    try:
        unit_value = compute_unit_value(final_price, final_included, final_unit_value)
    except ValueError as exc:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    combo_items = [
        _ComboItem(service_id=sid, position=pos)
        for pos, sid in enumerate(final_combo_ids, start=1)
    ]
    combo = build_combo_snapshot(combo_items, services_by_id)

    start = start_at or _now_utc()
    if start.tzinfo is None:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "start_at deve incluir fuso horário.",
        )
    start = start.astimezone(timezone.utc)
    end = compute_end_at(start, final_duration)

    membership = ClientMembership(
        organization_id=organization_id,
        client_id=client_id,
        plan_id=plan.id if plan else None,
        status=MembershipStatus.ativa,
        start_at=start,
        end_at=end,
        price_paid=Decimal(final_price),
        included_uses=final_included,
        used_uses=0,
        unit_recognized_value=unit_value,
        combo_snapshot=combo,
        duration_days=final_duration,
        sold_by_user_id=sold_by_user_id,
    )
    db.add(membership)
    await db.flush()
    return membership


async def sell_membership(
    db: AsyncSession,
    *,
    organization_id: int,
    client_id: int,
    plan_id: int,
    sold_by_user_id: Optional[int],
    start_at: Optional[datetime] = None,
) -> ClientMembership:
    """Contrata um plano de catálogo (caso particular de ``create_membership``)."""
    return await create_membership(
        db,
        organization_id=organization_id,
        client_id=client_id,
        sold_by_user_id=sold_by_user_id,
        start_at=start_at,
        plan_id=plan_id,
    )


async def renew_membership(
    db: AsyncSession, old: ClientMembership, *, sold_by_user_id: Optional[int]
) -> ClientMembership:
    """Renova clonando os snapshots da própria assinatura (preserva a
    personalização e funciona sem plano de catálogo). Nova vigência a partir de
    agora; saldo zerado.

    A renovação **substitui** a assinatura anterior: se a antiga ainda estava
    ``ativa``, é encerrada (``vencida``) ao criar a nova. Isso garante a
    invariante de no máximo uma assinatura ativa por cliente e elimina o
    histórico de 'múltiplas ativas' que a renovação antecipada gerava.
    """
    if old.status == MembershipStatus.ativa:
        old.status = MembershipStatus.vencida
    start = _now_utc()
    end = compute_end_at(start, old.duration_days)
    membership = ClientMembership(
        organization_id=old.organization_id,
        client_id=old.client_id,
        plan_id=old.plan_id,
        status=MembershipStatus.ativa,
        start_at=start,
        end_at=end,
        price_paid=Decimal(old.price_paid),
        included_uses=old.included_uses,
        used_uses=0,
        unit_recognized_value=Decimal(old.unit_recognized_value),
        combo_snapshot=old.combo_snapshot,
        duration_days=old.duration_days,
        sold_by_user_id=sold_by_user_id,
    )
    db.add(membership)
    await db.flush()
    return membership


async def active_memberships_for_client(
    db: AsyncSession, client_id: int
) -> list[ClientMembership]:
    """Todas as assinaturas vigentes (ativa e não vencida) do cliente."""
    return list(
        (
            await db.execute(
                select(ClientMembership)
                .where(ClientMembership.client_id == client_id)
                .where(ClientMembership.status == MembershipStatus.ativa)
                .where(ClientMembership.end_at > func.now())
                .order_by(ClientMembership.end_at.desc())
            )
        ).scalars().all()
    )


async def active_membership_for_client(
    db: AsyncSession, client_id: int
) -> Optional[ClientMembership]:
    """Assinatura vigente (ativa e não vencida) do cliente, se houver.

    Critério único de 'ativa' usado em todo o módulo (também na serialização do
    painel do cliente). Quando há mais de uma vigente, retorna a de maior
    ``end_at`` — mas os fluxos de débito automático devem usar
    ``resolve_membership_for_autopick`` p/ exigir desambiguação.
    """
    memberships = await active_memberships_for_client(db, client_id)
    return memberships[0] if memberships else None


async def resolve_membership_for_autopick(
    db: AsyncSession, client_id: int
) -> ClientMembership:
    """Resolve a assinatura a debitar quando o caller não informou ``membership_id``.

    404 se não há ativa; 409 se há mais de uma (a recepcionista precisa escolher
    explicitamente qual debitar, evitando baixar saldo da assinatura errada).
    """
    memberships = await active_memberships_for_client(db, client_id)
    if not memberships:
        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND, "Cliente não tem assinatura ativa."
        )
    if len(memberships) > 1:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Cliente tem mais de uma assinatura ativa; informe qual usar (membership_id).",
        )
    return memberships[0]


# ─── correção / reversão (ferramentas da recepcionista) ──────────────────────


async def reactivate_membership(
    db: AsyncSession,
    membership: ClientMembership,
    *,
    reactivated_by_user_id: Optional[int] = None,  # noqa: ARG001 (reservado p/ auditoria futura)
) -> ClientMembership:
    """Desfaz um cancelamento dentro da vigência (``cancelada`` → ``ativa``).

    Só reativa se a vigência ainda não terminou (senão a saída correta é renovar)
    e se o cliente não tiver outra assinatura ativa (preserva a invariante de no
    máximo uma ativa). Limpa ``canceled_at``/``canceled_by_user_id``.
    """
    if membership.status != MembershipStatus.cancelada:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Só é possível reativar uma assinatura cancelada.",
        )
    if membership.end_at <= _now_utc():
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Vigência já encerrada; renove em vez de reativar.",
        )
    if await active_memberships_for_client(db, membership.client_id):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Cliente já tem assinatura ativa; resolva-a antes de reativar esta.",
        )
    membership.status = MembershipStatus.ativa
    membership.canceled_at = None
    membership.canceled_by_user_id = None
    await db.flush()
    return membership


async def update_membership(
    db: AsyncSession,
    membership: ClientMembership,
    *,
    organization_id: int,
    client_id=_UNSET,
    start_at=_UNSET,
    end_at=_UNSET,
    duration_days=_UNSET,
    price=_UNSET,
    combo_service_ids=_UNSET,
    included_uses=_UNSET,
    set_unlimited: bool = False,
    unlimited_use_value=_UNSET,
) -> ClientMembership:
    """Corrige uma venda **antes de qualquer uso** (cliente/combo/preço/vigência).

    Recompõe os snapshots a partir dos novos valores; campos não informados são
    mantidos. Bloqueado se a assinatura já tem histórico de uso (ativo OU
    estornado) — nesse caso é preciso estornar os usos primeiro — e se não estiver
    ``ativa``. ``unit_recognized_value`` é sempre recomputado da spec final.
    """
    if membership.usages:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Assinatura já tem histórico de uso; estorne os usos antes de editar.",
        )
    if membership.status != MembershipStatus.ativa:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT, "Só é possível editar uma assinatura ativa."
        )

    # cliente
    if client_id is not _UNSET and client_id != membership.client_id:
        client = (
            await db.execute(select(Client).where(Client.id == client_id))
        ).scalar_one_or_none()
        if not client or client.deleted_at is not None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")
        membership.client_id = client_id

    # combo (recompõe o snapshot)
    if combo_service_ids is not _UNSET and combo_service_ids is not None:
        final_ids = list(combo_service_ids)
        if not final_ids:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Combo não pode ser vazio."
            )
        if len(set(final_ids)) != len(final_ids):
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Serviço repetido no combo."
            )
        services = (
            await db.execute(select(Service).where(Service.id.in_(final_ids)))
        ).scalars().all()
        services_by_id = {s.id: s for s in services}
        if any(sid not in services_by_id for sid in final_ids):
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Combo referencia serviço inexistente nesta organização.",
            )
        if any(not services_by_id[sid].is_active for sid in final_ids):
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Combo referencia serviço inativo.",
            )
        combo_items = [
            _ComboItem(service_id=sid, position=pos)
            for pos, sid in enumerate(final_ids, start=1)
        ]
        membership.combo_snapshot = build_combo_snapshot(combo_items, services_by_id)

    # preço / usos
    if price is not _UNSET and price is not None:
        membership.price_paid = Decimal(price)
    if set_unlimited:
        membership.included_uses = None
    elif included_uses is not _UNSET and included_uses is not None:
        membership.included_uses = included_uses

    # valor reconhecido por uso (recomputado da spec final)
    if membership.included_uses is None:
        # ilimitado: usa o unlimited_use_value informado; senão mantém o atual
        if unlimited_use_value is not _UNSET and unlimited_use_value is not None:
            membership.unit_recognized_value = Decimal(unlimited_use_value).quantize(
                _CENTS, rounding=ROUND_HALF_UP
            )
        elif not set_unlimited:
            pass  # já era ilimitado e não mudou o valor — mantém
        else:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Pacote ilimitado exige unlimited_use_value.",
            )
    else:
        try:
            membership.unit_recognized_value = compute_unit_value(
                membership.price_paid, membership.included_uses, None
            )
        except ValueError as exc:
            raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    # vigência
    if start_at is not _UNSET and start_at is not None:
        if start_at.tzinfo is None:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "start_at deve incluir fuso horário.",
            )
        membership.start_at = start_at.astimezone(timezone.utc)
    if end_at is not _UNSET and end_at is not None:
        if end_at.tzinfo is None:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "end_at deve incluir fuso horário.",
            )
        membership.end_at = end_at.astimezone(timezone.utc)
    elif duration_days is not _UNSET and duration_days is not None:
        membership.duration_days = duration_days
        membership.end_at = compute_end_at(membership.start_at, duration_days)
    if membership.end_at <= membership.start_at:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Vigência inválida (fim deve ser após o início).",
        )

    await db.flush()
    return membership


async def delete_membership(db: AsyncSession, membership: ClientMembership) -> None:
    """Remove uma venda **sem nenhum uso** (corrige venda totalmente equivocada).

    Só permite excluir se não houver registro de uso (ativo ou estornado). Com
    histórico de uso, o caminho correto é cancelar (preservando o histórico).
    """
    if membership.usages:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Assinatura tem histórico de uso; cancele em vez de excluir.",
        )
    await db.delete(membership)
    await db.flush()


def remaining_uses(membership: ClientMembership) -> Optional[int]:
    """Pacotes restantes; ``None`` quando ilimitado."""
    if membership.included_uses is None:
        return None
    return max(0, membership.included_uses - membership.used_uses)


# ─── consumo de pacote ───────────────────────────────────────────────────────


async def _decrement_balance(
    db: AsyncSession, membership_id: int
) -> tuple[Decimal, list]:
    """Baixa atômica de 1 uso (impede double-spend, limite e uso vencido).

    Retorna ``(unit_recognized_value, combo_snapshot)``. 404 se a assinatura não
    existe; 409 se está sem saldo/vencida/cancelada.
    """
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
    return Decimal(row.unit_recognized_value), list(row.combo_snapshot)


def _combo_matches(combo: Sequence[dict], service_ids: Sequence[int]) -> bool:
    """True se ``service_ids`` corresponde exatamente ao combo do snapshot."""
    sids = list(service_ids)
    return len(sids) == len(combo) and set(sids) == {c["service_id"] for c in combo}


async def consume_membership(
    db: AsyncSession,
    *,
    organization_id: int,
    membership_id: int,
    start_at: Optional[datetime] = None,
    assignments: Sequence[dict],
    created_by_user_id: Optional[int],
) -> Appointment:
    """Consome 1 pacote: baixa o saldo e cria o agendamento do combo.

    ``assignments`` = ``[{"service_id": int, "barber_id": int}]`` — um por serviço
    do combo (nem mais, nem menos). ``start_at`` ausente = agora (consumo avulso).
    Tudo roda na transação única do request: se qualquer passo após a baixa
    falhar, o rollback devolve o saldo.
    """
    start_src = start_at or _now_utc()
    if start_src.tzinfo is None:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "start_at deve incluir fuso horário.",
        )
    start_utc = start_src.astimezone(timezone.utc)

    # 1) Baixa atômica de saldo.
    unit_value, combo = await _decrement_balance(db, membership_id)

    # 2) O combo é fixo: os serviços do agendamento devem bater com o snapshot.
    combo_service_ids = {c["service_id"] for c in combo}
    assign_service_ids = [a["service_id"] for a in assignments]
    if not _combo_matches(combo, assign_service_ids):
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


async def apply_membership_to_appointment(
    db: AsyncSession,
    *,
    appointment: Appointment,
    membership: ClientMembership,
    created_by_user_id: Optional[int],
) -> Appointment:
    """Marca um agendamento JÁ existente como pago por assinatura.

    Baixa 1 uso, reprecifica os itens do agendamento com o rateio do valor
    reconhecido e grava o ``MembershipUsage`` (1:1). NÃO conclui o atendimento —
    a conclusão posterior detecta o uso e não cria ``Payment``. ``appointment``
    deve vir com ``items`` carregados. Atômico na transação do request.
    """
    if appointment.client_id != membership.client_id:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "O agendamento não pertence ao cliente desta assinatura.",
        )
    if appointment.status != AppointmentStatus.agendado:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Só é possível usar a assinatura em um agendamento 'agendado'.",
        )
    if await usage_for_appointment(db, appointment.id) is not None:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Este atendimento já está pago por assinatura.",
        )

    # Baixa de saldo ANTES do combo-match: se não casar, a exceção faz rollback
    # e devolve o saldo (transação única do request).
    unit_value, combo = await _decrement_balance(db, membership.id)

    item_service_ids = [it.service_id for it in appointment.items]
    if not _combo_matches(combo, item_service_ids):
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Os serviços do agendamento não correspondem ao combo da assinatura.",
        )

    rateio = rateio_price_charged(unit_value, combo)
    for it in appointment.items:
        it.price_charged = rateio[it.service_id]
    appointment.total_amount = unit_value

    db.add(
        MembershipUsage(
            organization_id=membership.organization_id,
            membership_id=membership.id,
            appointment_id=appointment.id,
            recognized_value=unit_value,
            created_by_user_id=created_by_user_id,
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        # Corrida: outra requisição concorrente já vinculou um uso ativo a este
        # agendamento (índice único parcial). Traduz SÓ essa violação p/ 409 limpo;
        # qualquer outra integridade volta a propagar (não mascarar causa real).
        if "membership_usages_appt_active_unique" in str(getattr(exc, "orig", exc)):
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                "Este atendimento já está pago por assinatura.",
            )
        raise
    return appointment


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


async def revert_usage(
    db: AsyncSession,
    appointment_id: int,
    *,
    reverted_by_user_id: Optional[int] = None,
) -> bool:
    """Estorna o uso de um agendamento cancelado/faltou/estornado, devolvendo o saldo.

    Atômico e idempotente: a baixa de saldo é amarrada à transição
    ``reverted_at`` NULL→agora num único UPDATE com RETURNING. Assim, dois
    estornos concorrentes do mesmo agendamento (ex.: ``faltou`` e ``cancelar``
    disparados quase juntos) devolvem o saldo no máximo uma vez — fechando a
    corrida do antigo read-modify-write. Registra ``reverted_by_user_id`` p/
    auditoria. Retorna ``False`` se não havia uso ativo a estornar.
    """
    row = (
        await db.execute(
            text(
                "UPDATE membership_usages "
                "SET reverted_at = now(), reverted_by_user_id = :u "
                "WHERE appointment_id = :a AND reverted_at IS NULL "
                "RETURNING membership_id"
            ),
            {"a": appointment_id, "u": reverted_by_user_id},
        )
    ).first()
    if row is None:
        return False
    await db.execute(
        text(
            "UPDATE client_memberships SET used_uses = used_uses - 1 "
            "WHERE id = :id AND used_uses > 0"
        ),
        {"id": row.membership_id},
    )
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
