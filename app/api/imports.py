"""Migração de dados vindos da Trinks — self-service do dono do tenant.

Facilita a entrada de clientes que usavam a Trinks: o dono/gerente faz upload dos
CSVs exportados e importa para a PRÓPRIA org (RLS pelo token). Reutiliza os serviços
`trinks_import`/`trinks_appointments` (mesmos parser/dedup/de-para validados no CLI).

Padrão de uso (preview → aplicar):
- `commit=false` (padrão): **dry-run** — devolve o relatório sem gravar nada.
- `commit=true`: grava (o `get_tenant_db` commita a transação no fim do request).

O corpo do request é o **arquivo bruto** (application/octet-stream / text/csv), lido via
`request.body()` — evita dependência de multipart. No frontend:
`fetch(url, { method: "POST", body: file })`.

Só gestor (owner/manager). ⚠️ CSVs contêm PII — não são persistidos em disco.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_manager_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.services.trinks_appointments import (
    import_appointments,
    parse_appointments,
)
from app.services.trinks_cash_closing import import_cash_closings, parse_cash_closings
from app.services.trinks_debts import import_debts, parse_debts
from app.services.trinks_import import import_clients, parse_clients
from app.services.trinks_ranking import enrich_clients, parse_ranking
from models import User

router = APIRouter(prefix="/admin/import/trinks", tags=["import"])

TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

# Limite defensivo do upload (o export de ~3,3k clientes tem ~1,5 MB).
_MAX_BYTES = 15 * 1024 * 1024


async def _guard(db: AsyncSession, user: User) -> None:
    require_manager_access(await resolve_current_role(db, user))


async def _read_body(request: Request) -> bytes:
    raw = await request.body()
    if not raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Corpo vazio: envie o arquivo CSV no body."
        )
    if len(raw) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo excede o limite (15 MB)."
        )
    return raw


@router.post("/clients")
async def import_trinks_clients(
    request: Request,
    db: TenantDB,
    current_user: CurrentUser,
    commit: Annotated[bool, Query(description="false=dry-run (padrão); true=grava")] = False,
) -> dict:
    """Importa clientes de um export de clientes da Trinks para a org do usuário."""
    await _guard(db, current_user)
    raw = await _read_body(request)
    records, parse_report = parse_clients(raw)
    report = await import_clients(
        db, current_user.organization_id, records, dry_run=not commit
    )
    return {
        "commit": commit,
        "parse": parse_report.as_dict(),
        "import": report.as_dict(),
    }


@router.post("/appointments")
async def import_trinks_appointments(
    request: Request,
    db: TenantDB,
    current_user: CurrentUser,
    commit: Annotated[bool, Query(description="false=dry-run (padrão); true=grava")] = False,
) -> dict:
    """Importa agendamentos de um export da Trinks (liga cliente/profissional/serviço)."""
    await _guard(db, current_user)
    raw = await _read_body(request)
    records, parse_report = parse_appointments(raw)
    report = await import_appointments(
        db, current_user.organization_id, records, dry_run=not commit
    )
    return {
        "commit": commit,
        "parse": parse_report.as_dict(),
        "import": report.as_dict(),
    }


@router.post("/ranking")
async def enrich_from_trinks_ranking(
    request: Request,
    db: TenantDB,
    current_user: CurrentUser,
    commit: Annotated[bool, Query(description="false=dry-run (padrão); true=grava")] = False,
) -> dict:
    """Enriquece clientes (email/nascimento faltantes) a partir do ranking da Trinks."""
    await _guard(db, current_user)
    raw = await _read_body(request)
    rows, parse_report = parse_ranking(raw)
    report = await enrich_clients(
        db, current_user.organization_id, rows, dry_run=not commit
    )
    return {
        "commit": commit,
        "parse": parse_report.as_dict(),
        "enrich": report.as_dict(),
    }


@router.post("/debts")
async def import_trinks_debts(
    request: Request,
    db: TenantDB,
    current_user: CurrentUser,
    commit: Annotated[bool, Query(description="false=dry-run (padrão); true=grava")] = False,
) -> dict:
    """Importa débitos (contas a receber) de um export da Trinks para a org."""
    await _guard(db, current_user)
    raw = await _read_body(request)
    rows, parse_report = parse_debts(raw)
    report = await import_debts(
        db, current_user.organization_id, rows, dry_run=not commit
    )
    return {
        "commit": commit,
        "parse": parse_report.as_dict(),
        "import": report.as_dict(),
    }


@router.post("/cash-closing")
async def import_trinks_cash_closing(
    request: Request,
    db: TenantDB,
    current_user: CurrentUser,
    commit: Annotated[bool, Query(description="false=dry-run (padrão); true=grava")] = False,
) -> dict:
    """Importa o fechamento de caixa diário (Movimentação Financeira) da Trinks."""
    await _guard(db, current_user)
    raw = await _read_body(request)
    rows, parse_report = parse_cash_closings(raw)
    report = await import_cash_closings(
        db, current_user.organization_id, rows, dry_run=not commit
    )
    return {
        "commit": commit,
        "parse": parse_report.as_dict(),
        "import": report.as_dict(),
    }
