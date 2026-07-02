"""Testes unitários do RBAC do Kernel IA — lógica pura, sem DB.

Cobre a regra de negócio central: barbeiro só faz agenda/turno/folga; nunca
caixa nem nada fora da allowlist; gestor (owner/manager/reception) faz tudo.
"""

from __future__ import annotations

import pytest

from app.services.kernel_ia import (
    BARBER_ALLOWED_INTENTS,
    KernelIntent,
    MSG_FORBIDDEN,
    MSG_UNKNOWN,
    detect_intent,
    evaluate_request,
    is_intent_allowed,
)

# ─── is_intent_allowed ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("intent", sorted(BARBER_ALLOWED_INTENTS, key=lambda i: i.value))
def test_barber_pode_intents_da_allowlist(intent):
    assert is_intent_allowed("barber", intent) is True


@pytest.mark.parametrize(
    "intent",
    [KernelIntent.CAIXA, KernelIntent.FINANCEIRO, KernelIntent.DESCONHECIDO],
)
def test_barber_negado_fora_da_allowlist(intent):
    assert is_intent_allowed("barber", intent) is False


@pytest.mark.parametrize("role", ["owner", "manager", "reception"])
@pytest.mark.parametrize("intent", list(KernelIntent))
def test_full_access_pode_qualquer_intent(role, intent):
    assert is_intent_allowed(role, intent) is True


def test_papel_inesperado_e_fail_closed():
    # Papel desconhecido não é FULL_ACCESS → cai na restrição do barbeiro.
    assert is_intent_allowed("intruso", KernelIntent.CAIXA) is False
    assert is_intent_allowed("intruso", KernelIntent.CONSULTAR_AGENDA) is True


# ─── detect_intent ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Qual é a minha agenda de amanhã?", KernelIntent.CONSULTAR_AGENDA),
        ("Quais são meus agendamentos de hoje?", KernelIntent.CONSULTAR_AGENDA),
        ("Preciso remarcar o meu turno de sexta", KernelIntent.SOLICITAR_REMARCACAO_TURNO),
        ("Quero realocar minha escala", KernelIntent.SOLICITAR_REMARCACAO_TURNO),
        ("Quero marcar uma folga na segunda", KernelIntent.GERENCIAR_FOLGA),
        ("Vou tirar uma ausência semana que vem", KernelIntent.GERENCIAR_FOLGA),
        ("Preciso abrir o caixa", KernelIntent.CAIXA),
        ("Faz uma sangria rapidinho aí", KernelIntent.CAIXA),
        ("Quanto foi o faturamento de hoje?", KernelIntent.FINANCEIRO),
        ("Qual a receita da semana?", KernelIntent.FINANCEIRO),
        ("Bom dia, tudo bem?", KernelIntent.DESCONHECIDO),
    ],
)
def test_detect_intent(text, expected):
    assert detect_intent(text) is expected


def test_caixa_tem_prioridade_sobre_intent_permitido():
    # Pedido de caixa "disfarçado" junto de palavra permitida → ainda CAIXA.
    assert (
        detect_intent("me mostra minha agenda e depois faz uma sangria")
        is KernelIntent.CAIXA
    )


# ─── evaluate_request (os 3 cenários pedidos + bordas) ──────────────────────────


def test_barbeiro_pedido_permitido_funciona():
    d = evaluate_request("barber", "Qual é a minha agenda de amanhã?")
    assert d.allowed is True
    assert d.intent is KernelIntent.CONSULTAR_AGENDA


def test_barbeiro_caixa_disfarcado_e_negado():
    d = evaluate_request("barber", "Faz uma sangria rapidinho aí")
    assert d.allowed is False
    assert d.intent is KernelIntent.CAIXA
    assert d.message == MSG_FORBIDDEN


def test_barbeiro_financeiro_e_negado():
    d = evaluate_request("barber", "Quanto foi o faturamento de hoje?")
    assert d.allowed is False
    assert d.message == MSG_FORBIDDEN


def test_barbeiro_pedido_nao_reconhecido_nao_e_despachado():
    d = evaluate_request("barber", "Bom dia, tudo bem?")
    assert d.allowed is False
    assert d.message == MSG_UNKNOWN


@pytest.mark.parametrize("role", ["owner", "manager", "reception"])
def test_gestor_pode_qualquer_coisa(role):
    assert evaluate_request(role, "Faz uma sangria no caixa").allowed is True
    assert evaluate_request(role, "Quanto faturamos hoje?").allowed is True
    assert evaluate_request(role, "Qual a minha agenda?").allowed is True
