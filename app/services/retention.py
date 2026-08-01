"""Retenção de dado pessoal fora da trilha de auditoria (D-86).

A auditoria já tinha prazo (`organizations.audit_retention_months`, D-70). As
sessões — que guardam IP e user-agent, dado pessoal — não tinham nenhum: ficavam
para sempre. Aqui está a purga, chamada pelo mesmo cron interno que já roda a
purga da auditoria (`/internal/audit/purge`), para não criar um segundo
agendamento no n8n que alguém esqueceria de configurar.

Cross-org via `app_sessions_purge_expired` (SECURITY DEFINER, migration 0047):
o role da app é NOBYPASSRLS, então um DELETE sem tenant não veria nada.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

# Carência após revogar/expirar: janela para o gestor ainda enxergar "sessão
# revogada em X" na tela de dispositivos antes da linha sumir de vez.
GRACE_DAYS: Final[int] = 30
# Sessão de staff parada além disto já não autentica nada (refresh de 30d).
STAFF_IDLE_DAYS: Final[int] = 60
# Cookie do site público vive 400 dias; passado esse prazo + carência, some.
CLIENT_IDLE_DAYS: Final[int] = 430


async def purge_expired_sessions() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM app_sessions_purge_expired("
                        ":grace, :staff_idle, :client_idle)"
                    ),
                    {
                        "grace": GRACE_DAYS,
                        "staff_idle": STAFF_IDLE_DAYS,
                        "client_idle": CLIENT_IDLE_DAYS,
                    },
                )
            ).one()
            return {"staff_sessions": row.staff_deleted, "client_sessions": row.client_deleted}
