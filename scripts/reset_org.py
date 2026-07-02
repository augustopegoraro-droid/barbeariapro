"""Reset dos DADOS OPERACIONAIS (fictícios) de um org — antes de importar a base real.

Apaga clientes/agendamentos/financeiro/CRM/fidelidade/assinaturas-de-cliente do org,
**preservando a configuração estrutural**: org, unidade, horários, usuários,
profissionais (barbers) + vínculos, serviços, catálogos (planos de mensalidade,
tiers de fidelidade, categorias de despesa), a assinatura do org com a plataforma
(`plans`/`subscriptions`) e as integrações (`integration_accounts` — WhatsApp/Google).

Segurança:
- Roda como `barber_app` com `set_current_org` → **RLS auto-escopa no org** (um erro
  não toca outras orgs) e ainda filtra `WHERE organization_id` explicitamente.
- **Dry-run por padrão**: só conta o que seria apagado. Precisa de `--commit`.
- Com `--commit`, exige `--confirm-name "<nome exato do org>"` (evita apagar o org errado).
- Tudo numa transação: qualquer erro faz rollback (nada é apagado pela metade).

⚠️ FAÇA BACKUP ANTES (pg_dump) — ver docs/TRINKS_IMPORT.md. O backup protege contra
um bug no próprio reset atingir o que você quer PRESERVAR.

Uso (na VM):
    python scripts/reset_org.py --org-id 1                       # dry-run
    python scripts/reset_org.py --org-id 1 --commit --confirm-name "Barbearia"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, set_current_org  # noqa: E402

# Ordem FK-safe (filhos antes dos pais). Só DADOS OPERACIONAIS/de cliente.
# Cada item: (tabela, predicado de escopo). A maioria tem `organization_id`; três
# tabelas (calendar_sync, appointment_items, client_consents) NÃO têm e são
# escopadas via subquery no pai — por isso vêm ANTES do pai ser apagado.
_ORG = "organization_id = :org"
_VIA_APPT = "appointment_id IN (SELECT id FROM appointments WHERE organization_id = :org)"
_VIA_CLIENT = "client_id IN (SELECT id FROM clients WHERE organization_id = :org)"

_DELETE_ORDER: list[tuple[str, str]] = [
    ("attachments", _ORG),
    ("messages", _ORG),
    ("conversations", _ORG),
    ("message_log", _ORG),
    ("calendar_sync", _VIA_APPT),
    ("lead_events", _ORG),
    ("leads", _ORG),
    ("membership_usages", _ORG),
    ("client_memberships", _ORG),
    ("membership_plan_items", _ORG),   # catálogo de mensalidade (itens antes do plano)
    ("membership_plans", _ORG),        # catálogo de mensalidade
    ("loyalty_point_ledger", _ORG),
    ("loyalty_vouchers", _ORG),
    ("client_loyalty", _ORG),
    ("loyalty_rules", _ORG),           # config de fidelidade (após dados do cliente)
    ("loyalty_tiers", _ORG),           # config de fidelidade
    ("payments", _ORG),
    ("expenses", _ORG),
    ("expense_categories", _ORG),      # categorias financeiras (após despesas)
    ("appointment_items", _VIA_APPT),
    ("appointments", _ORG),
    ("client_consents", _VIA_CLIENT),
    ("clients", _ORG),
]

# Explicitamente PRESERVADAS (não tocar): organizations, units, business_hours,
# users, user_units, barbers, barber_units, barber_services, time_off, services,
# plans, subscriptions, integration_accounts.
# (Catálogos — membership_plans/items, loyalty_tiers/rules, expense_categories —
#  são apagados a pedido: dados fictícios que o gestor vai recriar.)


async def _counts(session, org_id: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for t, where in _DELETE_ORDER:
        r = await session.execute(
            text(f"SELECT count(*) FROM {t} WHERE {where}"), {"org": org_id}
        )
        out[t] = r.scalar_one()
    return out


async def _org_name(session, org_id: int) -> str | None:
    r = await session.execute(
        text("SELECT name FROM organizations WHERE id = :id"), {"id": org_id}
    )
    row = r.first()
    return row[0] if row else None


async def _run(org_id: int, commit: bool, confirm_name: str | None) -> int:
    async with AsyncSessionLocal() as session:
        await set_current_org(session, org_id)

        name = await _org_name(session, org_id)
        if name is None:
            print(f"Org {org_id} não encontrada (ou sem acesso).")
            return 1
        print(f"Org {org_id}: {name!r}")

        counts = await _counts(session, org_id)
        total = sum(counts.values())
        print("\n== Linhas a apagar (por tabela) ==")
        for t, n in counts.items():
            if n:
                print(f"  {t:22} {n}")
        print(f"  {'TOTAL':22} {total}")

        if not commit:
            print("\nDRY-RUN: nada foi apagado. Use --commit --confirm-name para aplicar.")
            return 0

        if (confirm_name or "").strip().lower() != name.strip().lower():
            print(
                f"\nABORTADO: --confirm-name não confere com o nome do org ({name!r}). "
                "Nada foi apagado."
            )
            return 2

        for t, where in _DELETE_ORDER:
            await session.execute(
                text(f"DELETE FROM {t} WHERE {where}"), {"org": org_id}
            )
        await session.commit()
        print(f"\n✅ Reset concluído: {total} linhas apagadas do org {org_id} ({name!r}).")
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Reset dos dados operacionais (fictícios) de um org."
    )
    ap.add_argument("--org-id", type=int, required=True)
    ap.add_argument("--commit", action="store_true", help="Aplica (sem isso é dry-run).")
    ap.add_argument("--confirm-name", help="Nome EXATO do org (obrigatório com --commit).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.org_id, args.commit, args.confirm_name)))


if __name__ == "__main__":
    main()
