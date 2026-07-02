"""Importa DÉBITOS (contas a receber) de um export da Trinks para um org.

Roda NA VM (RLS via barber_app). Casa cliente por nome; idempotente (não duplica).

Uso:
    python scripts/import_trinks_debts.py --org-id 1 --file <arquivo>            # dry-run
    python scripts/import_trinks_debts.py --org-id 1 --file <arquivo> --commit   # aplica

⚠️ Arquivo contém PII — nunca versionar.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402
from app.services.trinks_debts import import_debts, parse_debts  # noqa: E402


def _print(title: str, data: dict) -> None:
    print(f"\n== {title} ==")
    for k, v in data.items():
        print(f"  {k:18} {v}")


async def _run(org_id: int, file: str, commit: bool) -> int:
    rows, parse_report = parse_debts(file)
    _print("Parsing", parse_report.as_dict())
    if not rows:
        print("\nNenhum débito parseável. Verifique o arquivo/cabeçalho.")
        return 1
    async with AsyncSessionLocal() as session:
        await set_current_org(session, org_id)
        rep = await import_debts(session, org_id, rows, dry_run=not commit)
        if commit:
            await session.commit()
    _print(f"Importação (org {org_id}, {'COMMIT' if commit else 'DRY-RUN'})", rep.as_dict())
    if not commit:
        print("\nDRY-RUN: nada foi gravado. Rode com --commit para aplicar.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Importa débitos da Trinks.")
    ap.add_argument("--org-id", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.org_id, args.file, args.commit)))


if __name__ == "__main__":
    main()
