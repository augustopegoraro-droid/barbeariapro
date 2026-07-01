"""Importa clientes de um export da Trinks para um org (tenant).

Roda NA VM (o Postgres não é acessível de fora — firewall). Usa a role `barber_app`
(RLS): escopa a sessão no org via `set_current_org` e insere só clientes daquele org.

Uso:
    # 1) DRY-RUN (padrão): não escreve nada, só mostra o relatório
    python scripts/import_trinks.py --org-id 1 --file TrinksInformations/ClientesT\\&T.csv

    # 2) Import real (grava e commita)
    python scripts/import_trinks.py --org-id 1 --file <arquivo> --commit

Relatório: total de linhas, importáveis, sem nome/telefone, telefone inválido,
duplicados no arquivo, com e-mail/nascimento; e, na persistência, inseridos vs.
já existentes (dedup por telefone contra o org).

⚠️ O arquivo de entrada contém PII (LGPD) — nunca versionar (ver .gitignore).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402
from app.services.trinks_import import (  # noqa: E402
    import_clients,
    parse_clients,
)


def _print_report(title: str, data: dict) -> None:
    print(f"\n== {title} ==")
    for k, v in data.items():
        print(f"  {k:20} {v}")


async def _run(org_id: int, file: str, commit: bool) -> int:
    records, parse_report = parse_clients(file)
    _print_report("Parsing", parse_report.as_dict())
    if not records:
        print("\nNenhum cliente importável. Verifique o arquivo/cabeçalho.")
        return 1

    async with AsyncSessionLocal() as session:
        await set_current_org(session, org_id)
        import_report = await import_clients(
            session, org_id, records, dry_run=not commit
        )
        if commit:
            await session.commit()
    _print_report(
        f"Persistência (org {org_id}, {'COMMIT' if commit else 'DRY-RUN'})",
        import_report.as_dict(),
    )
    if not commit:
        print("\nDRY-RUN: nada foi gravado. Rode com --commit para aplicar.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Importa clientes da Trinks para um org.")
    ap.add_argument("--org-id", type=int, required=True, help="ID do org (tenant) alvo")
    ap.add_argument("--file", required=True, help="CSV de clientes exportado da Trinks")
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Grava de verdade (sem esta flag é dry-run).",
    )
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.org_id, args.file, args.commit)))


if __name__ == "__main__":
    main()
