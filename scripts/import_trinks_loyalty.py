"""Semeia a FIDELIDADE (client_loyalty) a partir do ranking da Trinks para um org.

Roda NA VM (Postgres fechado ao mundo). Usa `barber_app` (RLS) com `set_current_org`.
Casa cada linha do ranking por telefone com um cliente existente e grava última visita,
contadores e status (ativo/em risco/inativo), além de creditar os PONTOS históricos no
ledger (idempotente — re-rodar não duplica). É o bootstrap que destrava a reativação.

Uso:
    python scripts/import_trinks_loyalty.py --org-id 1 --file <arquivo>            # dry-run
    python scripts/import_trinks_loyalty.py --org-id 1 --file <arquivo> --commit   # aplica

⚠️ Arquivo de entrada contém PII — nunca versionar (ver .gitignore).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402
from app.services.trinks_ranking import (  # noqa: E402
    parse_ranking,
    sync_loyalty_from_ranking,
)


def _print(title: str, data: dict) -> None:
    print(f"\n== {title} ==")
    for k, v in data.items():
        print(f"  {k:24} {v}")


async def _run(org_id: int, file: str, commit: bool) -> int:
    rows, parse_report = parse_ranking(file)
    _print("Parsing", parse_report.as_dict())
    if not rows:
        print("\nNenhuma linha parseável. Verifique o arquivo/cabeçalho.")
        return 1

    async with AsyncSessionLocal() as session:
        await set_current_org(session, org_id)
        rep = await sync_loyalty_from_ranking(session, org_id, rows, dry_run=not commit)
        if commit:
            await session.commit()
    _print(f"Fidelidade (org {org_id}, {'COMMIT' if commit else 'DRY-RUN'})", rep.as_dict())
    if not commit:
        print("\nDRY-RUN: nada foi gravado. Rode com --commit para aplicar.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Semeia a fidelidade a partir do ranking da Trinks.")
    ap.add_argument("--org-id", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--commit", action="store_true", help="Grava (sem isso é dry-run).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.org_id, args.file, args.commit)))


if __name__ == "__main__":
    main()
