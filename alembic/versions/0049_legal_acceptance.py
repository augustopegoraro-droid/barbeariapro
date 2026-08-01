"""Aceite de documentos: termo do funcionário e contrato de operador (DPA) — D-87.

Fecha a lacuna que sobrou do D-86: aquele fechou a entrada do **cliente final**;
quem opera o sistema continuava entrando sem aceitar nada.

Dois documentos, dois públicos, duas naturezas jurídicas diferentes:

- **Termo de uso e confidencialidade** (`users.terms_*`): quem loga no painel
  acessa PII de milhares de titulares. A base legal do tratamento dos dados
  *dele* é a relação de trabalho — não é consentimento —, então isto não é
  "consentimento do funcionário": é o registro de que ele foi informado do dever
  de sigilo e do uso monitorado. É a defesa da barbearia se um funcionário
  vazar a base.
- **Contrato de operador / DPA** (`organizations.dpa_*`): a plataforma é
  **operadora** dos dados dos clientes finais de cada barbearia (LGPD art. 39),
  e operador precisa tratar os dados conforme instruções **documentadas** do
  controlador. Hoje uma org nasce por `POST /platform/orgs` (D-55) e começa a
  operar sem contrato nenhum — em um incidente, a responsabilidade fica
  indefinida. O aceite é da ORG (por isso a coluna vive em `organizations`),
  mas guarda quem clicou.

Estado aqui, histórico em `consent_records` (`subject_type='user'`), no mesmo
desenho do D-86: a coluna decide o gate, a linha append-only é a prova.

`..._version_accepted` guarda a **versão aceita**, não um booleano: publicar
texto novo (subindo `TERMS_VERSION`/`DPA_VERSION` em `app/core/privacy.py`)
reabre o aceite sozinho, sem migration nova.

Aditiva: colunas nullable, nada a preencher. Todo mundo nasce pendente.

Revision ID: 0049_legal_acceptance
Revises: 0048_audit_actor_no_fk
"""

from alembic import op
import sqlalchemy as sa

revision = "0049_legal_acceptance"
down_revision = "0048_audit_actor_no_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_version_accepted", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations", sa.Column("dpa_version_accepted", sa.Text(), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column("dpa_accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Sem FK para `users` de propósito (mesma razão da 0048): é registro de um
    # fato jurídico e precisa sobreviver ao usuário que clicou.
    op.add_column(
        "organizations", sa.Column("dpa_accepted_by_user_id", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("organizations", "dpa_accepted_by_user_id")
    op.drop_column("organizations", "dpa_accepted_at")
    op.drop_column("organizations", "dpa_version_accepted")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_version_accepted")
