# file: app/api/legal.py
"""Aceite dos documentos de quem OPERA o sistema (D-87).

O D-86 fechou a entrada do **cliente final**. Aqui é a outra ponta: funcionário
e dono entravam no painel sem ter aceitado nada.

Dois documentos, naturezas diferentes (ver migration 0049):
- **termo de uso e confidencialidade** — cada usuário do painel, uma vez por
  versão. NÃO é consentimento (a base legal do vínculo é a relação de trabalho):
  é o registro de que foi informado do dever de sigilo;
- **contrato de operador (DPA)** — uma vez por organização, só o **proprietário**
  pode aceitar, porque é ele quem representa o controlador dos dados.

Desenho igual ao do consentimento do cliente (D-86): a **coluna** guarda o
estado que o gate lê, e `consent_records` (append-only, `subject_type='user'`)
guarda a prova. Reaceitar registra linha nova — o histórico mostra a evolução
de versões, nunca sobrescreve.

⚠️ **O bloqueio é de UX, não de API.** O painel não deixa passar sem aceitar
(`components/legal/legal-gate.tsx`), mas as rotas de negócio continuam
respondendo a um token válido. Bloquear a API inteira por aceite pendente
travaria a barbearia por um bug de tela — e o valor jurídico está no registro
auditado, não em negar `GET /agenda`. Decisão consciente, ver DECISIONS D-87.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.privacy import (
    DPA_VERSION,
    SOURCE_DPA_ACCEPT,
    SOURCE_TERMS_ACCEPT,
    TERMS_VERSION,
)
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.services.audit import record_event
from app.services.consent import record_consent
from models import Organization, User

router = APIRouter(prefix="/auth/me/legal", tags=["legal"])

Document = Literal["terms", "dpa"]


class DocumentStatus(BaseModel):
    """Estado de um documento para quem está pedindo."""

    version: str
    accepted_version: Optional[str] = None
    accepted_at: Optional[datetime] = None
    # True quando este usuário precisa aceitar agora. O DPA só é exigido do
    # proprietário — para os demais papéis vem sempre `False` (não é omissão:
    # eles não podem aceitar contrato em nome da empresa).
    pending: bool


class LegalStatusOut(BaseModel):
    terms: DocumentStatus
    dpa: DocumentStatus
    role: str


class AcceptIn(BaseModel):
    document: Document


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


async def _status(db: AsyncSession, user: User) -> LegalStatusOut:
    role = await resolve_current_role(db, user)
    org = (
        await db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
    ).scalar_one()

    return LegalStatusOut(
        role=role,
        terms=DocumentStatus(
            version=TERMS_VERSION,
            accepted_version=user.terms_version_accepted,
            accepted_at=user.terms_accepted_at,
            pending=user.terms_version_accepted != TERMS_VERSION,
        ),
        dpa=DocumentStatus(
            version=DPA_VERSION,
            accepted_version=org.dpa_version_accepted,
            accepted_at=org.dpa_accepted_at,
            pending=role == "owner" and org.dpa_version_accepted != DPA_VERSION,
        ),
    )


@router.get("", response_model=LegalStatusOut)
async def legal_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> LegalStatusOut:
    """O que este usuário ainda precisa aceitar. Sem permissão específica:
    todo usuário autenticado precisa saber o que deve dele."""
    return await _status(db, current_user)


@router.post("/accept", response_model=LegalStatusOut)
async def accept_document(
    body: AcceptIn,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> LegalStatusOut:
    now = datetime.now(timezone.utc)
    ip = _client_ip(request)
    role = await resolve_current_role(db, current_user)

    org = (
        await db.execute(
            select(Organization).where(Organization.id == current_user.organization_id)
        )
    ).scalar_one()

    if body.document == "terms":
        current_user.terms_version_accepted = TERMS_VERSION
        current_user.terms_accepted_at = now
        version, source, action = TERMS_VERSION, SOURCE_TERMS_ACCEPT, "legal.terms.accept"
    else:
        if role != "owner":
            # Não é falta de permissão de tela: contrato em nome da empresa só
            # o proprietário assina.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Só o proprietário pode aceitar o contrato de operador.",
            )
        org.dpa_version_accepted = DPA_VERSION
        org.dpa_accepted_at = now
        org.dpa_accepted_by_user_id = current_user.id
        version, source, action = DPA_VERSION, SOURCE_DPA_ACCEPT, "legal.dpa.accept"

    await record_consent(
        db,
        organization_id=current_user.organization_id,
        subject_type="user",
        subject_id=current_user.id,
        channel=body.document,
        status="accepted",
        source=source,
        ip=ip,
        policy_version=version,
    )
    # Monta a resposta ANTES do commit: `get_tenant_db` abre a transação num
    # context manager, então qualquer consulta depois do commit estoura
    # ("Can't operate on closed transaction inside context manager").
    resposta = LegalStatusOut(
        role=role,
        terms=DocumentStatus(
            version=TERMS_VERSION,
            accepted_version=current_user.terms_version_accepted,
            accepted_at=current_user.terms_accepted_at,
            pending=current_user.terms_version_accepted != TERMS_VERSION,
        ),
        dpa=DocumentStatus(
            version=DPA_VERSION,
            accepted_version=org.dpa_version_accepted,
            accepted_at=org.dpa_accepted_at,
            pending=role == "owner" and org.dpa_version_accepted != DPA_VERSION,
        ),
    )
    await db.commit()

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action=action,
        resource_type="organization" if body.document == "dpa" else "user",
        resource_id=current_user.organization_id if body.document == "dpa" else current_user.id,
        after={"version": version},
        reason=f"Aceite de {body.document} v{version}",
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return resposta
