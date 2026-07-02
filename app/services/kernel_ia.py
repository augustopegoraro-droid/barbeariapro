"""Kernel IA — assistente in-app (chat) que responde sobre o negócio via LLM + tools.

Reusa as *tools de gestão* (`app/services/management.py`, D-52) como ferramentas de
function-calling do LLM: o modelo escolhe a tool, nós executamos contra a sessão RLS
(dados reais da org do token) e devolvemos o resultado; o modelo redige a resposta.

Provedor isolado aqui (OpenAI hoje, `gpt-4o-mini`): trocar por Claude/Anthropic é
mudança local. Sem `OPENAI_API_KEY` → resposta amigável (nunca 500).

Contrato: `answer(db, prompt, unit_id) -> {"intent": str, "message": str}`.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import today_local
from app.services import management as mgmt
from models import Client

logger = logging.getLogger(__name__)

_MAX_ITERS = 5

_SYSTEM = (
    "Você é o Kernel IA, assistente do painel do BarbeariaPro para o gestor da empresa. "
    "Responda SEMPRE em português do Brasil, de forma curta e direta. "
    "Use as ferramentas para obter números reais do negócio — NUNCA invente valores, "
    "datas ou contagens. Se faltar dado, diga que não encontrou. "
    "Valores monetários em reais (R$). Períodos aceitos: hoje, ontem, semana, mes. "
    f"A data de hoje é {{today}}."
)

# ─── schemas das ferramentas (function-calling OpenAI) ──────────────────────────

_PERIOD = {
    "type": "string",
    "enum": ["hoje", "ontem", "semana", "mes"],
    "description": "Período. Default 'mes' para financeiro; 'hoje' para agenda.",
}

_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "financeiro",
            "description": "Resumo financeiro (receita, comissões, despesas, líquido, nº de atendimentos, por método de pagamento) num período.",
            "parameters": {"type": "object", "properties": {"period": _PERIOD}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ranking_profissionais",
            "description": "Ranking de profissionais por receita no período.",
            "parameters": {"type": "object", "properties": {"period": _PERIOD}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clientes_inativos",
            "description": "Clientes parados (candidatos a reativação). Opcional: 'days' (inativos há N dias) e 'limit'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Inativos há pelo menos N dias."},
                    "limit": {"type": "integer", "description": "Máx. de clientes (default 50)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buracos_agenda",
            "description": "Janelas ociosas (buracos) na agenda de um dia, por profissional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Data YYYY-MM-DD. Default: hoje."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mrr",
            "description": "Receita recorrente mensal (MRR) das assinaturas/mensalidades ativas dos clientes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "faturamento_ia",
            "description": "Faturamento atribuível ao bot/IA (agendamentos via WhatsApp concluídos + leads fora do horário) no período.",
            "parameters": {"type": "object", "properties": {"period": _PERIOD}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resumo_clientes",
            "description": "Total de clientes cadastrados (e quantos têm e-mail / data de nascimento).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ─── execução das ferramentas (contra a sessão RLS) ─────────────────────────────

async def _resumo_clientes(db: AsyncSession) -> dict:
    total, w_email, w_birth = (
        await db.execute(
            select(
                func.count(),
                func.count(Client.email),
                func.count(Client.birth_date),
            ).where(Client.deleted_at.is_(None))
        )
    ).one()
    return {"total": total, "com_email": w_email, "com_nascimento": w_birth}


async def _dispatch(name: str, args: dict, db: AsyncSession, unit_id: Optional[int]) -> Any:
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
        if not unit_id:
            return {"erro": "unidade não encontrada para a agenda"}
        d = _parse_date(args.get("date")) or today_local()
        return {"data": d.isoformat(), "buracos": await mgmt.agenda_gaps(db, d, unit_id)}
    if name == "mrr":
        return await mgmt.mrr(db)
    if name == "faturamento_ia":
        df, dt, label = mgmt.resolve_period(args.get("period") or "mes")
        out = await mgmt.ai_generated_revenue(db, df, dt, unit_id)
        out["periodo"] = label
        return out
    if name == "resumo_clientes":
        return await _resumo_clientes(db)
    return {"erro": f"ferramenta desconhecida: {name}"}


def _parse_date(v: Optional[str]) -> Optional[date]:
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


# ─── loop principal ─────────────────────────────────────────────────────────────

async def answer(db: AsyncSession, prompt: str, unit_id: Optional[int] = None) -> dict:
    """Responde a pergunta do gestor usando o LLM + tools. Nunca levanta (retorna msg)."""
    if not settings.openai_api_key:
        return {
            "intent": "config",
            "message": "O Kernel IA ainda não está configurado (falta OPENAI_API_KEY). "
            "Peça ao administrador para configurar.",
        }

    try:
        from openai import AsyncOpenAI  # import tardio: só quando há key

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM.format(today=today_local().isoformat())},
            {"role": "user", "content": prompt},
        ]
        primary_tool: Optional[str] = None

        for _ in range(_MAX_ITERS):
            resp = await client.chat.completions.create(
                model=settings.kernel_ia_model,
                messages=messages,
                tools=_TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return {"intent": primary_tool or "geral", "message": msg.content or ""}

            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                primary_tool = primary_tool or tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _dispatch(tc.function.name, args, db, unit_id)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str, ensure_ascii=False),
                    }
                )

        return {
            "intent": primary_tool or "geral",
            "message": "Não consegui concluir a consulta agora. Pode reformular a pergunta?",
        }
    except Exception as e:  # noqa: BLE001 — nunca derruba o endpoint por falha do LLM
        logger.exception("kernel_ia.answer falhou")
        if type(e).__name__ == "AuthenticationError" or "invalid_api_key" in str(e):
            return {
                "intent": "config",
                "message": "A chave da OpenAI está inválida ou expirada. Peça ao "
                "administrador para atualizar a OPENAI_API_KEY.",
            }
        return {
            "intent": "erro",
            "message": "Tive um problema ao processar agora. Tenta de novo em instantes?",
        }
