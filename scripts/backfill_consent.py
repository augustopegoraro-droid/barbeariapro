"""Registra a base legal dos clientes que entraram na base sem consentimento (D-86).

Contexto: a carga histórica da Trinks trouxe 2.911 titulares para a org 1
(D-56) e o cadastro pelo painel nunca gravou consentimento até o D-86 — nenhum
deles tem linha em `client_consents`/`consent_records`. Na prática eles são
alvo de lembrete e reativação sem que exista registro de por que podemos
contatá-los. Este script fecha a lacuna registrando o que de fato aconteceu:
relacionamento pré-existente migrado de outra ferramenta.

Isto **não fabrica consentimento**. `--status opt_in` (default) declara a base
legal de execução de contrato/relacionamento anterior, que é o caso real da
migração; use `--status opt_out` se o dono preferir silenciar a base histórica
até haver aceite explícito — a decisão é dele, o script honra as duas.

Segurança (molde `delete_org_debts.py`/`reset_org.py`):
- roda como `barber_app` com `set_current_org` → RLS escopa no org, mais filtro
  explícito por `organization_id`;
- **dry-run por padrão** (só conta); `--commit` exige `--confirm-name`;
- idempotente: só toca em cliente que **não tem nenhuma** linha em
  `client_consents` — rodar duas vezes não duplica nem sobrescreve quem já
  tinha estado (inclusive quem pediu opt-out).

Uso (na VM):
    python scripts/backfill_consent.py --org-id 1
    python scripts/backfill_consent.py --org-id 1 --commit --confirm-name "<nome do org>"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.privacy import SOURCE_TRINKS_IMPORT  # noqa: E402
from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402

# Clientes sem NENHUM consentimento registrado, em qualquer canal.
_TARGETS = """
    SELECT c.id
      FROM clients c
     WHERE c.organization_id = :org
       AND c.deleted_at IS NULL
       AND c.anonymized_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM client_consents cc WHERE cc.client_id = c.id
       )
"""


async def _org_name(session, org_id: int) -> str | None:
    row = (
        await session.execute(
            text("SELECT name FROM organizations WHERE id = :id"), {"id": org_id}
        )
    ).first()
    return row[0] if row else None


async def run(org_id: int, status: str, source: str, commit: bool, confirm_name: str | None) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)

            name = await _org_name(session, org_id)
            if name is None:
                print(f"Org {org_id} não encontrada (ou invisível para o role).")
                return 1
            ids = (await session.execute(text(_TARGETS), {"org": org_id})).scalars().all()
            print(f"Org {org_id} — {name}")
            print(f"Clientes sem consentimento registrado: {len(ids)}")
            print(f"Ação: gravar '{status}' no canal whatsapp, origem '{source}'")

            if not commit:
                print("\n(dry-run — nada gravado; use --commit --confirm-name para aplicar)")
                return 0
            if confirm_name != name:
                print(f"\n--confirm-name não confere. Esperado exatamente: {name!r}")
                return 1
            if not ids:
                print("Nada a fazer.")
                return 0

            params = {"org": org_id, "status": status, "source": source}
            await session.execute(
                text(
                    "INSERT INTO client_consents (client_id, channel, status, source) "
                    "SELECT c.id, 'whatsapp'::contact_channel, :status::consent_status, :source "
                    f"FROM ({_TARGETS}) AS c"
                ),
                params,
            )
            await session.execute(
                text(
                    "INSERT INTO consent_records "
                    "(organization_id, subject_type, subject_id, channel, status, "
                    " policy_version, source) "
                    "SELECT :org, 'client', c.id, 'whatsapp', :status, NULL, :source "
                    f"FROM ({_TARGETS}) AS c"
                ),
                params,
            )
            print(f"\n{len(ids)} cliente(s) com base legal registrada.")
            return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill de consentimento (LGPD, D-86).")
    p.add_argument("--org-id", type=int, required=True)
    p.add_argument(
        "--status",
        choices=("opt_in", "opt_out"),
        default="opt_in",
        help="opt_in = relacionamento pré-existente migrado (default); "
             "opt_out = silencia a base histórica até haver aceite explícito.",
    )
    p.add_argument("--source", default=SOURCE_TRINKS_IMPORT)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--confirm-name", dest="confirm_name")
    args = p.parse_args()
    return asyncio.run(
        run(args.org_id, args.status, args.source, args.commit, args.confirm_name)
    )


if __name__ == "__main__":
    raise SystemExit(main())
