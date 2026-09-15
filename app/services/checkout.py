"""Alocação do split de pagamento do checkout único de atendimento
(`app/api/barbeiro.py::concluir_atendimento`).

`allocate_payments` é pura (sem DB): recebe a lista de pagamentos informada
pela recepção (split livre: dinheiro, cartão com bandeira/tipo, Pix, saldo da
carteira) e distribui em ORDEM (FIFO) entre 3 baldes — serviço, produtos,
gorjeta — cada pagamento cobrindo primeiro o que resta do serviço, depois
produtos, depois gorjeta. A soma dos pagamentos precisa bater exatamente com
o total geral (serviço + produtos + gorjeta); senão levanta `ValueError` (o
chamador converte em 422).

A gorjeta é sempre um valor único (`Payment.tip_amount`), então só
guardamos o método/cartão do ÚLTIMO pagamento que a cobriu — cobre o caso
comum (1 método) e o caso raro de split cobrindo a gorjeta continua correto
em valor, só a rastreabilidade do "método da gorjeta" fica com a última linha.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from models import CardBrand, CardType, PaymentMethod


@dataclass(frozen=True)
class PaymentLineIn:
    amount: Decimal
    method: PaymentMethod
    card_type: Optional[CardType] = None
    card_brand: Optional[CardBrand] = None


@dataclass(frozen=True)
class AllocatedLine:
    amount: Decimal
    method: PaymentMethod
    card_type: Optional[CardType]
    card_brand: Optional[CardBrand]


@dataclass
class Allocation:
    service_lines: list[AllocatedLine] = field(default_factory=list)
    product_lines: list[AllocatedLine] = field(default_factory=list)
    tip_amount: Decimal = Decimal("0")
    tip_method: Optional[PaymentMethod] = None
    tip_card_type: Optional[CardType] = None
    tip_card_brand: Optional[CardBrand] = None


def allocate_payments(
    payments: list[PaymentLineIn],
    *,
    service_total: Decimal,
    product_total: Decimal,
    tip_total: Decimal,
) -> Allocation:
    grand_total = (service_total + product_total + tip_total).quantize(Decimal("0.01"))
    paid_total = sum((p.amount for p in payments), Decimal("0")).quantize(Decimal("0.01"))
    if paid_total != grand_total:
        raise ValueError(
            f"Soma dos pagamentos (R$ {paid_total}) não bate com o total geral (R$ {grand_total})."
        )

    alloc = Allocation()
    remaining_service = service_total
    remaining_product = product_total
    remaining_tip = tip_total

    for p in payments:
        amt = p.amount
        if amt <= 0:
            continue
        if remaining_service > 0:
            take = min(amt, remaining_service)
            alloc.service_lines.append(AllocatedLine(take, p.method, p.card_type, p.card_brand))
            remaining_service -= take
            amt -= take
        if amt > 0 and remaining_product > 0:
            take = min(amt, remaining_product)
            alloc.product_lines.append(AllocatedLine(take, p.method, p.card_type, p.card_brand))
            remaining_product -= take
            amt -= take
        if amt > 0 and remaining_tip > 0:
            take = min(amt, remaining_tip)
            alloc.tip_amount += take
            alloc.tip_method = p.method
            alloc.tip_card_type = p.card_type
            alloc.tip_card_brand = p.card_brand
            remaining_tip -= take
            amt -= take

    return alloc
