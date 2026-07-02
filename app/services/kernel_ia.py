"""Kernel IA — assistente in-app (chat) que responde sobre o negócio via LLM + tools.

Reusa as *tools de gestão* (`app/services/management.py`, D-52) como ferramentas de
function-calling do LLM: o modelo escolhe a tool, nós executamos contra a sessão RLS
(dados reais da org do token) e devolvemos o resultado; o modelo redige a resposta.

**RBAC por capacidade (default-deny):** o conjunto de tools exposto ao modelo depende
do PAPEL. `owner/manager/reception` (`rbac.FULL_ACCESS`) recebem as tools de negócio
(financeiro, ranking, clientes…); o **barbeiro** recebe só agenda + solicitar
remarcação — ele não recebe as tools financeiras, então não há como obtê-las nem por
texto livre (a barreira é a ausência da capacidade, não a precisão do classificador).

Provedor isolado aqui (OpenAI hoje, `gpt-4o-mini`): trocar por Claude é local. Sem
`OPENAI_API_KEY` (ou key inválida) → resposta amigável (nunca 500).

Contrato: `answer(db, prompt, role=..., org_id=..., unit_id=..., barber_id=..., user_id=...)
-> {"intent": str, "message": str, "task_id": Optional[str]}`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import today_local
from app.core.rbac import FULL_ACCESS
from app.services import management as mgmt
from app.services import reschedule as reschedule_svc
from models import Client

logger = logging.getLogger(__name__)

_MAX_ITERS = 5

_SYSTEM_BASE = (
    "Você é o Kernel IA, assistente do painel do BarbeariaPro. Responda SEMPRE em "
    "português do Brasil, curto e direto. Use as ferramentas para obter números reais "
    "— NUNCA invente valores, datas ou contagens. Valores em reais (R$). Períodos: "
    "hoje, ontem, semana, mes. A data de hoje é {today}."
)
_SYSTEM_BARBER = (
    " Você está atendendo um BARBEIRO: só pode ajudar com a agenda e com solicitações "
    "de remarcação de turno. Para financeiro, caixa, clientes ou qualquer outro assunto, "
    "responda que isso não está disponível para o perfil de barbeiro."
)


@dataclass
class KernelCtx:
    role: str
    org_id: int
    unit_id: Optional[int] = None
    barber_id: Optional[int] = None
    user_id: Optional[int] = None
    task_id: Optional[str] = None  # preenchido por tools que criam tarefa (remarcação)


# ─── schemas das ferramentas ────────────────────────────────────────────────────

_PERIOD = {
    "type": "string",
    "enum": ["hoje", "ontem", "semana", "mes"],
    "description": "Período. Default 'mes' para financeiro; 'hoje' para agenda.",
}


def _fn(name: str, description: str, properties: Optional[dict] = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}},
        },
    }


# Tool comum a gestor e barbeiro.
_TOOL_BURACOS = _fn(
    "buracos_agenda",
    "Janelas ociosas (buracos) na agenda de um dia, por profissional.",
    {"date": {"type": "string", "description": "Data YYYY-MM-DD. Default: hoje."}},
)
# Tool exclusiva do barbeiro.
_TOOL_REMARCACAO = _fn(
    "solicitar_remarcacao_turno",
    "Registra um PEDIDO de remarcação dos atendimentos do próprio barbeiro (fica "
    "pendente até um gestor aprovar). Use quando o barbeiro pedir para remarcar/realocar "
    "seu turno ou seus atendimentos.",
    {"motivo": {"type": "string", "description": "Motivo/observação do pedido."}},
)

# Tools de negócio (só gestor / FULL_ACCESS).
_TOOLS_GESTOR: list[dict] = [
    _fn("financeiro", "Resumo financeiro (receita, comissões, despesas, líquido, nº de atendimentos, por método) num período.", {"period": _PERIOD}),
    _fn("ranking_profissionais", "Ranking de profissionais por receita no período.", {"period": _PERIOD}),
    _fn("clientes_inativos", "Clientes parados (candidatos a reativação). Opcional 'days' e 'limit'.", {"days": {"type": "integer"}, "limit": {"type": "integer"}}),
    _TOOL_BURACOS,
    _fn("mrr", "Receita recorrente mensal (MRR) das assinaturas ativas dos clientes."),
    _fn("faturamento_ia", "Faturamento atribuível ao bot/IA (agendamentos via WhatsApp + leads fora do horário) no período.", {"period": _PERIOD}),
    _fn("resumo_clientes", "Total de clientes cadastrados (e quantos têm e-mail / nascimento)."),
]
# Tools do barbeiro (default-deny: sem nada financeiro).
_TOOLS_BARBER: list[dict] = [_TOOL_BURACOS, _TOOL_REMARCACAO]


def _tools_for_role(role: str) -> list[dict]:
    return _TOOLS_GESTOR if role in FULL_ACCESS else _TOOLS_BARBER


def _system_for_role(role: str) -> str:
    base = _SYSTEM_BASE.format(today=today_local().isoformat())
    return base if role in FULL_ACCESS else base + _SYSTEM_BARBER


# ─── execução das ferramentas (contra a sessão RLS) ─────────────────────────────

async def _resumo_clientes(db: AsyncSession) -> dict:
    total, w_email, w_birth = (
        await db.execute(
            select(func.count(), func.count(Client.email), func.count(Client.birth_date)).where(
                Client.deleted_at.is_(None)
            )
        )
    ).one()
    return {"total": total, "com_email": w_email, "com_nascimento": w_birth}


def _parse_date(v: Optional[str]) -> Optional[date]:
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


async def _dispatch(name: str, args: dict, db: AsyncSession, ctx: KernelCtx) -> Any:
    if name == "financeiro":
        df, dt, label = mgmt.resolve_period(args.get("period") or "mes")
        out = await mgmt.financial_summary(db, df, dt)
        out["periodo"] = label
        return out
    if name == "ranking_profissionais":
        df, dt, label = mgmt.resolve_period(args.get("period") or "mes")
        return {"periodo": label, "ranking": await mgmt.barber_ranking(db, df, dt)}
    if name == "clientes_inativos":
        return {"clientes": await mgmt.inactive_clients(db, days=args.get("days"), limit=args.get("limit") or 50)}
    if name == "buracos_agenda":
        if not ctx.unit_id:
            return {"erro": "unidade não encontrada para a agenda"}
        d = _parse_date(args.get("date")) or today_local()
        return {"data": d.isoformat(), "buracos": await mgmt.agenda_gaps(db, d, ctx.unit_id)}
    if name == "mrr":
        return await mgmt.mrr(db)
    if name == "faturamento_ia":
        df, dt, label = mgmt.resolve_period(args.get("period") or "mes")
        out = await mgmt.ai_generated_revenue(db, df, dt, ctx.unit_id)
        out["periodo"] = label
        return out
    if name == "resumo_clientes":
        return await _resumo_clientes(db)
    if name == "solicitar_remarcacao_turno":
        if ctx.barber_id is None:
            return {"erro": "apenas barbeiros podem solicitar remarcação"}
        req = await reschedule_svc.create_request(
            db,
            organization_id=ctx.org_id,
            barber_id=ctx.barber_id,
            requested_by_user_id=ctx.user_id,
            reason=args.get("motivo"),
            source="kernel_ia",
        )
        ctx.task_id = str(req.id)
        return {"ok": True, "pedido_id": req.id, "status": "pendente"}
    return {"erro": f"ferramenta desconhecida: {name}"}


# ─── loop principal ─────────────────────────────────────────────────────────────

async def answer(
    db: AsyncSession,
    prompt: str,
    *,
    role: str,
    org_id: int,
    unit_id: Optional[int] = None,
    barber_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> dict:
    """Responde a pergunta usando LLM + tools filtradas por papel. Nunca levanta."""
    if not settings.openai_api_key:
        return {
            "intent": "config",
            "message": "O Kernel IA ainda não está configurado (falta OPENAI_API_KEY). "
            "Peça ao administrador para configurar.",
            "task_id": None,
        }

    ctx = KernelCtx(role=role, org_id=org_id, unit_id=unit_id, barber_id=barber_id, user_id=user_id)
    tools = _tools_for_role(role)
    try:
        from openai import AsyncOpenAI  # import tardio: só quando há key

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages: list[dict] = [
            {"role": "system", "content": _system_for_role(role)},
            {"role": "user", "content": prompt},
        ]
        primary_tool: Optional[str] = None

        for _ in range(_MAX_ITERS):
            resp = await client.chat.completions.create(
                model=settings.kernel_ia_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return {"intent": primary_tool or "geral", "message": msg.content or "", "task_id": ctx.task_id}

            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                primary_tool = primary_tool or tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _dispatch(tc.function.name, args, db, ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str, ensure_ascii=False),
                    }
                )

        return {"intent": primary_tool or "geral", "message": "Não consegui concluir agora. Pode reformular?", "task_id": ctx.task_id}
    except Exception as e:  # noqa: BLE001 — nunca derruba o endpoint por falha do LLM
        logger.exception("kernel_ia.answer falhou")
        if type(e).__name__ == "AuthenticationError" or "invalid_api_key" in str(e):
            return {
                "intent": "config",
                "message": "A chave da OpenAI está inválida ou expirada. Peça ao "
                "administrador para atualizar a OPENAI_API_KEY.",
                "task_id": None,
            }
        return {"intent": "erro", "message": "Tive um problema ao processar agora. Tenta de novo em instantes?", "task_id": None}
