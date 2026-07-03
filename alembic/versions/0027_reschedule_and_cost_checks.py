"""CHECKs de integridade: custos da equipe ≥ 0, source e período da remarcação

Revision ID: 0027_reschedule_and_cost_checks
Revises: 0026_cash_daily_closings
Create Date: 2026-07-03

Correções de code review das migrations 0024/0025 (já em prod → imutáveis; esta é
aditiva, só constraints). Tudo passa nos dados existentes (custos default 0 / API
≥0; source ∈ {app,kernel_ia}; períodos NULL ou válidos):

- `barbers_monthly_cost_nonneg` / `barbers_chair_rent_nonneg` — dinheiro nunca
  negativo (mesma defesa do `barbers_commission_range`); protege o cálculo de
  folha/cobertura (`management.recurring_coverage`) contra writers fora da API
  (imports, scripts, futuro) — a API já garante `ge=0`, o DB é o backstop.
- `reschedule_source_valid` — paridade com o CHECK de `status` (0024 só constrangeu
  `status`); só 'app'/'kernel_ia' são escritos.
- `reschedule_period_order` — se ambos os limites vêm preenchidos, `period_end`
  tem de ser depois de `period_start` (`>` estrito, igual a TimeOff/Appointment/
  Membership). Tolerante a NULL: pedidos do Kernel IA não trazem período.

NB: os mesmos CHECKs estão espelhados no ORM (`models/barber.py`,
`models/appointment_reschedule.py`) — convenção do repo (modelo + migration).
"""
from __future__ import annotations

from alembic import op

revision = "0027_reschedule_and_cost_checks"
down_revision = "0026_cash_daily_closings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # F7 — custos da equipe nunca negativos
    op.create_check_constraint(
        "barbers_monthly_cost_nonneg", "barbers", "monthly_cost >= 0"
    )
    op.create_check_constraint(
        "barbers_chair_rent_nonneg", "barbers", "chair_rent >= 0"
    )
    # F3 — origem do pedido restrita ao catálogo fechado
    op.create_check_constraint(
        "reschedule_source_valid",
        "appointment_reschedule_requests",
        "source IN ('app', 'kernel_ia')",
    )
    # F1 — ordem do período (tolerante a NULL nos dois lados)
    op.create_check_constraint(
        "reschedule_period_order",
        "appointment_reschedule_requests",
        "period_start IS NULL OR period_end IS NULL OR period_end > period_start",
    )


def downgrade() -> None:
    op.drop_constraint(
        "reschedule_period_order", "appointment_reschedule_requests", type_="check"
    )
    op.drop_constraint(
        "reschedule_source_valid", "appointment_reschedule_requests", type_="check"
    )
    op.drop_constraint("barbers_chair_rent_nonneg", "barbers", type_="check")
    op.drop_constraint("barbers_monthly_cost_nonneg", "barbers", type_="check")
