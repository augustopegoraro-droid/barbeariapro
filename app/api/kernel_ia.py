"""Kernel IA — endpoint de texto livre com autorização por papel (RBAC).

`POST /kernel-ia/query`: recebe o texto livre do usuário autenticado (JWT do
tenant), detecta a intenção e **autoriza antes de despachar** (a autorização é a
fonte da verdade; ver `app/services/kernel_ia.py`). Pedido negado devolve 200 com
`allowed=false` + mensagem clara — para o painel de chat exibir a recusa como
resposta, em vez de um erro genérico.

⚠️ Despacho: as intenções permitidas ainda NÃO são executadas de verdade (agenda,
folga, remarcação de turno). O despacho para os serviços é um follow-up; em
particular, o fluxo de "remarcação/realocação de turno" (solicitação com
aprovação de gestor × execução direta) depende de definição de negócio.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_tenant_db, resolve_current_role_with_barber
from app.services import reschedule as reschedule_svc
from app.services.kernel_ia import KernelIntent, evaluate_request
from models import User

router = APIRouter(prefix="/kernel-ia", tags=["kernel-ia"])


class KernelQueryIn(BaseModel):
    prompt: str = Field(..., min_length=1, description="Texto livre do usuário")


class KernelQueryOut(BaseModel):
    # by_alias na resposta (padrão do FastAPI) → devolve `taskId` p/ o frontend.
    model_config = ConfigDict(populate_by_name=True)

    intent: str
    allowed: bool
    message: str
    task_id: Optional[str] = Field(default=None, alias="taskId")


@router.post("/query", response_model=KernelQueryOut)
async def query(
    body: KernelQueryIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> KernelQueryOut:
    role, barber_id = await resolve_current_role_with_barber(db, current_user)
    decision = evaluate_request(role, body.prompt)

    # Autorização é a barreira: intenção não permitida NUNCA é despachada.
    if not decision.allowed:
        return KernelQueryOut(
            intent=decision.intent.value, allowed=False, message=decision.message
        )

    task_id: Optional[str] = None
    message = decision.message
    # Despacho: a remarcação de turno cria um PEDIDO pendente (aprovação do
    # gestor). Só faz sentido para barbeiro (tem barber_id). Agenda/folga seguem
    # como reconhecimento por ora (TODO: despachar para os serviços reais).
    if (
        decision.intent is KernelIntent.SOLICITAR_REMARCACAO_TURNO
        and barber_id is not None
    ):
        req = await reschedule_svc.create_request(
            db,
            organization_id=current_user.organization_id,
            barber_id=barber_id,
            requested_by_user_id=current_user.id,
            reason=body.prompt,
            source="kernel_ia",
        )
        task_id = str(req.id)
        message = "Solicitação de remarcação registrada — um gestor vai avaliar."

    return KernelQueryOut(
        intent=decision.intent.value, allowed=True, message=message, task_id=task_id
    )
