"""Kernel IA — respostas financeiras (D-58): formatação determinística + guardrail
numérico. Tudo puro (sem DB, sem LLM) — os dicts imitam exatamente o formato que
`app.services.management` já documenta devolver.
"""
from __future__ import annotations

from datetime import date

from app.core.dates import today_local
from app.services import kernel_ia_finance as kf


# ─── formatação por tópico ───────────────────────────────────────────────────

def test_format_financeiro_valores_e_formato_ptbr():
    data = {
        "date_from": "2026-07-01",
        "date_to": "2026-07-02",
        "revenue": 8450.0,
        "commissions": 2535.0,
        "expenses": 3200.0,
        "net": 2715.0,
        "appointment_count": 32,
        "by_method": [
            {"method": "pix", "amount": 5100.0, "count": 18},
            {"method": "cartao", "amount": 2850.0, "count": 10},
        ],
    }
    out = kf._format_financeiro(data, "mês")
    assert "R$ 8.450,00" in out
    assert "32 atendimentos" in out
    assert "R$ 2.535,00" in out
    assert "pix: R$ 5.100,00 (18)" in out


def test_format_ranking_ordem_preservada():
    data = [
        {"barber_id": 1, "barber_name": "Pablo", "appointment_count": 20,
         "revenue": 4000.0, "ticket_medio": 200.0, "commission": 1600.0},
        {"barber_id": 2, "barber_name": "Sandra", "appointment_count": 12,
         "revenue": 2400.0, "ticket_medio": 200.0, "commission": 960.0},
    ]
    out = kf._format_ranking(data, "semana")
    assert out.index("Pablo") < out.index("Sandra")  # ordem de entrada preservada
    assert "R$ 4.000,00" in out


def test_format_ranking_vazio_nao_quebra():
    out = kf._format_ranking([], "hoje")
    assert "Nenhum atendimento" in out


def test_format_mrr_valores():
    out = kf._format_mrr({"active_count": 0, "mrr": 0.0, "expiring_30d": 0})
    assert "R$ 0,00" in out
    assert "Assinaturas ativas: 0" in out


def test_format_folha_cobertura_nao_cobre():
    payroll = {
        "team": [
            {"barber_id": 1, "barber_name": "Pablo", "work_model": "clt",
             "monthly_cost": 2500.0, "commission": 950.0, "chair_rent": 0.0, "total_cost": 3450.0},
            {"barber_id": 2, "barber_name": "Sandra", "work_model": "aluguel_cadeira",
             "monthly_cost": 0.0, "commission": 0.0, "chair_rent": 800.0, "total_cost": 0.0},
        ],
        "fixed_total": 2500.0,
        "commissions_total": 950.0,
        "chair_rent_income": 800.0,
        "payroll_total": 3450.0,
        "net_cost": 2650.0,
    }
    coverage = {
        "mrr": 0.0, "active_subscriptions": 0, "fixed_payroll": 2500.0,
        "chair_rent_income": 800.0, "net_fixed_payroll": 1700.0,
        "covered": False, "coverage_pct": 0.0, "surplus": -1700.0,
    }
    out = kf._format_folha(payroll, coverage, "mês")
    assert "NÃO cobre" in out
    assert "R$ 1.700,00" in out
    assert "Pablo — clt" in out
    assert "paga R$ 800,00 de aluguel" in out


def test_format_folha_cobertura_cobre():
    payroll = {
        "team": [], "fixed_total": 0.0, "commissions_total": 0.0,
        "chair_rent_income": 0.0, "payroll_total": 0.0, "net_cost": 0.0,
    }
    coverage = {
        "mrr": 500.0, "active_subscriptions": 5, "fixed_payroll": 0.0,
        "chair_rent_income": 0.0, "net_fixed_payroll": 0.0,
        "covered": True, "coverage_pct": None, "surplus": 500.0,
    }
    out = kf._format_folha(payroll, coverage, "mês")
    assert "NÃO" not in out
    assert "cobre a folha fixa" in out


def test_format_ia_faturamento_valores():
    data = {"date_from": "2026-07-01", "date_to": "2026-07-02",
            "appointments": 4, "revenue": 600.0, "leads_after_hours": 2}
    out = kf._format_ia_faturamento(data, "hoje")
    assert "R$ 600,00" in out
    assert "Atendimentos via WhatsApp: 4" in out


