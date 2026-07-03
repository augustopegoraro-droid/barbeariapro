"""Testes unitários do texto de reativação — função pura, sem banco."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_reativacao_nao_cita_numero_exato_de_dias():
    from app.services.reactivation import _build_message
    msg = _build_message(
        name="João Silva",
        days_away=90,
        barber_name="Taylor",
        service_name="Corte",
        benefit="10% de desconto",
        business_name="Taylor & Thedy",
    )
    assert "90" not in msg  # número exato soa robótico / denuncia automação
    assert "Aqui é da *Taylor & Thedy*" in msg
    assert "Taylor" in msg
    assert "Corte" in msg
    assert "10% de desconto" in msg


def test_reativacao_varia_por_faixa_de_inatividade():
    from app.services.reactivation import _build_message
    recente = _build_message("Ana", 10, None, None, "Sem benefício")
    medio = _build_message("Ana", 60, None, None, "Sem benefício")
    longo = _build_message("Ana", 200, None, None, "Sem benefício")
    assert recente != medio
    assert medio != longo


def test_reativacao_sem_beneficio_omite_a_linha():
    from app.services.reactivation import _build_message
    msg = _build_message("Ana", 60, None, None, "Sem benefício")
    assert "mimo" not in msg
    assert "Sem benefício" not in msg


def test_reativacao_sem_business_name_mantem_saudacao_simples():
    from app.services.reactivation import _build_message
    msg = _build_message("Ana", 60, None, None, "Sem benefício")
    assert "Oi Ana!" in msg
    assert "Aqui é da" not in msg
