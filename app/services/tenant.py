"""Resolução de tenant PRÉ-autenticação (multi-tenant real).

O `organization_id` deixou de ser hardcoded (`NEXT_PUBLIC_ORG_ID` no frontend,
`settings.bot_organization_id` no bot). Estas funções resolvem a org *antes* de
saber qual é o tenant:

- `org_id_by_subdomain` — login: o frontend resolve o subdomínio do host → org_id.
- `org_id_by_wa_instance` — bot: a org vem da instância Evolution que recebeu o
  webhook (decisão arquitetural: instância → org, não telefone → org, já que
  `phone_e164` não é único).
- `org_id_by_refresh_token_hash` — `POST /auth/refresh` (D-68): só recebe o
  refresh token, ainda não sabe a org.

`organizations` tem RLS por `app.current_org_id`; um SELECT sem tenant não vê
linha alguma. Por isso a consulta vai por funções `SECURITY DEFINER` criadas na
migration 0020 (`app_org_id_by_*`), que rodam como dono (ignoram a RLS) e
devolvem apenas o `id`. Use estas funções com uma sessão SEM tenant (`get_db`).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def org_id_by_subdomain(db: AsyncSession, subdomain: str) -> Optional[int]:
    """org_id do tenant cujo `subdomain` casa (case-insensitive), ou None.

    Não requer tenant na sessão (a função SQL ignora a RLS). `db` deve ser uma
    sessão pré-tenant (login usa `get_db`).
    """
    if not subdomain or not subdomain.strip():
        return None
    row = await db.execute(
        text("SELECT app_org_id_by_subdomain(:s)"),
        {"s": subdomain.strip().lower()},
    )
    return row.scalar_one_or_none()


async def org_id_by_wa_instance(db: AsyncSession, instance: str) -> Optional[int]:
    """org_id da barbearia cuja `wa_instance_name` casa com a instância do
    webhook, ou None se não houver mapeamento (caller decide o fallback)."""
    if not instance or not instance.strip():
        return None
    row = await db.execute(
        text("SELECT app_org_id_by_wa_instance(:i)"),
        {"i": instance.strip()},
    )
    return row.scalar_one_or_none()


async def org_id_by_refresh_token_hash(db: AsyncSession, token_hash: str) -> Optional[int]:
    """org_id da `sessions` (não revogada) cujo hash atual OU anterior casa.

    `db` deve ser uma sessão pré-tenant (`get_db`). Usado só para resolver a
    org antes de reabrir a consulta sob RLS normal (mesmo padrão de
    `org_id_by_subdomain`)."""
    if not token_hash:
        return None
    row = await db.execute(
        text("SELECT app_org_id_by_refresh_hash(:h)"),
        {"h": token_hash},
    )
    return row.scalar_one_or_none()
