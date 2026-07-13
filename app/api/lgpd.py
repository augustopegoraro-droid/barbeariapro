# file: app/api/lgpd.py
"""Direitos do titular — LGPD (Fase 8, `promptseguranca.md`).

Ações gestor-assistidas (sem site público/portal do cliente final ainda —
ver `promptsitepublico.md`): o titular pede por telefone/WhatsApp, o gestor
executa aqui. `privacy.lgpd.manage` é owner-only no catálogo (D-67) —
decisão deliberada, dado pessoal de titular externo é sensível demais para
delegar ao gestor por padrão.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.schemas.lgpd import AnonymizeClientOut, ConsentRecordOut
from app.services.audit import record_event
from app.services.lgpd import ClientNotFound, anonymize_client, export_client_data
from models import ConsentRecord, User

router = APIRouter(prefix="/admin/security/lgpd", tags=["lgpd"])


@router.get("/clients/{client_id}/export")
async def export_client(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> Response:
    """Dados do titular em formato portável (JSON) — direito de exportação."""
    await require_permission(db, current_user, "privacy.lgpd.manage")
    try:
        data = await export_client_data(db, client_id)
    except ClientNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado")

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="privacy.lgpd.export",
        resource_type="client",
        resource_id=client_id,
    )
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="cliente-{client_id}.json"'},
    )


@router.post("/clients/{client_id}/anonymize", response_model=AnonymizeClientOut)
async def anonymize_client_route(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AnonymizeClientOut:
    """Direito ao esquecimento — anonimiza PII, preserva agregados financeiros
    (Payment/AppointmentItem intocados)."""
    await require_permission(db, current_user, "privacy.lgpd.manage")
    try:
        client = await anonymize_client(db, client_id)
    except ClientNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado")

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="privacy.lgpd.anonymize",
        resource_type="client",
        resource_id=client_id,
        reason="Direito ao esquecimento (LGPD)",
    )
    return AnonymizeClientOut(client_id=client.id, anonymized_at=client.anonymized_at)


@router.get("/clients/{client_id}/consents", response_model=list[ConsentRecordOut])
async def list_client_consents(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[ConsentRecordOut]:
    await require_permission(db, current_user, "privacy.lgpd.manage")
    rows = (
        await db.execute(
            select(ConsentRecord)
            .where(ConsentRecord.subject_type == "client")
            .where(ConsentRecord.subject_id == client_id)
            .order_by(ConsentRecord.created_at.desc())
        )
    ).scalars().all()
    return [
        ConsentRecordOut(
            channel=r.channel, status=r.status, source=r.source, created_at=r.created_at
        )
        for r in rows
    ]
