# file: app/services/health.py
"""Health score por tenant (0–100) — visão proativa de risco de churn.

Função PURA (sem I/O): recebe a linha do overview (`app_platform_org_overview`)
já mesclada com o dunning da assinatura (`app_platform_billing_subscriptions`)
e devolve score, faixa e motivos. Toda a matéria-prima já existe nas funções
SECURITY DEFINER — nenhuma migration é necessária.

Modelo (pesos somam 100):
- Engajamento (45): recência da última atividade (25) + volume de
  agendamentos em 30 dias (20). É o preditor nº 1 de churn em SaaS de agenda.
- Adoção (25): profissionais (8) + clientes (12) + usuários (5) cadastrados.
- Financeiro (30): status da assinatura, com penalidade progressiva por
  dias de atraso.

Faixas: >=70 `healthy` · >=40 `watch` · <40 `at_risk` · suspensa → `suspended`.
Orgs com menos de `GRACE_DAYS` dias de vida ainda não têm histórico para
julgar engajamento: nunca caem abaixo de `watch` (motivo explícito na lista).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# Dias de carência para orgs recém-criadas (sem histórico ≠ em risco).
GRACE_DAYS = 14

BAND_HEALTHY = "healthy"
BAND_WATCH = "watch"
BAND_AT_RISK = "at_risk"
BAND_SUSPENDED = "suspended"


def _days_since(ref: Optional[datetime], now: datetime) -> Optional[int]:
    if ref is None:
        return None
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return max(int((now - ref).total_seconds() // 86400), 0)


def _engagement(row: dict, now: datetime) -> tuple[int, list[str]]:
    pts = 0
    reasons: list[str] = []

    idle = _days_since(row.get("last_activity"), now)
    if idle is None:
        reasons.append("nenhuma atividade registrada até hoje")
    elif idle <= 3:
        pts += 25
    elif idle <= 7:
        pts += 20
    elif idle <= 14:
        pts += 12
        reasons.append(f"sem atividade há {idle} dias")
    elif idle <= 30:
        pts += 5
        reasons.append(f"sem atividade há {idle} dias")
    else:
        reasons.append(f"sem atividade há {idle} dias")

    appt = int(row.get("appt_30d") or 0)
    if appt >= 30:
        pts += 20
    elif appt >= 10:
        pts += 15
    elif appt >= 3:
        pts += 8
    elif appt >= 1:
        pts += 4
        reasons.append(f"apenas {appt} agendamento(s) em 30 dias")
    else:
        reasons.append("nenhum agendamento em 30 dias")

    return pts, reasons


def _adoption(row: dict) -> tuple[int, list[str]]:
    pts = 0
    reasons: list[str] = []

    barbers = int(row.get("barbers_count") or 0)
    if barbers >= 2:
        pts += 8
    elif barbers == 1:
        pts += 5
    else:
        reasons.append("nenhum profissional cadastrado")

    clients = int(row.get("clients_count") or 0)
    if clients >= 50:
        pts += 12
    elif clients >= 10:
        pts += 8
    elif clients >= 1:
        pts += 4
        reasons.append(f"base pequena: {clients} cliente(s)")
    else:
        reasons.append("nenhum cliente cadastrado")

    users = int(row.get("users_count") or 0)
    if users >= 2:
        pts += 5
    elif users == 1:
        pts += 2

    return pts, reasons


def _billing(row: dict, status: str) -> tuple[int, list[str]]:
    base = {
        "active": 30,
        "trial": 22,
        "past_due": 12,
        "sem_assinatura": 5,
        "canceled": 0,
    }.get(status, 5)
    reasons: list[str] = []

    if status == "trial":
        reasons.append("em trial — ainda não converteu")
    elif status == "canceled":
        reasons.append("assinatura cancelada")
    elif status == "past_due":
        reasons.append("assinatura inadimplente")
    elif status == "sem_assinatura":
        reasons.append("sem assinatura vigente")

    overdue = int(row.get("days_overdue") or 0)
    if overdue > 0:
        base = max(base - min(2 * overdue, base), 0)
        amount = float(row.get("open_amount") or 0)
        reasons.append(
            f"pagamento em atraso há {overdue} dia(s)"
            + (f" (R$ {amount:.2f} em aberto)" if amount else "")
        )

    return base, reasons


def compute_health(row: dict, *, now: Optional[datetime] = None) -> dict:
    """Calcula {score, band, reasons} para uma org.

    `row` = linha de `app_platform_org_overview` + (opcionais) `days_overdue`
    e `open_amount` do dunning + `status` derivado (`_derive_status`).
    """
    now = now or datetime.now(timezone.utc)
    status = row.get("status") or "sem_assinatura"

    if row.get("deleted_at") is not None or status == "suspended":
        return {"score": 0, "band": BAND_SUSPENDED, "reasons": ["conta suspensa"]}

    eng_pts, eng_reasons = _engagement(row, now)
    ado_pts, ado_reasons = _adoption(row)
    bil_pts, bil_reasons = _billing(row, status)
    score = eng_pts + ado_pts + bil_pts
    reasons = bil_reasons + eng_reasons + ado_reasons

    age = _days_since(row.get("created_at"), now)
    is_new = age is not None and age < GRACE_DAYS

    if score >= 70:
        band = BAND_HEALTHY
    elif score >= 40 or is_new:
        band = BAND_WATCH
        if is_new and score < 40:
            reasons.insert(0, f"conta nova ({age} dia(s)) — carência de avaliação")
    else:
        band = BAND_AT_RISK

    return {"score": score, "band": band, "reasons": reasons}
