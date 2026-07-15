"""RLS em appointment_items/webhook_events (V17/V18a, Fase 9)

Revision ID: 0043_rls_hardening_v17_v18
Revises: 0042_consent_records
Create Date: 2026-07-14

Fecha um achado residual completo e metade de outro, da auditoria original
(`AUDITORIA_SEGURANCA.md`), confirmados ainda abertos na revisão final da
Fase 9 (`FASE9_REVISAO_FINAL.md`):

- **V17** — `appointment_items` (contém `price_charged`, dado financeiro)
  isolava só por disciplina de JOIN via `appointment_id → appointments.
  organization_id`, sem RLS própria. Denormaliza `organization_id` (sempre
  igual ao da `Appointment` pai, setado nos 4 pontos de criação —
  `agenda.py`/`bot.py`/`membership.py`/`trinks_appointments.py`) e aplica o
  molde padrão (RLS + `FORCE`, mesmo grant que já existia).
- **V18a** — `webhook_events.organization_id` é **nullable** de propósito
  (evento chega antes da org ser resolvida, nunca passa por rota de tenant —
  ver comentário original em `0032_billing_domain.py`). RLS "global OU
  tenant" (molde `roles`/0037): linha sem org é visível a todos (não há
  como saber de quem é ainda), linha COM org só pra própria org — fecha o
  cenário "JWT de tenant lê webhook_events de outra org" sem quebrar a
  ingestão.
- **V18b (`coupons`) NÃO é tratado aqui** — tentativa revertida nesta mesma
  sessão: `coupons` é catálogo global (sem `organization_id`, RLS não se
  aplica) e o gap real é `barber_app` poder escrever nele — mas revogar
  `INSERT`/`UPDATE` quebrou o fluxo real de resgate de cupom
  (`platform_billing.py` incrementa `times_redeemed` usando a MESMA conexão
  `barber_app` de qualquer rota tenant; não existe um papel elevado
  separado para rotas de plataforma, diferente de `platform_admins`/
  `platform_audit_log` que são só via `SECURITY DEFINER`). Corrigir de
  verdade exige mover a escrita de cupom pra uma função `SECURITY DEFINER`
  (molde D-55) — fora do escopo desta migration; **V18b segue aberto**,
  registrado em `FASE9_REVISAO_FINAL.md`.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0043_rls_hardening_v17_v18"
down_revision = "0042_consent_records"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)
# NULLIF(...,'')  — não é só estilo: numa conexão pooled que já teve
# `set_current_org` chamado antes (comum, o pool é compartilhado), o valor
# LOCAL reverte para '' (string vazia), não NULL, quando a transação termina
# — e ''::bigint estoura "invalid input syntax for type bigint". Só
# `current_setting(..., true)` teria sido NULL numa conexão NUNCA usada
# antes; `NULLIF` cobre os dois casos. Achado real (não teórico): quebrou
# `webhook_events` sob a suíte completa (conexões reaproveitadas), nunca
# isolado (conexão nova a cada teste solo).
_NULL_OR_TENANT = (
    "organization_id IS NULL OR "
    "organization_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint"
)


def upgrade() -> None:
    # ── appointment_items (V17) ──────────────────────────────────────────────
    op.add_column(
        "appointment_items",
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE appointment_items ai
        SET organization_id = a.organization_id
        FROM appointments a
        WHERE ai.appointment_id = a.id
        """
    )
    op.alter_column("appointment_items", "organization_id", nullable=False)
    op.create_index("idx_appt_items_org", "appointment_items", ["organization_id"])
    op.execute("ALTER TABLE appointment_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON appointment_items "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE appointment_items FORCE ROW LEVEL SECURITY")

    # ── webhook_events (V18a) — RLS "global OU tenant" (org pode ser NULL) ──
    op.execute("ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON webhook_events "
        f"USING ({_NULL_OR_TENANT}) WITH CHECK ({_NULL_OR_TENANT})"
    )
    op.execute("ALTER TABLE webhook_events FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE webhook_events NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON webhook_events")
    op.execute("ALTER TABLE webhook_events DISABLE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE appointment_items NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON appointment_items")
    op.execute("ALTER TABLE appointment_items DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_appt_items_org", table_name="appointment_items")
    op.drop_column("appointment_items", "organization_id")
