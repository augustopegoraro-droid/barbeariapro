"""Camada de cálculo das *tools de gestão* (Agente Gestor — D-52).

Fonte única de verdade para os indicadores do Gestor. Funções `async (db, ...)`
que assumem uma `AsyncSession` já sob RLS (a org vem do contexto: bot via
`settings.bot_organization_id`, dashboard via JWT). As 3 apresentações
(bot `/bot/gestor/*`, dashboard `/admin/gestor/*`, cron `/internal/gestor/*`)
apenas chamam estas funções e formatam — sem duplicar SQL.

Reaproveita `local_date`/`today_local` (datas locais) e `resolve_role` (RBAC).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import local_date, today_local
from app.core.phone import normalize_phone
from app.core.rbac import MANAGER_ACCESS, resolve_role
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberUnit,
    BusinessHours,
    Client,
    ClientLoyalty,
    ClientMembership,
    ContactChannel,
    Lead,
    LoyaltyStatus,
    MembershipStatus,
    Organization,
    Payment,
    TimeOff,
    Unit,
    User,
    UserUnit,
)

# Períodos nomeados aceitos pelas tools (pull/dashboard).
VALID_PERIODS = ("hoje", "ontem", "semana", "mes")


# ─── período ──────────────────────────────────────────────────────────────────

def resolve_period(
    period: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> tuple[date, date, str]:
    """Resolve a janela de datas (local) a partir de um período nomeado OU de um
    intervalo explícito. Retorna `(date_from, date_to, label)`.

    `date_from`/`date_to` explícitos têm precedência. Caso contrário, `period`:
    `hoje` (default), `ontem`, `semana` (segunda→hoje), `mes` (dia 1→hoje).
    """
    if date_from is not None and date_to is not None:
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return date_from, date_to, f"{date_from.isoformat()}..{date_to.isoformat()}"

    today = today_local()
    p = (period or "hoje").lower()
    if p == "ontem":
        d = today - timedelta(days=1)
        return d, d, "ontem"
    if p == "semana":
        start = today - timedelta(days=today.weekday())  # segunda-feira
        return start, today, "semana"
    if p == "mes":
        return today.replace(day=1), today, "mês"
    return today, today, "hoje"  # 'hoje' e fallback


# ─── receita por barbeiro (base compartilhada) ────────────────────────────────

async def barber_revenue_rows(db: AsyncSession, date_from: date, date_to: date):
    """Receita por barbeiro no intervalo [date_from, date_to] (datas locais).

    Soma `AppointmentItem.price_charged` de agendamentos `concluido`, agrupado por
    barbeiro, ordenado por receita desc. Base reutilizada por financeiro e ranking.
    """
    return (
        await db.execute(
            select(
                Barber.id,
                Barber.name,
                Barber.commission_pct,
                func.count(Appointment.id.distinct()).label("appt_count"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("revenue"),
            )
            .select_from(AppointmentItem)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(local_date(Appointment.start_at) >= date_from)
            .where(local_date(Appointment.start_at) <= date_to)
            .group_by(Barber.id, Barber.name, Barber.commission_pct)
            .order_by(func.sum(AppointmentItem.price_charged).desc())
        )
    ).all()


# ─── ranking de barbeiros ─────────────────────────────────────────────────────

async def barber_ranking(db: AsyncSession, date_from: date, date_to: date) -> list[dict]:
    """Ranking de produção por barbeiro no período (receita, atendimentos,
    ticket médio e comissão). Já ordenado por receita desc."""
    rows = await barber_revenue_rows(db, date_from, date_to)
    ranking: list[dict] = []
    for r in rows:
        revenue = Decimal(str(r.revenue))
        commission = (revenue * r.commission_pct).quantize(Decimal("0.01"))
        ticket = (revenue / r.appt_count).quantize(Decimal("0.01")) if r.appt_count else Decimal("0.00")
        ranking.append(
            {
                "barber_id": r.id,
                "barber_name": r.name,
                "appointment_count": r.appt_count,
                "revenue": float(revenue),
                "ticket_medio": float(ticket),
                "commission": float(commission),
            }
        )
    return ranking


# ─── resumo financeiro ────────────────────────────────────────────────────────

async def financial_summary(db: AsyncSession, date_from: date, date_to: date) -> dict:
    """Resumo financeiro do período.

    `revenue` e `commissions` são exatos para qualquer janela (somam itens
    `concluido` no intervalo). `expenses` segue a semântica de competência mensal
    já adotada no sistema (`Expense.competence_month`): soma as despesas dos meses
    tocados pelo intervalo — por isso `net` só é plenamente significativo em
    janelas de mês fechado. `by_method` agrega `Payment` (valor + gorjeta) no período.
    """
    barber_rows = await barber_revenue_rows(db, date_from, date_to)
    revenue = sum((Decimal(str(r.revenue)) for r in barber_rows), Decimal("0"))
    commissions = sum(
        (Decimal(str(r.revenue)) * r.commission_pct for r in barber_rows), Decimal("0")
    )
    appt_count = sum(r.appt_count for r in barber_rows)

    method_rows = (
        await db.execute(
            select(
                Payment.method,
                func.sum(Payment.amount + func.coalesce(Payment.tip_amount, 0)).label("total"),
                func.count(Payment.id).label("cnt"),
            )
            .where(local_date(Payment.paid_at) >= date_from)
            .where(local_date(Payment.paid_at) <= date_to)
            .group_by(Payment.method)
            .order_by(func.sum(Payment.amount).desc())
        )
    ).all()
    by_method = [
        {"method": r.method.value, "amount": float(r.total), "count": r.cnt}
        for r in method_rows
    ]

    # Despesas por competência mensal dos meses tocados pelo intervalo.
    from models import Expense  # import tardio: evita ciclo na borda do módulo

    first_month = date_from.replace(day=1)
    last_month = date_to.replace(day=1)
    expenses_total = (
        await db.execute(
            select(func.coalesce(func.sum(Expense.amount), 0))
            .where(Expense.competence_month >= first_month)
            .where(Expense.competence_month <= last_month)
        )
    ).scalar_one()
    expenses = Decimal(str(expenses_total))

    net = revenue - commissions - expenses
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "revenue": float(revenue),
        "commissions": float(commissions),
        "expenses": float(expenses),
        "net": float(net),
        "appointment_count": appt_count,
        "by_method": by_method,
    }


# ─── gating: telefone → role ──────────────────────────────────────────────────

async def resolve_role_by_phone(db: AsyncSession, phone: str) -> Optional[str]:
    """Role efetiva (maior prioridade) do usuário cujo `phone_e164` casa com
    `phone`, escopado à org da sessão (RLS). `None` se telefone inválido, sem
    usuário correspondente, ou usuário inativo.

    Usado no gating do Agente Gestor: o chamador decide se a role autoriza dados
    sensíveis (ver `is_manager_role`).
    """
    try:
        normalized = normalize_phone(phone)
    except ValueError:
        return None

    user = (
        await db.execute(
            select(User).where(User.phone_e164 == normalized)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    # user_units não tem RLS própria; o join com units (que tem) garante o escopo.
    unit_links = (
        await db.execute(
            select(UserUnit)
            .join(Unit, Unit.id == UserUnit.unit_id)
            .where(UserUnit.user_id == user.id)
        )
    ).scalars().all()
    return resolve_role(list(unit_links))


def is_manager_role(role: Optional[str]) -> bool:
    """True se a role autoriza dados de gestão (owner/manager)."""
    return role in MANAGER_ACCESS


# ===========================================================================
# Fase B — clientes inativos, buracos na agenda, faturamento-IA, MRR
# ===========================================================================

# ─── clientes inativos ────────────────────────────────────────────────────────

async def inactive_clients(
    db: AsyncSession, days: Optional[int] = None, limit: int = 50
) -> list[dict]:
    """Clientes parados, candidatos a reativação.

    Sem `days`: usa o status de fidelidade (`em_risco`/`inativo`) — mesmo critério
    da campanha automática (`reactivation.run`). Com `days`: filtra por
    `last_visit_at` mais antigo que N dias. Ordena do mais inativo p/ o mais
    recente; ignora bloqueados/excluídos.
    """
    q = (
        select(ClientLoyalty, Client, Barber.name.label("barber_name"))
        .join(Client, Client.id == ClientLoyalty.client_id)
        .outerjoin(Barber, Barber.id == ClientLoyalty.preferred_barber_id)
        .where(Client.deleted_at.is_(None))
        .where(Client.is_blocked.is_(False))
    )
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.where(ClientLoyalty.last_visit_at.isnot(None)).where(
            ClientLoyalty.last_visit_at <= cutoff
        )
    else:
        q = q.where(
            ClientLoyalty.status.in_([LoyaltyStatus.em_risco, LoyaltyStatus.inativo])
        )
    q = q.order_by(ClientLoyalty.last_visit_at.asc().nulls_last()).limit(limit)

    rows = (await db.execute(q)).all()
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for loyalty, client, barber_name in rows:
        days_since = None
        if loyalty.last_visit_at:
            lv = loyalty.last_visit_at
            if lv.tzinfo is None:
                lv = lv.replace(tzinfo=timezone.utc)
            days_since = (now - lv).days
        out.append(
            {
                "client_id": client.id,
                "name": client.name,
                "phone": client.phone_e164,
                "days_since_last_visit": days_since,
                "visit_count": loyalty.visit_count,
                "status": loyalty.status.value,
                "preferred_barber": barber_name,
            }
        )
    return out


# ─── buracos na agenda ────────────────────────────────────────────────────────

def _free_windows(
    busy: list[tuple[datetime, datetime]], start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Janelas livres em [start, end] dado um conjunto de intervalos ocupados.

    Mescla os ocupados (clipados à janela) e devolve os vãos restantes."""
    merged: list[list[datetime]] = []
    for s, e in sorted(busy):
        s, e = max(s, start), min(e, end)
        if s >= e:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    free: list[tuple[datetime, datetime]] = []
    cur = start
    for s, e in merged:
        if s > cur:
            free.append((cur, s))
        cur = max(cur, e)
    if cur < end:
        free.append((cur, end))
    return free


