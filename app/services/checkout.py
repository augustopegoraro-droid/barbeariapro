"""Alocação do split de pagamento do checkout único (D-105/D-106).

`allocate_payments` é pura (sem DB): recebe a lista de pagamentos informada
pela recepção (split livre: dinheiro, cartão com bandeira/tipo, Pix, saldo da
carteira) e distribui em ORDEM (FIFO) entre 3 baldes — serviço, produtos,
gorjeta — cada pagamento cobrindo primeiro o que resta do serviço, depois
produtos, depois gorjeta.

A soma dos pagamentos NÃO precisa bater exatamente com o total geral (D-106):
- **Pagou a mais** (troco): o que sobra depois de cobrir serviço+produtos+
  gorjeta vira `overpayment` — o chamador credita a diferença na carteira do
  cliente (em vez de devolver troco físico). Uma linha que já É a própria
  carteira (`credito_cliente`) nunca gera `overpayment` — não existe "troco"
  de um pagamento que não é dinheiro/cartão/pix real, e contar geraria
  crédito fantasma (debitar X do saldo e creditar de volta o excedente que
  nunca foi de fato debitado).
- **Pagou a menos:** o que falta cobrir depois de esgotar todas as linhas
  vira `underpayment` — o chamador registra a diferença como saldo devedor
  na carteira do cliente (fiado), sem checar saldo disponível.

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
    # D-106: divergência entre o que foi pago e o total geral.
    overpayment: Decimal = Decimal("0")   # pagou a mais -> vira crédito
    underpayment: Decimal = Decimal("0")  # pagou a menos -> vira saldo devedor


def allocate_payments(
    payments: list[PaymentLineIn],
    *,
    service_total: Decimal,
    product_total: Decimal,
    tip_total: Decimal,
) -> Allocation:
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
        if amt > 0 and p.method != PaymentMethod.credito_cliente:
            alloc.overpayment += amt

    alloc.underpayment = remaining_service + remaining_product + remaining_tip
    return alloc
