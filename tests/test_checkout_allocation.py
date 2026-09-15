"""Alocação pura do split de pagamento do checkout único (D-105/D-106).

Sem DB: `allocate_payments` distribui a lista de pagamentos em ordem (FIFO)
entre serviço, produtos e gorjeta. Divergência de valor não é mais erro
(D-106): pagou a mais -> `overpayment` (vira crédito); pagou a menos ->
`underpayment` (vira saldo devedor).
"""

from __future__ import annotations

from decimal import Decimal

from app.services.checkout import PaymentLineIn, allocate_payments
from models import CardBrand, CardType, PaymentMethod


def test_soma_batendo_um_metodo_so():
    alloc = allocate_payments(
        [PaymentLineIn(Decimal("70"), PaymentMethod.pix)],
        service_total=Decimal("50"),
        product_total=Decimal("20"),
        tip_total=Decimal("0"),
    )
    assert sum(l.amount for l in alloc.service_lines) == Decimal("50")
    assert sum(l.amount for l in alloc.product_lines) == Decimal("20")
    assert alloc.tip_amount == Decimal("0")


def test_split_dinheiro_e_cartao_cobrindo_servico_produto_e_gorjeta():
    alloc = allocate_payments(
        [
            PaymentLineIn(Decimal("50"), PaymentMethod.dinheiro),
            PaymentLineIn(Decimal("20"), PaymentMethod.cartao, CardType.credito, CardBrand.visa),
        ],
        service_total=Decimal("50"),
        product_total=Decimal("15"),
        tip_total=Decimal("5"),
    )
    assert [l.amount for l in alloc.service_lines] == [Decimal("50")]
    assert [l.amount for l in alloc.product_lines] == [Decimal("15")]
    assert alloc.tip_amount == Decimal("5")
    assert alloc.tip_method == PaymentMethod.cartao
    assert alloc.tip_card_brand == CardBrand.visa


def test_pagou_a_menos_vira_underpayment():
    alloc = allocate_payments(
        [PaymentLineIn(Decimal("10"), PaymentMethod.dinheiro)],
        service_total=Decimal("50"),
        product_total=Decimal("0"),
        tip_total=Decimal("0"),
    )
    assert [l.amount for l in alloc.service_lines] == [Decimal("10")]
    assert alloc.underpayment == Decimal("40")
    assert alloc.overpayment == Decimal("0")


def test_pagou_a_mais_vira_overpayment():
    alloc = allocate_payments(
        [PaymentLineIn(Decimal("60"), PaymentMethod.dinheiro)],
        service_total=Decimal("50"),
        product_total=Decimal("0"),
        tip_total=Decimal("0"),
    )
    assert [l.amount for l in alloc.service_lines] == [Decimal("50")]
    assert alloc.overpayment == Decimal("10")
    assert alloc.underpayment == Decimal("0")


def test_excedente_de_pagamento_com_carteira_nao_vira_credito_fantasma():
    # Selecionar mais saldo do que o necessário não gera crédito de volta —
    # só o que realmente foi alocado (50) é debitado da carteira depois.
    alloc = allocate_payments(
        [PaymentLineIn(Decimal("60"), PaymentMethod.credito_cliente)],
        service_total=Decimal("50"),
        product_total=Decimal("0"),
        tip_total=Decimal("0"),
    )
    assert [l.amount for l in alloc.service_lines] == [Decimal("50")]
    assert alloc.overpayment == Decimal("0")
    assert alloc.underpayment == Decimal("0")


def test_gorjeta_sem_pagamento_de_servico_usa_carteira():
    # Serviço 100% pago por assinatura (service_total=0); só gorjeta em carteira.
    alloc = allocate_payments(
        [PaymentLineIn(Decimal("5"), PaymentMethod.credito_cliente)],
        service_total=Decimal("0"),
        product_total=Decimal("0"),
        tip_total=Decimal("5"),
    )
    assert alloc.service_lines == []
    assert alloc.product_lines == []
    assert alloc.tip_amount == Decimal("5")
    assert alloc.tip_method == PaymentMethod.credito_cliente


def test_multiplos_metodos_cobrindo_so_produtos():
    alloc = allocate_payments(
        [
            PaymentLineIn(Decimal("10"), PaymentMethod.pix),
            PaymentLineIn(Decimal("10"), PaymentMethod.dinheiro),
        ],
        service_total=Decimal("0"),
        product_total=Decimal("20"),
        tip_total=Decimal("0"),
    )
    assert len(alloc.product_lines) == 2
    assert sum(l.amount for l in alloc.product_lines) == Decimal("20")
