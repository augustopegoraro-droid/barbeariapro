"""Enriquece clientes (email/nascimento) a partir do ranking exportado da Trinks.

Roda NA VM (RLS via barber_app). Casa por telefone e preenche só lacunas.

Uso:
    python scripts/enrich_trinks_ranking.py --org-id 1 --file <arquivo>            # dry-run
    python scripts/enrich_trinks_ranking.py --org-id 1 --file <arquivo> --commit   # aplica

⚠️ Arquivo contém PII — nunca versionar.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402
from app.services.trinks_ranking import enrich_clients, parse_ranking  # noqa: E402


def _print(title: str, data: dict) -> None:
    print(f"\n== {title} ==")
    for k, v in data.items():
        print(f"  {k:16} {v}")


async def _run(org_id: int, file: str, commit: bool) -> int:
    rows, parse_report = parse_ranking(file)
    _print("Parsing", parse_report.as_dict())
    if not rows:
        print("\nNenhuma linha de ranking parseável. Verifique o arquivo/cabeçalho.")
        return 1
    async with AsyncSessionLocal() as session:
        await set_current_org(session, org_id)
        rep = await enrich_clients(session, org_id, rows, dry_run=not commit)
        if commit:
            await session.commit()
    _print(f"Enriquecimento (org {org_id}, {'COMMIT' if commit else 'DRY-RUN'})", rep.as_dict())
    if not commit:
        print("\nDRY-RUN: nada foi gravado. Rode com --commit para aplicar.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Enriquece clientes pelo ranking da Trinks.")
    ap.add_argument("--org-id", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.org_id, args.file, args.commit)))


if __name__ == "__main__":
    main()
