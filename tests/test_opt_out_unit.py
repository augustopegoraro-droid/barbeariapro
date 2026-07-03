"""Testes unitários da detecção de opt-out — função pura, sem banco."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_keywords_disparam_optout():
    from app.services.opt_out import is_opt_out_keyword
    positivos = [
        "SAIR", "sair", "Parar", "PARE", "stop", "STOP", "unsubscribe",
        "descadastrar", "Não quero receber", "nao quero mais receber",
        "sair da lista", "cancelar inscrição", "remover meu número",
        "  Sair!  ", "*SAIR*", "sair.", "PARAR DE RECEBER",
    ]
    for msg in positivos:
        assert is_opt_out_keyword(msg) is True, f"deveria disparar: {msg!r}"


def test_frases_normais_nao_disparam():
    from app.services.opt_out import is_opt_out_keyword
    # Match exato evita falso positivo: nada disso deve descadastrar.
    negativos = [
        "Oi, quero agendar", "vou ter que sair mais cedo",
        "posso cancelar meu horário de amanhã?", "obrigado!", "sim",
        "quero marcar um corte", "pode parar de brincadeira kkk",
        "", None,
    ]
    for msg in negativos:
        assert is_opt_out_keyword(msg) is False, f"NÃO deveria disparar: {msg!r}"


def test_normalizacao_acentos_caixa_pontuacao():
    from app.services.opt_out import is_opt_out_keyword
    assert is_opt_out_keyword("SAIR DA LISTA") is True
    assert is_opt_out_keyword("Cancelar inscrição") is True   # acento
    assert is_opt_out_keyword("remover meu número") is True   # acento
    assert is_opt_out_keyword("  parar  ") is True            # espaços
