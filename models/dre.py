"""Linhas mensais do DRE — histórico financeiro migrado da Trinks (migration 0036).

Cada linha é UM item do Demonstrativo de Resultado (DRE) mensal exportado da
Trinks: uma linha-folha (ex.: "Serviços", "Aluguel", "Vale/Adiantamento
Profissional") com o valor de UM mês (`competence_month`). É histórico ANALÍTICO
por **competência** — NÃO se vincula a `payments`/`appointments`. São lentes
diferentes: DRE = competência contábil; `payment_transactions`/`cash_daily_closings`
= recebimento (não reconciliar 1:1). Serve ao dashboard executivo: receita por
tipo, despesa por categoria, custo fixo × variável, lucro/margem e evolução mensal.

Só as **linhas-folha** são guardadas; subtotais e totais do arquivo são recomputados
(evita dupla contagem). `amount` pode ser NEGATIVO (contra-receita, ex.: "Consumo de
Pré-pago") — por isso sem CHECK de sinal, no molde de `payment_transactions`. Despesa
é positiva. Mesmo molde de RLS/GRANT das 0026/0035. Idempotência por substituição de
período (delete + insert dos meses cobertos pelo arquivo).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization


class DreMonthlyLine(Base):
    __tablename__ = "dre_monthly_lines"
    __table_args__ = (
        CheckConstraint("section IN ('receita', 'despesa')", name="dre_section_valid"),
        Index("idx_dre_monthly_lines_org_month", "organization_id", "competence_month"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # 1º dia do mês de competência (ex.: 2025-10-01 p/ "outubro / 2025").
    competence_month: Mapped[date] = mapped_column(Date, nullable=False)
    # 'receita' | 'despesa' (CHECK dre_section_valid).
    section: Mapped[str] = mapped_column(Text, nullable=False)
    # Só despesa: fixa/variavel/pessoal/impostos/outros (slug do subgrupo). NULL p/ receita.
    subgroup: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Rótulo da linha-folha do DRE ("Serviços", "Aluguel", "SIMPLES NACIONAL"...).
    line_item: Mapped[str] = mapped_column(Text, nullable=False)
    # Valor do mês; pode ser negativo (contra-receita). Despesa é positiva.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'trinks'")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
