# file: app/db/redis.py
"""Cliente Redis assíncrono singleton (D-68, Fase 3).

Uso: rate-limit/lockout de login, tickets de SSE de uso único, denylist curta
de `jti` no logout. Dado 100% efêmero — nunca é a fonte de verdade de sessão
(isso é a tabela `sessions` no Postgres, ver models/user_session.py). Perder o
Redis degrada (contadores zeram, tickets pendentes somem) mas não compromete
uma sessão válida.
"""

from __future__ import annotations

import asyncio

from redis import asyncio as redis_asyncio

from app.core.config import settings

_redis: redis_asyncio.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def get_redis() -> redis_asyncio.Redis:
    """Cliente Redis compartilhado do processo (lazy, uma conexão pool).

    Recria o client se o event loop atual mudou desde a última chamada. Em
    produção (uvicorn, um loop pro processo inteiro) isso nunca dispara — é
    puro custo zero. Mas a suíte de testes cria um event loop NOVO por teste
    (pytest-asyncio); sem isto, o client ficava preso ao loop do 1º teste que
    o tocasse e as chamadas seguintes travavam/degradavam (conexão órfã de um
    loop fechado), deixando a suíte inteira lenta a partir do 1º uso.
    """
    global _redis, _redis_loop
    loop = asyncio.get_event_loop()
    if _redis is None or _redis_loop is not loop:
        _redis = redis_asyncio.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=3
        )
        _redis_loop = loop
    return _redis
