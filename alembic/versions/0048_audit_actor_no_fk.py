"""Auditoria: soltar o FK de `actor_user_id` (o banco reescrevia a trilha) — D-86.

Achado da rotina de verificação criada nesta mesma decisão: a cadeia de hash da
0039 cobre `actor_user_id`, mas a coluna tinha
`FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL`. Apagar um
usuário fazia o **próprio banco** zerar o campo em todas as linhas antigas dele
— uma tabela declarada append-only sendo reescrita por ação referencial. O hash
gravado deixava de bater e a trilha ficava "adulterada" sem que ninguém a
tivesse adulterado. No staging: 138 linhas nesse estado.

Trilha de auditoria não deve ter integridade referencial com a entidade que
audita — o id do ator é um **fato histórico**, não uma referência viva; ele
precisa sobreviver ao usuário. O `LEFT JOIN users` que a tela usa para mostrar
o e-mail continua funcionando enquanto o usuário existir, e devolve NULL depois
(era exatamente o que o SET NULL produzia, só que agora sem destruir o dado).

As linhas já zeradas não têm como ser recuperadas — a verificação vai apontá-las.
Ver DECISIONS D-86.

Revision ID: 0048_audit_actor_no_fk
Revises: 0047_session_retention
"""

from alembic import op

revision = "0048_audit_actor_no_fk"
down_revision = "0047_session_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `idx_audit_logs_org_actor` (0039) já cobre a busca por ator — nada a criar.
    op.execute(
        "ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_actor_user_id_fkey"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_actor_user_id_fkey "
        "FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL"
    )
