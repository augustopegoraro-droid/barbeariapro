"""Auditoria: aceitar actor_kind='client' (site público) — D-86.

O D-79 passou a emitir eventos do site público com `actor_kind="client"`
(sessão criada, agendamento, cancelamento), mas a CHECK criada na 0039 só
admitia `user|bot|system`. Como `record_event` é fire-and-forget e engole a
exceção (`except Exception: log.exception`), **todo** evento do cliente final
falhava em silêncio — a trilha do site público nunca existiu de fato.

Aditivo: só troca a CHECK por uma mais larga. Nenhuma linha existente viola a
nova regra (o conjunto antigo está contido no novo).

Revision ID: 0046
Revises: 0045
"""

from alembic import op

revision = "0046_audit_actor_kind_client"
down_revision = "0045_barber_photo"
branch_labels = None
depends_on = None

_CONSTRAINT = "audit_logs_actor_kind_valid"


def upgrade() -> None:
    op.execute(f"ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE audit_logs ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (actor_kind IN ('user', 'bot', 'system', 'client'))"
    )


def downgrade() -> None:
    # Linhas com actor_kind='client' impediriam a CHECK antiga de ser recriada;
    # a tabela é append-only (sem GRANT de UPDATE/DELETE ao role da app), então
    # o downgrade roda como owner e as normaliza para 'system' antes.
    op.execute("UPDATE audit_logs SET actor_kind = 'system' WHERE actor_kind = 'client'")
    op.execute(f"ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE audit_logs ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (actor_kind IN ('user', 'bot', 'system'))"
    )
