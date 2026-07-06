"""Importa o DRE (Demonstrativo de Resultado) mensal da Trinks → `dre_monthly_lines`.

O relatório costuma vir dividido em vários arquivos (um por ano, p/ driblar o
timeout do export). Como o importador é idempotente por **substituição dos meses**
cobertos, pode-se passar todos os arquivos de uma vez (meses disjuntos → cada um
substitui só os seus). Roda **na VM** (5432 fechada). Dry-run por padrão.

Cada arquivo tem um `parse.checksum_ok`: confirma que a soma recomputada das
linhas-folha bate com os totais declarados no próprio arquivo — se vier `False`,
revise antes de aplicar.

⚠️ Arquivo cru é financeiro sensível — nunca versionar. FAÇA BACKUP (pg_dump) antes
de --commit. Ver docs/TRINKS_IMPORT.md.

Uso (na VM):
    python scripts/import_trinks_dre.py --org-id 1 --file DRE_10:25_07:26.csv          # dry-run
    python scripts/import_trinks_dre.py --org-id 1 --file DRE_*.csv --commit           # aplica (todos)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402
from app.services.trinks_dre import import_dre, parse_dre  # noqa: E402


def _print(title: str, d: dict) -> None:
    print(f"\n== {title} ==")
    for k, v in d.items():
        print(f"  {k}: {v}")


async def _run(org_id: int, files: list[str], commit: bool) -> None:
    all_rows = []
    checksum_ok = True
    for f in files:
        rows, parse_report = parse_dre(f)
        _print(f"Parse — {os.path.basename(f)}", parse_report.as_dict())
        checksum_ok = checksum_ok and not parse_report.checksum_mismatches
        all_rows.extend(rows)

    if not checksum_ok:
        print(
            "\n⚠️  ATENÇÃO: algum arquivo tem checksum_ok=False (soma recomputada != "
            "totais do arquivo). Revise o parse antes de --commit."
        )

    async with AsyncSessionLocal() as session:
        await set_current_org(session, org_id)
        report = await import_dre(session, org_id, all_rows, dry_run=not commit)
        if commit:
            await session.commit()

    _print("Import (todos os arquivos)", report.as_dict())
    if not commit:
        print("\nDRY-RUN: nada gravado. Use --commit para aplicar.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Importa o DRE mensal da Trinks para dre_monthly_lines."
    )
    ap.add_argument("--org-id", type=int, required=True)
    ap.add_argument(
        "--file",
        nargs="+",
        required=True,
        help="Um ou mais CSVs do DRE (meses disjuntos).",
    )
    ap.add_argument("--commit", action="store_true", help="Aplica (sem isso é dry-run).")
    args = ap.parse_args()
    asyncio.run(_run(args.org_id, args.file, args.commit))


if __name__ == "__main__":
    main()
