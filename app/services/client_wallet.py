"""Carteira de crédito do cliente final — ledger append-only
(`client_wallet_movements`, migration 0068).

Saldo = `SUM(amount)` (ledger puro, sem coluna cacheada em `Client`). Toda
escrita passa por `credit`/`debit`/`reverse_reference` — nunca inserir
`ClientWalletMovement` fora deste módulo. Concorrência: não há uma linha
"mãe" pra travar com `FOR UPDATE` (é um ledger puro), então dois débitos
simultâneos do MESMO cliente são serializados por
`pg_advisory_xact_lock(client_id)` (mesmo padrão de `app/api/agenda.py`/
`app/services/membership.py` para numeração/uso atômico).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import ClientWalletMovement, ClientWalletMovementType


async def get_balance(db: AsyncSession, *, organization_id: int, client_id: int) -> Decimal:
    result = await db.execute(
        select(func.coalesce(func.sum(ClientWalletMovement.amount), 0)).where(
            ClientWalletMovement.organization_id == organization_id,
            ClientWalletMovement.client_id == client_id,
        )
    )
    return Decimal(result.scalar_one())


async def credit(
    db: AsyncSession,
    *,
    organization_id: int,
    client_id: int,
    amount: Decimal,
    movement_type: ClientWalletMovementType = ClientWalletMovementType.credito_manual,
    note: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    created_by_user_id: Optional[int] = None,
) -> ClientWalletMovement:
    if amount <= 0:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "O valor do crédito deve ser positivo.")
    movement = ClientWalletMovement(
        organization_id=organization_id,
        client_id=client_id,
        amount=amount,
        movement_type=movement_type,
        note=note,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(movement)
    await db.flush()
    return movement


async def debit(
    db: AsyncSession,
    *,
    organization_id: int,
    client_id: int,
    amount: Decimal,
    reference_type: str,
    reference_id: int,
    created_by_user_id: Optional[int] = None,
) -> ClientWalletMovement:
    if amount <= 0:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "O valor do débito deve ser positivo.")

    await db.execute(text("SELECT pg_advisory_xact_lock(:client_id)"), {"client_id": client_id})

    balance = await get_balance(db, organization_id=organization_id, client_id=client_id)
    if balance < amount:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            f"Saldo insuficiente na carteira do cliente: R$ {balance} disponível, R$ {amount} solicitado.",
        )

    movement = ClientWalletMovement(
        organization_id=organization_id,
        client_id=client_id,
        amount=-amount,
        movement_type=ClientWalletMovementType.uso_pagamento,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(movement)
    await db.flush()
    return movement


async def refund(
    db: AsyncSession,
    *,
    organization_id: int,
    client_id: int,
    amount: Decimal,
    reference_type: str,
    reference_id: int,
    created_by_user_id: Optional[int] = None,
) -> ClientWalletMovement:
    """Devolve à carteira um valor pago com saldo (ex.: cancelamento de venda
    de produto). Diferente de `credit`: fica marcado como `estorno`, não
    `credito_manual` — distinção só de auditoria/relatório."""
    if amount <= 0:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "O valor do estorno deve ser positivo.")
    return await credit(
        db,
        organization_id=organization_id,
        client_id=client_id,
        amount=amount,
        movement_type=ClientWalletMovementType.estorno,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
