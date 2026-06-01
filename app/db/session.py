# file: app/db/session.py
"""Engine/sessão async e o ponto de integração com a RLS do schema.

`set_current_org` executa o equivalente a `SET LOCAL app.current_org_id`,
que as policies do schema leem via `current_setting('app.current_org_id')`.
O escopo é de TRANSAÇÃO (is_local=true), então o valor não vaza entre
requisições que reutilizam a mesma conexão do pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def set_current_org(session: AsyncSession, organization_id: int) -> None:
    """Define o tenant da transação corrente (parametrizado, sem interpolação)."""
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(organization_id)},
    )


async def get_db() -> AsyncIterator[AsyncSession]:
    """Sessão transacional SEM tenant pré-definido.

    Usada pelo login, que define o org a partir do corpo da requisição antes
    de consultar. Para rotas protegidas, use `get_tenant_db` em app/deps.py.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session
