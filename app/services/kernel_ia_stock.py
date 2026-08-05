"""Kernel IA — respostas de estoque: bloco de dados 100% determinístico.

Mesmo padrão de `kernel_ia_finance.py` (D-58): os dicts vêm direto de
`app.services.inventory`/`app.services.management` (mesma fonte de
`/estoque/alertas` e `/estoque/giro`) e são formatados em texto pt-BR por
funções puras — o LLM nunca toca em número aqui.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import inventory, management

TOPICS = ("alertas", "niveis", "giro")

_ALERTAS_LIMIT = 20
_GIRO_LIMIT = 15


def _brl(value: float) -> str:
    s = f"{value:,.2f}"  # "1,700.00" (agrupamento en-US)
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return f"R$ {s}"


async def fetch_and_format(db: AsyncSession, topic: str, periodo: str) -> str:
    if topic == "alertas":
        data = await inventory.low_stock_alerts(db)
        return _format_alertas(data)
    if topic == "niveis":
        data = await management.stock_overview(db)
        return _format_niveis(data)
    if topic == "giro":
        df, dt, label = management.resolve_period(periodo or "mes")
        data = await management.stock_turnover(db, df, dt)
        return _format_giro(data, label)
    raise ValueError(f"tópico desconhecido: {topic}")


def _format_alertas(data: list[dict]) -> str:
    lines = ["⚠️ Alertas de estoque baixo"]
    if not data:
        lines.append("Nenhuma variação no mínimo ou abaixo — estoque OK.")
        return "\n".join(lines)
    shown = data[:_ALERTAS_LIMIT]
    for a in shown:
        lines.append(
            f"• {a['product_name']} — {a['variant_name']}: {a['stock_qty']:g} "
            f"(mínimo {a['min_stock']:g})"
        )
    if len(data) > len(shown):
        lines.append(f"+{len(data) - len(shown)} outras variações em alerta.")
    return "\n".join(lines)


def _format_niveis(data: dict) -> str:
    lines = ["📦 Situação geral do estoque"]
    lines.append(f"Variações ativas rastreadas: {data['total_variants']}")
    lines.append(f"No mínimo ou abaixo: {data['below_min_count']}")
    lines.append(f"Zeradas: {data['zero_stock_count']}")
    lines.append(f"Valor total em estoque (custo médio): {_brl(data['total_value'])}")
    return "\n".join(lines)


def _format_giro(data: list[dict], label: str) -> str:
    lines = [f"🔄 Giro de estoque — {label}"]
    if not data:
        lines.append("Nenhuma venda de produto no período.")
        return "\n".join(lines)
    shown = data[:_GIRO_LIMIT]
    for g in shown:
        turnover_txt = f"{g['turnover']:.2f}x" if g["turnover"] is not None else "n/d"
        lines.append(
            f"• {g['product_name']} — {g['variant_name']}: {g['qty_sold']:g} vendidas, "
            f"estoque médio {g['avg_stock']:g}, giro {turnover_txt}"
        )
    if len(data) > len(shown):
        lines.append(f"+{len(data) - len(shown)} outras variações vendidas no período.")
    return "\n".join(lines)