async def agenda_gaps(db: AsyncSession, target_date: date, unit_id: int) -> list[dict]:
    """Janelas ociosas por barbeiro na data, dentro do horário comercial da unidade.

    Subtrai agendamentos (não cancelados) e folgas. Se `target_date` é hoje, corta
    o passado (só interessa o que ainda dá pra preencher). Ordenado por ociosidade
    desc. `[]` se a unidade está fechada no dia."""
    unit = (await db.execute(select(Unit).where(Unit.id == unit_id))).scalar_one_or_none()
    tz = ZoneInfo(unit.timezone if unit and unit.timezone else "America/Sao_Paulo")

    pg_weekday = (target_date.weekday() + 1) % 7  # schema: 0=Dom .. 6=Sáb
    bh_rows = (
        await db.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id == unit_id)
            .where(BusinessHours.weekday == pg_weekday)
        )
    ).scalars().all()
    if not bh_rows:
        return []

    open_t = min(b.open_time for b in bh_rows)
    close_t = max(b.close_time for b in bh_rows)
    window_start = datetime.combine(target_date, open_t, tzinfo=tz)
    window_end = datetime.combine(target_date, close_t, tzinfo=tz)

    if target_date == today_local():
        now_local = datetime.now(timezone.utc).astimezone(tz)
        window_start = max(window_start, now_local)
    if window_start >= window_end:
        return []

    day_start_utc = window_start.astimezone(timezone.utc)
    day_end_utc = window_end.astimezone(timezone.utc)

    barbers = (
        await db.execute(
            select(Barber)
            .join(BarberUnit, BarberUnit.barber_id == Barber.id)
            .where(BarberUnit.unit_id == unit_id)
            .where(Barber.deleted_at.is_(None))
            .order_by(Barber.name)
        )
    ).scalars().all()

    out: list[dict] = []
    for barber in barbers:
        appts = (
            await db.execute(
                select(Appointment.start_at, Appointment.end_at)
                .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
                .where(AppointmentItem.barber_id == barber.id)
                .where(Appointment.status != AppointmentStatus.cancelado)
                .where(Appointment.start_at < day_end_utc)
                .where(Appointment.end_at > day_start_utc)
            )
        ).all()
        offs = (
            await db.execute(
                select(TimeOff.start_at, TimeOff.end_at)
                .where(TimeOff.barber_id == barber.id)
                .where(TimeOff.start_at < day_end_utc)
                .where(TimeOff.end_at > day_start_utc)
            )
        ).all()

        busy = [
            (s.astimezone(tz), e.astimezone(tz))
            for s, e in [*appts, *offs]
        ]
        windows = _free_windows(busy, window_start, window_end)
        idle_min = int(sum((e - s).total_seconds() for s, e in windows) // 60)
        out.append(
            {
                "barber_id": barber.id,
                "barber_name": barber.name,
                "idle_min": idle_min,
                "free_windows": [
                    {"start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")}
                    for s, e in windows
                ],
            }
        )

    out.sort(key=lambda b: b["idle_min"], reverse=True)
    return out