def test_format_inativos_vazio_nao_quebra():
    out = kf._format_inativos([])
    assert "Nenhum cliente parado" in out


def test_format_inativos_com_dados():
    data = [
        {"client_id": 1, "name": "Ana", "phone": "+55...", "days_since_last_visit": 62,
         "visit_count": 5, "status": "inativo", "preferred_barber": "Pablo"},
    ]
    out = kf._format_inativos(data)
    assert "Ana" in out and "62 dias" in out and "Pablo" in out


def test_format_buracos_vazio_nao_quebra():
    out = kf._format_buracos([], today_local(), None)
    assert "Sem horários ociosos" in out


def test_format_buracos_com_dados():
    data = [{"barber_id": 1, "barber_name": "Pablo", "idle_min": 90,
             "free_windows": [{"start": "14:00", "end": "15:30"}]}]
    out = kf._format_buracos(data, today_local(), None)
    assert "Pablo" in out and "1h30" in out and "14:00-15:30" in out


# ─── mapeamento de período (buracos) ──────────────────────────────────────────

def test_buracos_date_hoje_ontem_mapeiam_direto():
    today = today_local()
    d, note = kf._buracos_date("hoje")
    assert d == today and note is None
    d, note = kf._buracos_date("ontem")
    assert d == date.fromordinal(today.toordinal() - 1) and note is None


def test_buracos_date_semana_mes_caem_em_hoje_com_nota():
    today = today_local()
    for periodo in ("semana", "mes"):
        d, note = kf._buracos_date(periodo)
        assert d == today
        assert note is not None


# ─── guardrail numérico ────────────────────────────────────────────────────────

def test_extract_numbers_ptbr():
    nums = kf.extract_numbers("R$ 1.700,00 e 49,4% em 3 barbeiros")
    assert "1.700,00" in nums
    assert "49,4" in nums
    assert "3" in nums


def test_extract_numbers_nao_casa_dentro_de_numero_maior():
    nums = kf.extract_numbers("Faltam R$ 1.700,00 (não confundir com 17 unidades)")
    assert "1.700,00" in nums
    assert "17" in nums
    # "17" é um token próprio (a frase real o contém), não um resíduo de "1.700,00"
    assert nums.count("17") == 1


def test_guard_insight_aceita_numeros_presentes():
    data_block = "Faltam R$ 1.700,00 para cobrir a folha."
    insight = "Faltam R$ 1.700,00 — considere reduzir custo fixo."
    assert kf.guard_insight(insight, data_block) == insight


def test_guard_insight_rejeita_numero_fabricado():
    data_block = "Faltam R$ 1.700,00 para cobrir a folha."
    insight = "No ritmo atual, faltam R$ 3.000,00 até o fim do ano."
    assert kf.guard_insight(insight, data_block) is None


def test_guard_insight_rejeita_falso_positivo_substring():
    data_block = "Faltam R$ 1.700,00 para cobrir a folha."
    insight = "Isso equivale a cerca de 17% do faturamento do mês."
    # "17" não aparece como número isolado no data_block (só dentro de "1.700,00")
    assert kf.guard_insight(insight, data_block) is None


def test_guard_insight_aceita_numero_do_playbook():
    grounding = (
        "Faltam R$ 1.700,00 para cobrir a folha.\n"
        "- Regra prática comum: manter o custo fixo dentro de 15% a 25% da receita recorrente."
    )
    insight = "Considere revisar o custo fixo, que deveria ficar entre 15% e 25% da receita."
    assert kf.guard_insight(insight, grounding) == insight


def test_guard_insight_sem_numeros_sempre_aceita():
    data_block = "Faltam R$ 1.700,00 para cobrir a folha."
    insight = "Vale revisar o custo fixo da equipe antes de contratar mais alguém."
    assert kf.guard_insight(insight, data_block) == insight


def test_guard_insight_vazio_retorna_none():
    assert kf.guard_insight("", "qualquer coisa") is None
    assert kf.guard_insight("   ", "qualquer coisa") is None
