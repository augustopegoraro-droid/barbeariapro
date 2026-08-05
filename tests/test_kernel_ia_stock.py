"""Kernel IA — respostas de estoque: formatação determinística. Tudo puro (sem
DB, sem LLM) — os dicts imitam exatamente o formato que
`app.services.inventory`/`app.services.management` já documentam devolver.
"""
from __future__ import annotations

import pytest

from app.services import kernel_ia_stock as ks


# ─── formatação por tópico ───────────────────────────────────────────────────

def test_format_alertas_com_dados():
    data = [
        {"variant_id": 1, "variant_name": "500ml", "product_name": "Refrigerante",
         "stock_qty": 2.0, "min_stock": 5.0},
    ]
    out = ks._format_alertas(data)
    assert "Refrigerante" in out and "500ml" in out
    assert "2" in out and "mínimo 5" in out


def test_format_alertas_vazio_nao_quebra():
    out = ks._format_alertas([])
    assert "estoque OK" in out


def test_format_alertas_trunca_e_mostra_resto():
    data = [
        {"variant_id": i, "variant_name": f"V{i}", "product_name": f"P{i}",
         "stock_qty": 0.0, "min_stock": 1.0}
        for i in range(25)
    ]
    out = ks._format_alertas(data)
    assert "+5 outras variações em alerta." in out


def test_format_niveis_valores_e_formato_ptbr():
    data = {
        "total_variants": 12,
        "below_min_count": 3,
        "zero_stock_count": 1,
        "total_value": 1700.5,
    }
    out = ks._format_niveis(data)
    assert "Variações ativas rastreadas: 12" in out
    assert "No mínimo ou abaixo: 3" in out
    assert "Zeradas: 1" in out
    assert "R$ 1.700,50" in out


def test_format_giro_ordem_preservada():
    data = [
        {"variant_id": 1, "variant_name": "500ml", "product_name": "Refrigerante",
         "qty_sold": 20.0, "avg_stock": 10.0, "turnover": 2.0},
        {"variant_id": 2, "variant_name": "Único", "product_name": "Picolé",
         "qty_sold": 5.0, "avg_stock": 5.0, "turnover": 1.0},
    ]
    out = ks._format_giro(data, "mês")
    assert out.index("Refrigerante") < out.index("Picolé")
    assert "2.00x" in out


def test_format_giro_vazio_nao_quebra():
    out = ks._format_giro([], "hoje")
    assert "Nenhuma venda de produto no período." in out


def test_format_giro_turnover_none_mostra_n_d():
    data = [
        {"variant_id": 1, "variant_name": "500ml", "product_name": "Refrigerante",
         "qty_sold": 0.0, "avg_stock": 0.0, "turnover": None},
    ]
    out = ks._format_giro(data, "mês")
    assert "n/d" in out


# ─── fetch_and_format: validação de tópico ───────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_and_format_topico_desconhecido_levanta():
    with pytest.raises(ValueError):
        await ks.fetch_and_format(None, "inexistente", "mes")