# ─── faturamento gerado pela IA ───────────────────────────────────────────────

async def ai_generated_revenue(
    db: AsyncSession, date_from: date, date_to: date, unit_id: Optional[int] = None
) -> dict:
    """Resultado atribuível ao bot: agendamentos concluídos com
    `booking_channel='whatsapp'` (contagem + receita reconhecida) e leads criados
    fora do horário comercial no período (oportunidade que a IA capturou sozinha)."""
    row = (
        await db.execute(
            select(
                func.count(Appointment.id.distinct()).label("appts"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("revenue"),
            )
            .select_from(Appointment)
            .outerjoin(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(Appointment.booking_channel == ContactChannel.whatsapp)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(local_date(Appointment.start_at) >= date_from)
            .where(local_date(Appointment.start_at) <= date_to)
        )
    ).one()

    leads_after_hours = await _count_leads_after_hours(db, date_from, date_to, unit_id)

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "appointments": int(row.appts),
        "revenue": float(row.revenue),
        "leads_after_hours": leads_after_hours,
    }


async def _count_leads_after_hours(
    db: AsyncSession, date_from: date, date_to: date, unit_id: Optional[int]
) -> int:
    """Conta leads criados no período cujo horário local cai FORA do horário
    comercial da unidade. Sem unidade/horário cadastrado, retorna 0 (não chuta)."""
    if unit_id is None:
        unit_id = (
            await db.execute(
                select(Unit.id).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1)
            )
        ).scalar_one_or_none()
    if unit_id is None:
        return 0

    unit = (await db.execute(select(Unit).where(Unit.id == unit_id))).scalar_one_or_none()
    tz = ZoneInfo(unit.timezone if unit and unit.timezone else "America/Sao_Paulo")

    bh_rows = (
        await db.execute(
            select(BusinessHours).where(BusinessHours.unit_id == unit_id)
        )
    ).scalars().all()
    if not bh_rows:
        return 0
    bh_map: dict[int, list[tuple[time, time]]] = {}
    for b in bh_rows:
        bh_map.setdefault(b.weekday, []).append((b.open_time, b.close_time))

    lead_rows = (
        await db.execute(
            select(Lead.created_at)
            .where(local_date(Lead.created_at) >= date_from)
            .where(local_date(Lead.created_at) <= date_to)
        )
    ).scalars().all()

    after = 0
    for created in lead_rows:
        c = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        local = c.astimezone(tz)
        pg_weekday = (local.weekday() + 1) % 7
        t = local.time()
        if not any(o <= t < cl for o, cl in bh_map.get(pg_weekday, [])):
            after += 1
    return after


