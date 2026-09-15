"""Alocação pura do split de pagamento do checkout único (D-105).

Sem DB: `allocate_payments` distribui a lista de pagamentos em ordem (FIFO)
entre serviço, produtos e gorjeta.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

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


def test_soma_nao_bate_levanta_value_error():
    with pytest.raises(ValueError):
        allocate_payments(
            [PaymentLineIn(Decimal("10"), PaymentMethod.dinheiro)],
            service_total=Decimal("50"),
            product_total=Decimal("0"),
            tip_total=Decimal("0"),
        )


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
