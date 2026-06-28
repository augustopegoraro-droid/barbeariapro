"""Backfill da fidelidade por pontos (Fase 2).

Converte o histórico de cada cliente em pontos, SEM regressão de tier:

1. `recalculate()` credita 1 'earn' por atendimento concluído (idempotente) e
   materializa saldo + tier — semeia tiers/regras default por org (lazy).
2. Piso anti-regressão: o cliente nunca cai abaixo do tier equivalente ao seu
   `nivel`/`categoria` legados. Se os pontos do histórico ficarem abaixo desse
   piso, lança 1 'adjust' (reason 'backfill: preservar tier') para alcançá-lo.

Idempotente: re-rodar não duplica earns (UNIQUE no ledger) nem re-aplica o piso
(checa o saldo atual). Usa ADMIN_DATABASE_URL (role dono, RLS não se aplica).

Uso:
    set -a; . ./.env.staging; set +a
    .venv/bin/python -m scripts.backfill_loyalty_points
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

# Permite rodar como `python scripts/backfill_loyalty_points.py` (repo root no path).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.services import loyalty as loyalty_svc  # noqa: E402
from models.enums import LoyaltyCategoria, LoyaltyNivel  # noqa: E402
from models.loyalty import ClientLoyalty, LoyaltyTier  # noqa: E402

# nivel/categoria legados → nome do tier default equivalente (piso anti-regressão)
_NIVEL_TIER = {
    LoyaltyNivel.novo: "Bronze",
    LoyaltyNivel.ativo: "Prata",
    LoyaltyNivel.fiel: "Ouro",
    LoyaltyNivel.vip: "Diamante",
}
_CATEGORIA_TIER = {
    LoyaltyCategoria.bronze: "Bronze",
    LoyaltyCategoria.prata: "Prata",
    LoyaltyCategoria.ouro: "Ouro",
    LoyaltyCategoria.diamante: "Diamante",
}


def _floor_min_points(
    nivel: Optional[LoyaltyNivel], categoria: Optional[LoyaltyCategoria], tiers: list[LoyaltyTier]
) -> int:
    by_name = {t.name: t.min_points for t in tiers}
    floor = 0
    if nivel is not None:
        floor = max(floor, by_name.get(_NIVEL_TIER.get(nivel, "Bronze"), 0))
    if categoria is not None:
        floor = max(floor, by_name.get(_CATEGORIA_TIER.get(categoria, "Bronze"), 0))
    return floor


async def run() -> dict[str, int]:
    url = os.environ.get("ADMIN_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Defina ADMIN_DATABASE_URL (ou DATABASE_URL).")
    engine = create_async_engine(url)
    processed = 0
    floored = 0
    try:
        async with AsyncSession(engine) as session:
            rows = (
                await session.execute(
                    select(
                        ClientLoyalty.client_id,
                        ClientLoyalty.organization_id,
                        ClientLoyalty.nivel,
                        ClientLoyalty.categoria,
                    )
                )
            ).all()
            for client_id, org_id, nivel, categoria in rows:
                loyalty = await loyalty_svc.recalculate(client_id, org_id, session)
                tiers = await loyalty_svc.get_or_seed_tiers(org_id, session)
                floor = _floor_min_points(nivel, categoria, tiers)
                if loyalty.points_balance < floor:
                    await loyalty_svc.adjust_points(
                        org_id,
                        client_id,
                        floor - loyalty.points_balance,
                        "backfill: preservar tier",
                        session,
                    )
                    floored += 1
                processed += 1
            await session.commit()
    finally:
        await engine.dispose()
    return {"processed": processed, "floored": floored}


if __name__ == "__main__":
    result = asyncio.run(run())
    print(f"Backfill concluído: {result['processed']} clientes, {result['floored']} com piso aplicado.")