# ─── MRR (receita recorrente das assinaturas) ─────────────────────────────────

async def mrr(db: AsyncSession) -> dict:
    """Receita recorrente mensal das assinaturas vigentes.

    Normaliza cada assinatura ativa para 30 dias: `price_paid / duration_days * 30`.
    Inclui contagem de ativas e quantas vencem nos próximos 30 dias."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=30)

    rows = (
        await db.execute(
            select(
                ClientMembership.price_paid,
                ClientMembership.duration_days,
                ClientMembership.end_at,
            )
            .where(ClientMembership.status == MembershipStatus.ativa)
            .where(ClientMembership.end_at > now)
        )
    ).all()

    total = Decimal("0")
    expiring = 0
    for price_paid, duration_days, end_at in rows:
        if duration_days:
            total += (Decimal(price_paid) / Decimal(duration_days) * 30)
        ea = end_at if end_at.tzinfo else end_at.replace(tzinfo=timezone.utc)
        if ea <= horizon:
            expiring += 1

    return {
        "active_count": len(rows),
        "mrr": float(total.quantize(Decimal("0.01"))),
        "expiring_30d": expiring,
    }


# ===========================================================================
# Fase C — push proativo: destinatários, resumo diário, alertas
# ===========================================================================

async def manager_phones(db: AsyncSession) -> list[str]:
    """Telefones (E.164) dos usuários owner/manager com telefone cadastrado, na
    org da sessão. Destinatários do push do Gestor."""
    rows = (
        await db.execute(
            select(User.phone_e164, UserUnit.role)
            .join(UserUnit, UserUnit.user_id == User.id)
            .join(Unit, Unit.id == UserUnit.unit_id)
            .where(User.phone_e164.isnot(None))
            .where(User.is_active.is_(True))
        )
    ).all()
    phones: list[str] = []
    for phone, role in rows:
        if phone and is_manager_role(role.value if hasattr(role, "value") else role):
            if phone not in phones:
                phones.append(phone)
    return phones


async def _noshow_count(db: AsyncSession, date_from: date, date_to: date) -> int:
    return (
        await db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.status == AppointmentStatus.faltou)
            .where(local_date(Appointment.start_at) >= date_from)
            .where(local_date(Appointment.start_at) <= date_to)
        )
    ).scalar_one()


async def _daily_revenue_series(
    db: AsyncSession, date_from: date, date_to: date
) -> dict[date, float]:
    """Receita reconhecida por dia (concluído) no intervalo. Dias sem atendimento
    ficam ausentes do dict."""
    rows = (
        await db.execute(
            select(
                local_date(Appointment.start_at).label("day"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("rev"),
            )
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(local_date(Appointment.start_at) >= date_from)
            .where(local_date(Appointment.start_at) <= date_to)
            .group_by(local_date(Appointment.start_at))
        )
    ).all()
    return {r.day: float(r.rev) for r in rows}


async def daily_digest(db: AsyncSession, target_date: date) -> dict:
    """Números do resumo diário do Gestor: faturamento/atendimentos do dia, topo do
    ranking, faltas, resultado da IA e ociosidade prevista para amanhã."""
    fin = await financial_summary(db, target_date, target_date)
    ranking = await barber_ranking(db, target_date, target_date)
    top = ranking[0] if ranking else None
    noshows = await _noshow_count(db, target_date, target_date)
    ai = await ai_generated_revenue(db, target_date, target_date)

    tomorrow = target_date + timedelta(days=1)
    unit_id = (
        await db.execute(
            select(Unit.id).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1)
        )
    ).scalar_one_or_none()
    gaps = await agenda_gaps(db, tomorrow, unit_id) if unit_id else []
    tomorrow_idle_min = sum(g["idle_min"] for g in gaps)

    return {
        "date": target_date.isoformat(),
        "revenue": fin["revenue"],
        "appointment_count": fin["appointment_count"],
        "top_barber": (
            {"name": top["barber_name"], "revenue": top["revenue"]} if top else None
        ),
        "noshows": int(noshows),
        "ai_appointments": ai["appointments"],
        "ai_revenue": ai["revenue"],
        "tomorrow_idle_min": tomorrow_idle_min,
    }


async def revenue_alerts(db: AsyncSession, target_date: date) -> list[dict]:
    """Condições de alerta proativo. Lista (possivelmente vazia) de
    `{type, message}`:
    - `meta`: a projeção do mês (ritmo atual) fica abaixo de `monthly_revenue_goal`;
    - `queda`: a receita do último dia fechado (ontem) cai bem abaixo da média da
      semana anterior.
    """
    alerts: list[dict] = []

    org = (
        await db.execute(select(Organization).limit(1))
    ).scalar_one_or_none()

    # ── meta do mês (projeção pelo ritmo) ────────────────────────────────────
    month_start = target_date.replace(day=1)
    if org is not None and org.monthly_revenue_goal:
        rows = await barber_revenue_rows(db, month_start, target_date)
        month_rev = sum((Decimal(str(r.revenue)) for r in rows), Decimal("0"))
        elapsed = (target_date - month_start).days + 1
        next_m = (
            date(month_start.year + 1, 1, 1)
            if month_start.month == 12
            else date(month_start.year, month_start.month + 1, 1)
        )
        days_in_month = (next_m - month_start).days
        if elapsed > 0:
            projection = month_rev / elapsed * days_in_month
            goal = Decimal(str(org.monthly_revenue_goal))
            if projection < goal:
                alerts.append(
                    {
                        "type": "meta",
                        "message": (
                            f"📉 No ritmo atual o mês fecha em ~R${projection:,.0f}, "
                            f"abaixo da meta de R${goal:,.0f} "
                            f"(faltam ~R${goal - projection:,.0f})."
                        ),
                    }
                )

    # ── queda de movimento (ontem vs média da semana anterior) ───────────────
    ref_day = target_date - timedelta(days=1)
    window_start = ref_day - timedelta(days=7)
    series = await _daily_revenue_series(db, window_start, ref_day)
    ref_rev = series.get(ref_day, 0.0)
    prior = [series.get(window_start + timedelta(days=i), 0.0) for i in range(7)]
    avg = sum(prior) / 7
    if avg > 0 and ref_rev < 0.6 * avg:
        alerts.append(
            {
                "type": "queda",
                "message": (
                    f"⚠️ Ontem o faturamento foi R${ref_rev:,.0f}, bem abaixo da "
                    f"média da semana anterior (R${avg:,.0f})."
                ),
            }
        )

    return alerts
