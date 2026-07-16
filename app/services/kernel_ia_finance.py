"""Kernel IA — respostas financeiras (D-58): bloco de dados 100% determinístico +
guardrail numérico.

O LLM nunca gera nem toca nos números do relatório aqui — os dicts vêm direto de
`app.services.management` (mesma fonte usada por `/bot/gestor/*` e
`/admin/gestor/*`) e são formatados em texto pt-BR por funções puras. A única
geração livre do LLM nesse fluxo é UMA frase de insight (feita em
`kernel_ia.py`), e mesmo essa passa por `guard_insight` antes de chegar ao
usuário: qualquer número citado que não esteja no bloco de dados real nem no
playbook usado como referência é descartado (fail closed).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_local
from app.services import management

TOPICS = ("financeiro", "ranking", "mrr", "folha", "ia_faturamento", "inativos", "buracos")

_INATIVOS_LIMIT = 15
_BURACOS_LIMIT = 15


def _brl(value: float) -> str:
    s = f"{value:,.2f}"  # "1,700.00" (agrupamento en-US)
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return f"R$ {s}"


def _minutes_label(idle_min: int) -> str:
    h, m = divmod(int(idle_min), 60)
    return f"{h}h{m:02d}" if h else f"{m}min"


# ─── busca + formatação por tópico ─────────────────────────────────────────────

async def fetch_and_format(
    db: AsyncSession, topic: str, periodo: str, unit_id: Optional[int]
) -> str:
    if topic == "financeiro":
        df, dt, label = management.resolve_period(periodo)
        data = await management.financial_summary(db, df, dt)
        return _format_financeiro(data, label)
    if topic == "ranking":
        df, dt, label = management.resolve_period(periodo)
        data = await management.barber_ranking(db, df, dt)
        return _format_ranking(data, label)
    if topic == "mrr":
        data = await management.mrr(db)
        return _format_mrr(data)
    if topic == "folha":
        df, dt, label = management.resolve_period(periodo or "mes")
        payroll = await management.payroll_summary(db, df, dt)
        coverage = await management.recurring_coverage(db)
        return _format_folha(payroll, coverage, label)
    if topic == "ia_faturamento":
        df, dt, label = management.resolve_period(periodo)
        data = await management.ai_generated_revenue(db, df, dt, unit_id)
        return _format_ia_faturamento(data, label)
    if topic == "inativos":
        data = await management.inactive_clients(db)
        return _format_inativos(data)
    if topic == "buracos":
        if unit_id is None:
            return "Não encontrei uma unidade configurada para checar horários ociosos."
        target, note = _buracos_date(periodo)
        data = await management.agenda_gaps(db, target, unit_id)
        return _format_buracos(data, target, note)
    raise ValueError(f"tópico desconhecido: {topic}")


def _buracos_date(periodo: str) -> tuple[date, Optional[str]]:
    """`agenda_gaps` só aceita UMA data (não um período). 'hoje'/'ontem' mapeiam
    direto; 'semana'/'mes' caem em hoje, com uma nota explicando a limitação."""
    today = today_local()
    if periodo == "ontem":
        return today - timedelta(days=1), None
    if periodo in ("semana", "mes"):
        return today, "Buracos na agenda mostra sempre um único dia — usando hoje."
    return today, None


def _format_financeiro(data: dict, label: str) -> str:
    lines = [f"📊 Financeiro — {label} ({data['date_from']}..{data['date_to']})"]
    lines.append(f"Faturamento: {_brl(data['revenue'])} ({data['appointment_count']} atendimentos)")
    lines.append(f"Comissões: {_brl(data['commissions'])}")
    lines.append(f"Despesas: {_brl(data['expenses'])}")
    lines.append(f"Resultado líquido: {_brl(data['net'])}")
    by_method = data.get("by_method") or []
    if by_method:
        lines.append("")
        lines.append("Por forma de pagamento:")
        for m in by_method:
            lines.append(f"• {m['method']}: {_brl(m['amount'])} ({m['count']})")
    else:
        lines.append("")
        lines.append("Sem pagamentos registrados no período.")
    return "\n".join(lines)


def _format_ranking(data: list[dict], label: str) -> str:
    lines = [f"🏆 Ranking de profissionais — {label}"]
    if not data:
        lines.append("Nenhum atendimento concluído no período.")
        return "\n".join(lines)
    for i, r in enumerate(data, start=1):
        lines.append(
            f"{i}. {r['barber_name']} — {_brl(r['revenue'])} ({r['appointment_count']} atend., "
            f"ticket médio {_brl(r['ticket_medio'])}, comissão {_brl(r['commission'])})"
        )
    return "\n".join(lines)


def _format_mrr(data: dict) -> str:
    lines = ["💳 Receita recorrente (MRR)"]
    lines.append(f"MRR atual: {_brl(data['mrr'])}")
    lines.append(f"Assinaturas ativas: {data['active_count']}")
    lines.append(f"Vencendo nos próximos 30 dias: {data['expiring_30d']}")
    return "\n".join(lines)


def _format_folha(payroll: dict, coverage: dict, label: str) -> str:
    lines = [f"👥 Folha × Receita recorrente — {label}"]
    lines.append(f"Custo fixo mensal: {_brl(payroll['fixed_total'])}")
    lines.append(f"Comissões do período: {_brl(payroll['commissions_total'])}")
    lines.append(f"Aluguel de cadeira (receita): {_brl(payroll['chair_rent_income'])}")
    lines.append(f"Custo líquido da folha: {_brl(payroll['net_cost'])}")
    lines.append("")
    lines.append(
        f"MRR (assinaturas ativas): {_brl(coverage['mrr'])} ({coverage['active_subscriptions']} ativas)"
    )
    surplus = coverage["surplus"]
    if coverage["covered"]:
        pct = coverage.get("coverage_pct")
        extra = f" ({pct}% da folha fixa coberta)" if pct is not None else ""
        lines.append(f"Cobertura: cobre a folha fixa — folga de {_brl(surplus)}{extra}")
    else:
        lines.append(f"Cobertura: NÃO cobre a folha fixa — faltam {_brl(abs(surplus))}")
    team = payroll.get("team") or []
    if team:
        lines.append("")
        lines.append("Por profissional:")
        for m in team:
            rent_note = f" (paga {_brl(m['chair_rent'])} de aluguel)" if m["chair_rent"] else ""
            lines.append(
                f"• {m['barber_name']} — {m['work_model']} — fixo {_brl(m['monthly_cost'])} "
                f"+ comissão {_brl(m['commission'])} = {_brl(m['total_cost'])}{rent_note}"
            )
    return "\n".join(lines)


def _format_ia_faturamento(data: dict, label: str) -> str:
    lines = [f"🤖 Faturamento gerado pela IA/WhatsApp — {label}"]
    lines.append(f"Atendimentos via WhatsApp: {data['appointments']}")
    lines.append(f"Receita: {_brl(data['revenue'])}")
    lines.append(f"Leads capturados fora do horário comercial: {data['leads_after_hours']}")
    return "\n".join(lines)


def _format_inativos(data: list[dict]) -> str:
    lines = ["📉 Clientes inativos / em risco"]
    if not data:
        lines.append("Nenhum cliente parado no momento — base de clientes ativa.")
        return "\n".join(lines)
    shown = data[:_INATIVOS_LIMIT]
    for c in shown:
        days = c.get("days_since_last_visit")
        days_txt = f"{days} dias sem visitar" if days is not None else "sem visita registrada"
        pref = f" — prefere {c['preferred_barber']}" if c.get("preferred_barber") else ""
        lines.append(f"• {c['name']} — {days_txt}{pref}")
    if len(data) > len(shown):
        lines.append(f"+{len(data) - len(shown)} outros clientes parados.")
    return "\n".join(lines)


def _format_buracos(data: list[dict], target_date: date, note: Optional[str]) -> str:
    lines = [f"🗓️ Horários ociosos — {target_date.isoformat()}"]
    if note:
        lines.append(note)
    if not data or not any(b["idle_min"] for b in data):
        lines.append(f"Sem horários ociosos em {target_date.isoformat()} (ou unidade fechada).")
        return "\n".join(lines)
    shown = [b for b in data if b["idle_min"]][:_BURACOS_LIMIT]
    for b in shown:
        windows = ", ".join(f"{w['start']}-{w['end']}" for w in b["free_windows"])
        lines.append(f"• {b['barber_name']} — {_minutes_label(b['idle_min'])} livres ({windows})")
    return "\n".join(lines)


# ─── guardrail numérico ─────────────────────────────────────────────────────────
# Reconhece números pt-BR completos ("1.700,00", "49,4", "3") como tokens únicos,
# sem casar uma substring de um número maior (ex.: não deixa "17" "vazar" de
# dentro de "1.700,00" só por coincidência de dígitos).
_NUM_RE = re.compile(
    r"(?<![\d.,])\d{1,3}(?:\.\d{3})*(?:,\d+)?(?![\d.,])"
    r"|(?<![\d.,])\d+(?:,\d+)?(?![\d.,])"
)


def extract_numbers(text: str) -> list[str]:
    """Extrai os tokens numéricos de `text` (regras de agrupamento pt-BR)."""
    return _NUM_RE.findall(text)


_CLIENT_LINE_RE = re.compile(r"^• .+? — ", re.MULTILINE)


def redact_for_llm(topic: str, block: str) -> str:
    """V15 (LGPD): tira nome de cliente do texto antes de virar contexto do
    LLM (Claude) — o bloco original (com nome) continua indo pro gestor no chat
    normalmente, só o que vira prompt do LLM é anonimizado. Só o tópico
    'inativos' lista nome de cliente por linha hoje (`_format_inativos`);
    números (dias sem visita etc.) não são tocados — `guard_insight` só
    valida número, nunca nome."""
    if topic != "inativos":
        return block
    return _CLIENT_LINE_RE.sub("• Cliente — ", block)


def guard_insight(insight: str, grounding_text: str) -> Optional[str]:
    """Defesa em profundidade contra alucinação de números no insight do LLM.

    `grounding_text` deve conter TUDO que é uma fonte permitida de números — o
    bloco de dados determinístico (números reais do negócio) e os bullets do
    playbook usados no prompt (heurísticas gerais, ex.: "15% a 25%"). Qualquer
    número no insight que não apareça, verbatim, em `grounding_text` derruba o
    insight inteiro (fail closed — sem número duvidoso, sem insight, nunca um
    número inventado). Insight sem nenhum número (frase só qualitativa) sempre
    passa.
    """
    insight = (insight or "").strip()
    if not insight:
        return None
    for num in extract_numbers(insight):
        if num not in grounding_text:
            return None
    return insight
