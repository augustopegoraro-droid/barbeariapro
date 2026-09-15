"""Bandeira/tipo de cartão + fundação do split de pagamento.

Aditivo, não quebra nada:
- Novos enums `card_type` (credito/debito) e `card_brand` (visa/mastercard/
  elo/amex/hipercard/outro).
- `payment_method` ganha o valor `credito_cliente` (pagamento com saldo da
  carteira do cliente, migration 0068) — `ADD VALUE` fora de transação com
  uso, sem risco (nenhum INSERT desta migration usa o valor novo).
- `payments`/`sale_payments` ganham `card_type`/`card_brand` (nullable, só
  preenchidos quando `method = 'cartao'`, CHECK espelhado no ORM). Sem tabela
  nova: `payments.appointment_id` nunca teve `UniqueConstraint` — múltiplas
  linhas de `Payment` por atendimento (split) já são estruturalmente livres,
  só o código (fora desta migration) passa a inserir N linhas em vez de 1.

Revision ID: 0067_payment_card_split
Revises: 0066_membership_addons
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0067_payment_card_split"
down_revision = "0066_membership_addons"
branch_labels = None
depends_on = None

_CARD_TYPES = ("credito", "debito")
_CARD_BRANDS = ("visa", "mastercard", "elo", "amex", "hipercard", "outro")

_CARD_CHECK_SQL = "method = 'cartao' OR (card_type IS NULL AND card_brand IS NULL)"


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_CARD_TYPES, name="card_type").create(bind, checkfirst=False)
    postgresql.ENUM(*_CARD_BRANDS, name="card_brand").create(bind, checkfirst=False)

    # PG >= 12 aceita ADD VALUE em transação, desde que o valor novo não seja
    # usado na mesma transação (não é: nenhum INSERT aqui usa 'credito_cliente').
    op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'credito_cliente'")

    for table in ("payments", "sale_payments"):
        op.add_column(
            table,
            sa.Column(
                "card_type",
                postgresql.ENUM(*_CARD_TYPES, name="card_type", create_type=False),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "card_brand",
                postgresql.ENUM(*_CARD_BRANDS, name="card_brand", create_type=False),
                nullable=True,
            ),
        )
        op.create_check_constraint(
            f"{table}_card_fields_only_when_cartao", table, _CARD_CHECK_SQL
        )


def downgrade() -> None:
    for table in ("payments", "sale_payments"):
        op.drop_constraint(f"{table}_card_fields_only_when_cartao", table, type_="check")
        op.drop_column(table, "card_brand")
        op.drop_column(table, "card_type")

    # 'credito_cliente' não é removido de payment_method — PG não suporta
    # DROP VALUE em enum; downgrade aceita o resíduo (mesma lógica de outras
    # migrations do projeto que ADD VALUE, ex. 0044/0052).
    op.execute("DROP TYPE IF EXISTS card_brand")
    op.execute("DROP TYPE IF EXISTS card_type")
