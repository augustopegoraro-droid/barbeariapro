"""Kernel IA — assistente de NAVEGAÇÃO por linguagem natural (anti-alucinação).

Decisão (2026-07-02): o motor (gpt-4o-mini) alucina ao responder dados/números no
chat. Então o Kernel IA **não responde os dados** — ele entende o pedido e
**ENCAMINHA o usuário para a página certa** (o dado real aparece na página, sem
alucinação). O LLM só faz duas coisas de baixo risco:
  1. `navegar(pagina)` — escolhe UMA rota de um catálogo FECHADO (enum);
  2. `solicitar_remarcacao_turno` — barbeiro pede remarcação (cria pedido pendente).

As mensagens ao usuário são **templadas** ("Vou te encaminhar para X") — o LLM não
gera texto livre com dados. RBAC por capacidade: o catálogo de rotas é filtrado por
papel (barbeiro só a própria agenda; gestor todas as páginas do admin).

Provedor isolado (OpenAI). Sem/`OPENAI_API_KEY` inválida → mensagem amigável.

Contrato: `answer(...) -> {"intent", "message", "action", "route", "task_id"}`
onde `action ∈ {navigate, reschedule, answer, config, erro}`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import FULL_ACCESS
from app.services import reschedule as reschedule_svc

logger = logging.getLogger(__name__)

_MAX_ITERS = 4

# ─── catálogo de rotas (fonte da verdade do roteamento) ─────────────────────────
# chave → (rota real no frontend, descrição p/ o LLM casar a intenção)
_ROUTES_GESTOR: dict[str, tuple[str, str]] = {
    "agenda": ("/admin/agenda", "agenda do dia, agendamentos, encaixes, remarcações"),
    "clientes": ("/admin/clientes", "lista de clientes, cadastro, contatos, aniversários"),
    "financeiro": ("/admin/financeiro", "faturamento, receita, despesas, comissões, caixa"),
    "gestor": ("/admin/gestor", "indicadores de gestão: MRR/receita recorrente, ranking de profissionais, clientes inativos, buracos na agenda, faturamento gerado pela IA — usar para perguntas de gestão (a receita recorrente cobre a folha? cabe contratar? cabe expandir?)"),
    "assinaturas": ("/admin/assinaturas", "assinaturas, mensalidades e pacotes (receita recorrente)"),
    "dashboard": ("/admin/dashboard", "visão geral e indicadores do negócio"),
    "servicos": ("/admin/servicos", "serviços oferecidos e preços"),
    "equipe": ("/admin/equipe", "profissionais/barbeiros, comissões, modelo de trabalho"),
    "fidelidade": ("/admin/fidelidade", "programa de pontos e fidelidade"),
    "conversas": ("/admin/conversas", "conversas de WhatsApp com clientes"),
    "crm": ("/admin/crm", "funil de leads / CRM"),
    "campanhas": ("/admin/campanhas", "campanhas de marketing"),
    "empresa": ("/admin/empresa", "dados da empresa, horário de funcionamento, plano"),
    "integracoes": ("/admin/integracoes", "integrações (WhatsApp, Google Calendar)"),
    "usuarios": ("/admin/usuarios", "usuários e acessos do sistema"),
}
_ROUTES_BARBER: dict[str, tuple[str, str]] = {
    "agenda": ("/barbeiro/agenda", "sua agenda do dia"),
}


def _routes_for_role(role: str) -> dict[str, tuple[str, str]]:
    return _ROUTES_GESTOR if role in FULL_ACCESS else _ROUTES_BARBER


_SYSTEM = (
    "Você é o Kernel IA, assistente de NAVEGAÇÃO do BarbeariaPro. Sua função é entender "
    "o que o usuário quer e ENCAMINHÁ-LO para a página certa usando a ferramenta `navegar`. "
    "NUNCA responda dados, números, análises ou faça cálculos você mesmo — o usuário vê "
    "isso na própria página. Seja muito breve. Se o usuário for barbeiro e pedir para "
    "remarcar/realocar o próprio turno, use `solicitar_remarcacao_turno`. Se nenhuma página "
    "servir, diga em uma frase que não encontrou e sugira o que ele pode pedir."
)


@dataclass
class KernelCtx:
    role: str
    org_id: int
    barber_id: Optional[int] = None
    user_id: Optional[int] = None
    route: Optional[str] = None        # preenchido pela tool navegar
    route_label: Optional[str] = None
    task_id: Optional[str] = None      # preenchido pela tool de remarcação


def _tools_for_role(role: str) -> list[dict]:
    routes = _routes_for_role(role)
    tools: list[dict] = [
        {
            "type": "function",
            "function": {
                "name": "navegar",
                "description": "Encaminha o usuário para a página que responde ao pedido dele.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pagina": {
                            "type": "string",
                            "enum": list(routes.keys()),
                            "description": "\n".join(f"{k}: {d}" for k, (_, d) in routes.items()),
                        }
                    },
                    "required": ["pagina"],
                },
            },
        }
    ]
    if role not in FULL_ACCESS:  # barbeiro
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "solicitar_remarcacao_turno",
                    "description": "Registra um pedido de remarcação dos atendimentos do próprio barbeiro (pendente até um gestor aprovar).",
                    "parameters": {
                        "type": "object",
                        "properties": {"motivo": {"type": "string", "description": "Motivo do pedido."}},
                    },
                },
            }
        )
    return tools


async def _dispatch(name: str, args: dict, db: AsyncSession, ctx: KernelCtx) -> dict:
    if name == "navegar":
        routes = _routes_for_role(ctx.role)
        key = (args.get("pagina") or "").strip()
        entry = routes.get(key)
        if entry is None:
            return {"erro": "pagina desconhecida"}
        ctx.route, ctx.route_label = entry[0], key
        return {"ok": True, "rota": entry[0]}
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
        return {"ok": True, "pedido_id": req.id}
    return {"erro": f"ferramenta desconhecida: {name}"}


# rótulos amigáveis das rotas p/ a mensagem templada
_LABELS = {
    "agenda": "a Agenda", "clientes": "os Clientes", "financeiro": "o Financeiro",
    "gestor": "os Indicadores de Gestão", "assinaturas": "as Assinaturas",
    "dashboard": "o Dashboard", "servicos": "os Serviços", "equipe": "a Equipe",
    "fidelidade": "a Fidelidade", "conversas": "as Conversas", "crm": "o CRM",
    "campanhas": "as Campanhas", "empresa": "a Empresa", "integracoes": "as Integrações",
    "usuarios": "os Usuários",
}


async def answer(
    db: AsyncSession,
    prompt: str,
    *,
    role: str,
    org_id: int,
    unit_id: Optional[int] = None,  # aceito p/ compat; navegação não usa
    barber_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> dict:
    """Roteia o pedido para a página certa (ou cria remarcação). Nunca levanta."""
    base = {"intent": "geral", "message": "", "action": "answer", "route": None, "task_id": None}
    if not settings.openai_api_key:
        return {**base, "intent": "config", "action": "config",
                "message": "O Kernel IA ainda não está configurado (falta OPENAI_API_KEY)."}

    ctx = KernelCtx(role=role, org_id=org_id, barber_id=barber_id, user_id=user_id)
    try:
        from openai import AsyncOpenAI  # import tardio

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ]
        tools = _tools_for_role(role)

        for _ in range(_MAX_ITERS):
            resp = await client.chat.completions.create(
                model=settings.kernel_ia_model, messages=messages, tools=tools,
                tool_choice="auto", temperature=0,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                # sem tool → pergunta de esclarecimento ou "não encontrei" (sem dados).
                return {**base, "message": msg.content or "Não entendi. Sobre o que você quer ver?"}

            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                args = _json(tc.function.arguments)
                result = await _dispatch(tc.function.name, args, db, ctx)
                # Terminal: navegar / remarcação → mensagem TEMPLADA (sem texto do LLM).
                if tc.function.name == "navegar" and ctx.route:
                    label = _LABELS.get(ctx.route_label or "", "a página")
                    return {**base, "intent": "navegar", "action": "navigate",
                            "route": ctx.route, "message": f"Certo! Vou te encaminhar para {label}."}
                if tc.function.name == "solicitar_remarcacao_turno" and ctx.task_id:
                    return {**base, "intent": "solicitar_remarcacao_turno", "action": "reschedule",
                            "task_id": ctx.task_id,
                            "message": "Pedido de remarcação registrado — um gestor vai avaliar."}
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, ensure_ascii=False)})

        return {**base, "message": "Não consegui identificar a página. Pode reformular?"}
    except Exception as e:  # noqa: BLE001
        logger.exception("kernel_ia.answer falhou")
        if type(e).__name__ == "AuthenticationError" or "invalid_api_key" in str(e):
            return {**base, "intent": "config", "action": "config",
                    "message": "A chave da OpenAI está inválida ou expirada. Atualize a OPENAI_API_KEY."}
        return {**base, "intent": "erro", "action": "erro",
                "message": "Tive um problema ao processar agora. Tenta de novo?"}


def _json(s: Optional[str]) -> dict:
    try:
        return json.loads(s or "{}")
    except json.JSONDecodeError:
        return {}
