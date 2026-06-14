"""
Testes unitários das funções puras de fidelidade (CRM) — sem banco.

Cobrem a segmentação que alimenta dashboard, reativação e mensagens do bot.
Uma regressão aqui corrompe o CRM silenciosamente, por isso os limites de
cada faixa são fixados explicitamente.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from models.enums import LoyaltyCategoria, LoyaltyNivel, LoyaltyStatus


# ────────────────────────────────────────────────────────────
# compute_nivel — VIP > fiel > novo/ativo, VIP tem precedência
# ────────────────────────────────────────────────────────────

def test_nivel_novo_ate_uma_visita():
    from app.services.loyalty import compute_nivel
    assert compute_nivel(0, Decimal("0")) == LoyaltyNivel.novo
    assert compute_nivel(1, Decimal("0")) == LoyaltyNivel.novo


def test_nivel_ativo_entre_2_e_4_visitas_sem_gasto_alto():
    from app.services.loyalty import compute_nivel
    assert compute_nivel(2, Decimal("0")) == LoyaltyNivel.ativo
    assert compute_nivel(4, Decimal("149")) == LoyaltyNivel.ativo


def test_nivel_fiel_por_visitas_ou_gasto():
    from app.services.loyalty import compute_nivel
    assert compute_nivel(5, Decimal("0")) == LoyaltyNivel.fiel
    assert compute_nivel(0, Decimal("150")) == LoyaltyNivel.fiel
    # gasto >= 150 promove a fiel mesmo com 1 visita (não fica em 'novo')
    assert compute_nivel(1, Decimal("150")) == LoyaltyNivel.fiel
    assert compute_nivel(11, Decimal("499")) == LoyaltyNivel.fiel


def test_nivel_vip_por_gasto_ou_visitas_tem_precedencia():
    from app.services.loyalty import compute_nivel
    assert compute_nivel(0, Decimal("500")) == LoyaltyNivel.vip
    assert compute_nivel(12, Decimal("0")) == LoyaltyNivel.vip
    # 500 dispara VIP antes da regra de fiel
    assert compute_nivel(5, Decimal("500")) == LoyaltyNivel.vip


# ────────────────────────────────────────────────────────────
# compute_status — ativo<=60d, em_risco<=120d, inativo>120d
# ────────────────────────────────────────────────────────────

def _ago(days: int) -> datetime:
    # 12h de folga para o truncamento de `.days` cair na faixa pretendida
    return datetime.now(timezone.utc) - timedelta(days=days, hours=12)


def test_status_inativo_sem_visita():
    from app.services.loyalty import compute_status
    assert compute_status(None) == LoyaltyStatus.inativo


def test_status_ativo_ate_60_dias():
    from app.services.loyalty import compute_status
    assert compute_status(_ago(0)) == LoyaltyStatus.ativo
    assert compute_status(_ago(30)) == LoyaltyStatus.ativo
    assert compute_status(_ago(60)) == LoyaltyStatus.ativo


def test_status_em_risco_entre_61_e_120():
    from app.services.loyalty import compute_status
    assert compute_status(_ago(61)) == LoyaltyStatus.em_risco
    assert compute_status(_ago(120)) == LoyaltyStatus.em_risco


def test_status_inativo_acima_de_120():
    from app.services.loyalty import compute_status
    assert compute_status(_ago(121)) == LoyaltyStatus.inativo
    assert compute_status(_ago(400)) == LoyaltyStatus.inativo


def test_status_aceita_datetime_naive_como_utc():
    from app.services.loyalty import compute_status
    naive = datetime.utcnow() - timedelta(days=30)  # sem tzinfo
    assert compute_status(naive) == LoyaltyStatus.ativo


# ────────────────────────────────────────────────────────────
# compute_categoria — por contagem de visitas
# ────────────────────────────────────────────────────────────

def test_categoria_none_sem_visita():
    from app.services.loyalty import compute_categoria
    assert compute_categoria(0) is None


def test_categoria_faixas():
    from app.services.loyalty import compute_categoria
    assert compute_categoria(1) == LoyaltyCategoria.bronze
    assert compute_categoria(4) == LoyaltyCategoria.bronze
    assert compute_categoria(5) == LoyaltyCategoria.prata
    assert compute_categoria(9) == LoyaltyCategoria.prata
    assert compute_categoria(10) == LoyaltyCategoria.ouro
    assert compute_categoria(19) == LoyaltyCategoria.ouro
    assert compute_categoria(20) == LoyaltyCategoria.diamante
    assert compute_categoria(50) == LoyaltyCategoria.diamante


# ────────────────────────────────────────────────────────────
# resolve_benefit — melhor benefício entre nível e categoria
# ────────────────────────────────────────────────────────────

def test_benefit_pega_o_de_maior_prioridade():
    from app.services.loyalty import resolve_benefit
    # categoria diamante (1 corte) supera nível novo (sem benefício)
    assert resolve_benefit(LoyaltyNivel.novo, LoyaltyCategoria.diamante) == "1 corte gratuito"
    # nível VIP (10% produtos) supera categoria prata (café)
    assert resolve_benefit(LoyaltyNivel.vip, LoyaltyCategoria.prata) == "10% desconto em produtos"
    # diamante supera até VIP
    assert resolve_benefit(LoyaltyNivel.vip, LoyaltyCategoria.diamante) == "1 corte gratuito"


def test_benefit_sem_categoria_usa_nivel():
    from app.services.loyalty import resolve_benefit
    assert resolve_benefit(LoyaltyNivel.fiel, None) == "Café/bebida grátis"
    assert resolve_benefit(LoyaltyNivel.novo, None) == "Sem benefício"


def test_benefit_bronze_e_novo_sem_beneficio():
    from app.services.loyalty import resolve_benefit
    assert resolve_benefit(LoyaltyNivel.novo, LoyaltyCategoria.bronze) == "Sem benefício"


# ────────────────────────────────────────────────────────────
# next_milestone — mensagens de progresso
# ────────────────────────────────────────────────────────────

def test_milestone_cliente_novo():
    from app.services.loyalty import next_milestone
    m = next_milestone(0, Decimal("0"))
    assert "5 visita(s) para Prata" in m["categoria"]
    assert "2 visita(s) para Ativo" in m["nivel"]


def test_milestone_caminho_para_fiel():
    from app.services.loyalty import next_milestone
    m = next_milestone(3, Decimal("0"))
    assert "2 visita(s) para Prata" in m["categoria"]
    assert "para Fiel" in m["nivel"]


def test_milestone_caminho_para_vip():
    from app.services.loyalty import next_milestone
    m = next_milestone(5, Decimal("0"))
    assert "Ouro" in m["categoria"]  # faltam 5 para Ouro
    assert "para VIP" in m["nivel"]


def test_milestone_vip_e_categoria_maxima():
    from app.services.loyalty import next_milestone
    m = next_milestone(20, Decimal("600"))
    assert m["categoria"] == "Nível máximo de categoria atingido."
    assert m["nivel"] == "Nível VIP atingido."


def test_milestone_vip_por_gasto():
    from app.services.loyalty import next_milestone
    m = next_milestone(0, Decimal("500"))
    assert m["nivel"] == "Nível VIP atingido."
