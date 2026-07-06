"""Remove os débitos (`client_debts`) de um org — por padrão os importados da Trinks.

Contexto: o export "Débitos de clientes" da Trinks foi identificado como fonte
INVÁLIDA e descartado do escopo. Como `client_debts` é uma **tabela-folha**
(nenhuma outra tabela referencia ela; `client_id` aponta para `clients` e é
opcional), apagar os débitos NÃO cascateia para clientes/pagamentos/agenda.
Não existe rota de DELETE no app (só listar/somar/pagar/reabrir) — por isso este
script.

Segurança (mesmo molde do `reset_org.py`):
- Roda como `barber_app` com `set_current_org` → **RLS auto-escopa no org** + filtro
  `WHERE organization_id` explícito.
- **Dry-run por padrão**: só conta (por source/status). Precisa de `--commit`.
- Com `--commit`, exige `--confirm-name "<nome exato do org>"` (o dry-run imprime o
  nome exato do org — use-o).
- Escopo: apaga só `source = :source` (default 'trinks'); `--source all` ignora a origem.
- Tudo numa transação: qualquer erro faz rollback.

⚠️ FAÇA BACKUP ANTES (pg_dump) — ver docs/TRINKS_IMPORT.md.

Uso (na VM):
    python scripts/delete_org_debts.py --org-id 1                       # dry-run
    python scripts/delete_org_debts.py --org-id 1 --commit --confirm-name "<nome do org>"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402


def _scope(org_id: int, source: str) -> tuple[str, dict]:
    """Predicado de escopo + params. `source == 'all'` apaga de qualquer origem."""
    if source == "all":
        return "organization_id = :org", {"org": org_id}
    return "organization_id = :org AND source = :source", {"org": org_id, "source": source}


async def _org_name(session, org_id: int) -> str | None:
    r = await session.execute(
        text("SELECT name FROM organizations WHERE id = :id"), {"id": org_id}
    )
    row = r.first()
    return row[0] if row else None


async def _breakdown(session, where: str, params: dict) -> list[tuple[str, str, int, str]]:
    r = await session.execute(
        text(
            "SELECT source, status, count(*) AS n, "
            "COALESCE(sum(amount), 0)::text AS total "
            f"FROM client_debts WHERE {where} "
            "GROUP BY source, status ORDER BY source, status"
        ),
        params,
    )
    return [(row[0], row[1], int(row[2]), row[3]) for row in r.all()]


async def _run(org_id: int, source: str, commit: bool, confirm_name: str | None) -> int:
    where, params = _scope(org_id, source)
    async with AsyncSessionLocal() as session:
        await set_current_org(session, org_id)

        name = await _org_name(session, org_id)
        if name is None:
            print(f"Org {org_id} não encontrada (ou sem acesso).")
            return 1
        print(f"Org {org_id}: {name!r}  |  source={source!r}")

        rows = await _breakdown(session, where, params)
        total = sum(n for _, _, n, _ in rows)
        print("\n== Débitos a apagar (source / status) ==")
        if not rows:
            print("  (nenhum)")
        for src, status, n, amount in rows:
            print(f"  {src:8} {status:8} {n:6}  R$ {amount}")
        print(f"  {'TOTAL':18} {total}")

        if not commit:
            print("\nDRY-RUN: nada foi apagado. Use --commit --confirm-name para aplicar.")
            return 0

        if (confirm_name or "").strip().lower() != name.strip().lower():
            print(
                f"\nABORTADO: --confirm-name não confere com o nome do org ({name!r}). "
                "Nada foi apagado."
            )
            return 2

        result = await session.execute(
            text(f"DELETE FROM client_debts WHERE {where}"), params
        )
        await session.commit()
        print(f"\n✅ {result.rowcount} débito(s) apagado(s) do org {org_id} ({name!r}).")
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Remove os débitos (client_debts) de um org — por padrão os de source='trinks'."
    )
    ap.add_argument("--org-id", type=int, required=True)
    ap.add_argument(
        "--source",
        default="trinks",
        help="Filtra por origem (default: trinks). Use 'all' para apagar de qualquer origem.",
    )
    ap.add_argument("--commit", action="store_true", help="Aplica (sem isso é dry-run).")
    ap.add_argument("--confirm-name", help="Nome EXATO do org (obrigatório com --commit).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.org_id, args.source, args.commit, args.confirm_name)))


if __name__ == "__main__":
    main()
