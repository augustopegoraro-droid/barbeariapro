"""Kernel IA — assistente de NAVEGAÇÃO por linguagem natural (anti-alucinação).

Decisão (2026-07-02, D-57): o motor LLM alucina ao responder dados/
números no chat. Então o Kernel IA **não responde os dados** — ele entende o
pedido e **ENCAMINHA o usuário para a página certa** (o dado real aparece na
página, sem alucinação). O LLM só faz duas coisas de baixo risco:
  1. `navegar(pagina)` — escolhe UMA rota de um catálogo FECHADO (enum);
  2. `solicitar_remarcacao_turno` — barbeiro pede remarcação (cria pedido pendente).

As mensagens ao usuário são **templadas** ("Vou te encaminhar para X") — o LLM não
gera texto livre com dados. RBAC por capacidade: o catálogo de rotas é filtrado por
papel (barbeiro só a própria agenda; gestor todas as páginas do admin).

**Exceção controlada (2026-07-02, D-58):** owner/manager (`MANAGER_ACCESS`) ganham
a tool `consultar_financas`, que RESPONDE dados financeiros no chat — mas sem
reabrir a alucinação do D-57: os números vêm 100% de `app.services.management`
(formatados por `kernel_ia_finance`, texto determinístico, o LLM não os toca); só
a UMA frase de insight que acompanha o relatório é gerada pelo LLM, e essa frase
passa por `kernel_ia_finance.guard_insight` — qualquer número citado que não
esteja no relatório real nem no playbook de referência é descartado antes de
chegar ao usuário. Recepção e barbeiro continuam sem acesso a dados financeiros.

Provedor isolado (Anthropic/Claude — D-77, antes OpenAI). Sem/`ANTHROPIC_API_KEY`
inválida → mensagem amigável.

Contrato: `answer(...) -> {"intent", "message", "action", "route", "task_id"}`
onde `action ∈ {navigate, reschedule, finance_answer, answer, config, erro}`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import FULL_ACCESS, MANAGER_ACCESS
from app.data.finance_playbook import PLAYBOOK
from app.services import kernel_ia_finance
from app.services import reschedule as reschedule_svc

logger = logging.getLogger(__name__)

_MAX_ITERS = 4

# ─── catálogo de rotas (fonte da verdade do roteamento) ─────────────────────────
# chave → (rota real no frontend, descrição p/ o LLM casar a intenção)
_ROUTES_GESTOR: dict[str, tuple[str, str]] = {
    "agenda": ("/admin/agenda", "agenda do dia, agendamentos, encaixes, remarcações"),
    "clientes": ("/admin/clientes", "lista de clientes, cadastro, contatos, aniversários"),
    "financeiro": ("/admin/financeiro", "faturamento, receita, despesas, comissões, caixa"),
    "gestor": ("/admin/gestor", "indicadores de gestão: MRR/receita recorrente, FOLHA DE PAGAMENTO da equipe (custo fixo, comissões, aluguel de cadeira) e cobertura da folha pela receita recorrente, ranking de profissionais, clientes inativos, buracos na agenda, faturamento da IA — usar para perguntas de gestão (a receita recorrente cobre a folha? cabe contratar mais um barbeiro? cabe expandir?)"),
    "assinaturas": ("/admin/assinaturas", "assinaturas, mensalidades e pacotes (receita recorrente)"),
    "dashboard": ("/admin/dashboard", "visão geral e indicadores do negócio"),
    "servicos": ("/admin/servicos", "serviços oferecidos e preços"),
    "equipe": ("/admin/equipe", "profissionais/barbeiros: cadastrar, comissões e configurar modelo de trabalho (CLT, MEI, comissionado, aluguel de cadeira, híbrido) e custo mensal"),
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
    "Você é o Kernel IA do BarbeariaPro. Você NUNCA calcula, soma ou inventa números — "
    "só escolhe entre ferramentas de catálogo fechado:\n"
    "1) Se o pedido for sobre faturamento, receita, despesas, comissões, ranking de "
    "barbeiros, MRR/assinaturas, folha de pagamento, cobertura da folha pela receita "
    "recorrente, faturamento gerado pela IA/WhatsApp, clientes inativos ou horários "
    "ociosos na agenda, use `consultar_financas` (os dados reais vêm do banco).\n"
    "2) Para abrir uma tela/página, use `navegar`.\n"
    "3) Se o usuário for barbeiro e pedir remarcação do próprio turno, use "
    "`solicitar_remarcacao_turno`.\n"
    "Seja muito breve. Se nada servir, diga em uma frase que não encontrou e sugira o "
    "que ele pode pedir."
)

_INSIGHT_SYSTEM = (
    "Você é um consultor financeiro especialista em gestão de barbearias/salões. Com "
    "base SOMENTE nos dados fornecidos abaixo e nos princípios do playbook fornecido, "
    "escreva UMA frase curta (máx. ~25 palavras) de insight ou sugestão prática, em "
    "pt-BR. NÃO invente nenhum número que não esteja nos dados fornecidos ou no "
    "playbook. NÃO cite fontes fora do playbook fornecido. Se não houver recomendação "
    "relevante, responda apenas com uma frase neutra."
)


@dataclass
class KernelCtx:
    role: str
    org_id: int
    barber_id: Optional[int] = None
    user_id: Optional[int] = None
    unit_id: Optional[int] = None      # usado por consultar_financas (ia_faturamento/buracos)
    route: Optional[str] = None        # preenchido pela tool navegar
    route_label: Optional[str] = None
    task_id: Optional[str] = None      # preenchido pela tool de remarcação
    finance_topic: Optional[str] = None        # preenchido pela tool consultar_financas
    finance_data_block: Optional[str] = None   # texto determinístico (sem passagem do LLM)


def _tools_for_role(role: str) -> list[dict]:
    """Tools no formato da API do Claude (`name`/`description`/`input_schema`)."""
    routes = _routes_for_role(role)
    tools: list[dict] = [
        {
            "name": "navegar",
            "description": "Encaminha o usuário para a página que responde ao pedido dele.",
            "input_schema": {
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
        }
    ]
    if role in MANAGER_ACCESS:  # owner/manager apenas — recepção NÃO recebe esta tool
        tools.append(
            {
                "name": "consultar_financas",
                "description": (
                    "Consulta um indicador financeiro/de gestão REAL do negócio (dados "
                    "exatos vindos do banco — você nunca calcula ou inventa números). Use "
                    "para perguntas sobre faturamento/receita/despesas/comissões "
                    "(financeiro), produção por profissional (ranking), receita recorrente "
                    "de assinaturas (mrr), custo de equipe e se a receita recorrente cobre "
                    "a folha (folha), resultado atribuível ao WhatsApp/IA (ia_faturamento), "
                    "clientes parados/candidatos a reativação (inativos), ou horários "
                    "ociosos na agenda de um dia (buracos)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topico": {
                            "type": "string",
                            "enum": list(kernel_ia_finance.TOPICS),
                            "description": (
                                "financeiro: faturamento/receita/despesas/comissões/caixa\n"
                                "ranking: produção por barbeiro (receita, ticket médio, comissão)\n"
                                "mrr: receita recorrente das assinaturas ativas\n"
                                "folha: custo da equipe (fixo+comissão+aluguel) e cobertura pela receita recorrente\n"
                                "ia_faturamento: atendimentos/receita atribuíveis ao WhatsApp/IA\n"
                                "inativos: clientes parados, candidatos a reativação\n"
                                "buracos: horários ociosos na agenda de um dia"
                            ),
                        },
                        "periodo": {
                            "type": "string",
                            "enum": ["hoje", "ontem", "semana", "mes"],
                            "description": (
                                "Período do indicador. Ignorado em 'mrr' e 'inativos' "
                                "(sempre atuais); em 'buracos' só 'hoje'/'ontem' têm efeito."
                            ),
                        },
                    },
                    "required": ["topico", "periodo"],
                },
            }
        )
    if role not in FULL_ACCESS:  # barbeiro
        tools.append(
            {
                "name": "solicitar_remarcacao_turno",
                "description": "Registra um pedido de remarcação dos atendimentos do próprio barbeiro (pendente até um gestor aprovar).",
                "input_schema": {
                    "type": "object",
                    "properties": {"motivo": {"type": "string", "description": "Motivo do pedido."}},
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
    if name == "consultar_financas":
        if ctx.role not in MANAGER_ACCESS:  # defesa em profundidade — mesmo padrão do navegar
            return {"erro": "acesso restrito a owner/manager"}
        topic = (args.get("topico") or "").strip()
        if topic not in kernel_ia_finance.TOPICS:
            return {"erro": "topico desconhecido"}
        periodo = (args.get("periodo") or "mes").strip()
        try:
            data_block = await kernel_ia_finance.fetch_and_format(db, topic, periodo, ctx.unit_id)
        except Exception:
            logger.exception("consultar_financas falhou (topico=%s)", topic)
            return {"erro": "falha ao buscar dados"}
        ctx.finance_topic = topic
        ctx.finance_data_block = data_block
        return {"ok": True}
    return {"erro": f"ferramenta desconhecida: {name}"}


async def _finance_message(client: Any, ctx: KernelCtx) -> str:
    """Bloco de dados determinístico + (opcional) 1 frase de insight do LLM.

    O insight é best-effort: qualquer falha (API, guardrail reprovando) cai de
    volta para o bloco de dados puro — nunca perde a resposta real por causa do
    insight.
    """
    insight = None
    try:
        bullets = "\n".join(f"- {b}" for b in PLAYBOOK.get(ctx.finance_topic, []))
        # V15 (LGPD): o que vira prompt do LLM é a versão sem nome de
        # cliente — o bloco com nome só é usado pra responder o gestor no
        # chat (guard_insight só valida número, redigir nome não quebra ele).
        llm_block = kernel_ia_finance.redact_for_llm(ctx.finance_topic, ctx.finance_data_block)
        grounding = f"{llm_block}\n{bullets}"
        resp = await client.messages.create(
            model=settings.kernel_ia_model,
            max_tokens=150,
            system=_INSIGHT_SYSTEM,
            messages=[
                {"role": "user", "content": f"{llm_block}\n\nPlaybook:\n{bullets}"},
            ],
        )
        raw = next((b.text for b in resp.content if b.type == "text"), "").strip()
        insight = kernel_ia_finance.guard_insight(raw, grounding)
    except Exception:
        logger.exception("consultar_financas: falha ao gerar insight (topico=%s)", ctx.finance_topic)
    return f"{ctx.finance_data_block}\n\n💡 {insight}" if insight else ctx.finance_data_block


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
    unit_id: Optional[int] = None,  # usado por consultar_financas (ia_faturamento/buracos)
    barber_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> dict:
    """Roteia o pedido para a página certa, cria remarcação, ou (owner/manager)
    responde um indicador financeiro real via `consultar_financas`. Nunca levanta."""
    base = {"intent": "geral", "message": "", "action": "answer", "route": None, "task_id": None}
    if not settings.anthropic_api_key:
        return {**base, "intent": "config", "action": "config",
                "message": "O Kernel IA ainda não está configurado (falta ANTHROPIC_API_KEY)."}

    ctx = KernelCtx(role=role, org_id=org_id, barber_id=barber_id, user_id=user_id, unit_id=unit_id)
    try:
        from anthropic import AsyncAnthropic  # import tardio

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        messages: list[dict] = [{"role": "user", "content": prompt}]
        tools = _tools_for_role(role)

        for _ in range(_MAX_ITERS):
            resp = await client.messages.create(
                model=settings.kernel_ia_model, max_tokens=1024,
                system=_SYSTEM, messages=messages, tools=tools,
            )
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                # sem tool → pergunta de esclarecimento ou "não encontrei" (sem dados).
                text = next((b.text for b in resp.content if b.type == "text"), "").strip()
                return {**base, "message": text or "Não entendi. Sobre o que você quer ver?"}

            messages.append({"role": "assistant", "content": resp.content})
            tool_results: list[dict] = []
            for tc in tool_uses:
                args = tc.input if isinstance(tc.input, dict) else {}
                result = await _dispatch(tc.name, args, db, ctx)
                # Terminal: navegar / remarcação → mensagem TEMPLADA (sem texto do LLM).
                if tc.name == "navegar" and ctx.route:
                    label = _LABELS.get(ctx.route_label or "", "a página")
                    return {**base, "intent": "navegar", "action": "navigate",
                            "route": ctx.route, "message": f"Certo! Vou te encaminhar para {label}."}
                if tc.name == "solicitar_remarcacao_turno" and ctx.task_id:
                    return {**base, "intent": "solicitar_remarcacao_turno", "action": "reschedule",
                            "task_id": ctx.task_id,
                            "message": "Pedido de remarcação registrado — um gestor vai avaliar."}
                if tc.name == "consultar_financas":
                    if ctx.finance_data_block:
                        message = await _finance_message(client, ctx)
                        return {**base, "intent": ctx.finance_topic, "action": "finance_answer",
                                "message": message}
                    return {**base, "intent": "financeiro", "action": "erro",
                            "message": "Não consegui buscar esse indicador agora. Tenta de novo "
                                       "ou peça pra abrir o Financeiro."}
                tool_results.append({"type": "tool_result", "tool_use_id": tc.id,
                                     "content": json.dumps(result, ensure_ascii=False)})
            messages.append({"role": "user", "content": tool_results})

        return {**base, "message": "Não consegui identificar a página. Pode reformular?"}
    except Exception as e:  # noqa: BLE001
        logger.exception("kernel_ia.answer falhou")
        if type(e).__name__ == "AuthenticationError" or "invalid x-api-key" in str(e):
            return {**base, "intent": "config", "action": "config",
                    "message": "A chave da Anthropic está inválida ou expirada. Atualize a ANTHROPIC_API_KEY."}
        return {**base, "intent": "erro", "action": "erro",
                "message": "Tive um problema ao processar agora. Tenta de novo?"}
