"""equipe: modelo de trabalho + custo fixo mensal + aluguel de cadeira

Revision ID: 0025_barber_work_model
Revises: 0024_reschedule_requests
Create Date: 2026-07-02

Gestão inteligente de equipe (doc `gestaointeligente/`): para responder "a receita
recorrente cobre a folha?" e "cabe contratar?", o sistema precisa saber quanto cada
profissional CUSTA por mês e em qual modelo trabalha. Tudo ADITIVO:

- `barbers.work_model` — 'clt' | 'mei' | 'comissionado' | 'aluguel_cadeira' |
  'hibrido'. NULL = não configurado (tratado como 'comissionado', o comportamento
  histórico: só comissão, sem custo fixo).
- `barbers.monthly_cost` — custo fixo mensal TOTAL para a empresa (salário +
  encargos no CLT; valor fixo no MEI/híbrido). 0 para comissão pura.
- `barbers.chair_rent` — aluguel de cadeira que o profissional PAGA à empresa por
  mês (receita, abate o custo líquido da equipe). 0 quando não se aplica.

A comissão variável continua em `commission_pct` (inalterada).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0025_barber_work_model"
down_revision = "0024_reschedule_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("barbers", sa.Column("work_model", sa.Text(), nullable=True))
    op.add_column(
        "barbers",
        sa.Column("monthly_cost", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "barbers",
        sa.Column("chair_rent", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "barbers_work_model_valid",
        "barbers",
        "work_model IS NULL OR work_model IN "
        "('clt', 'mei', 'comissionado', 'aluguel_cadeira', 'hibrido')",
    )


def downgrade() -> None:
    op.drop_constraint("barbers_work_model_valid", "barbers", type_="check")
    op.drop_column("barbers", "chair_rent")
    op.drop_column("barbers", "monthly_cost")
    op.drop_column("barbers", "work_model")
