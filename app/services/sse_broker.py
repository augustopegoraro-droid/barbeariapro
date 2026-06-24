"""Broker SSE em memória — Fase 5.

Single-process only (asyncio). Cada organização tem um conjunto de filas
(uma por cliente SSE conectado). Ao escalar para múltiplos workers,
substituir por PostgreSQL LISTEN/NOTIFY (ver ARQUITETURA_CRM_DEFINITIVA §4.4).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

_logger = logging.getLogger(__name__)

# org_id → set de asyncio.Queue (uma por conexão SSE aberta)
_subs: dict[int, set[asyncio.Queue]] = defaultdict(set)


def subscribe(org_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subs[org_id].add(q)
    _logger.debug("sse subscribe org=%s total=%d", org_id, len(_subs[org_id]))
    return q


def unsubscribe(org_id: int, q: asyncio.Queue) -> None:
    _subs[org_id].discard(q)
    if not _subs[org_id]:
        del _subs[org_id]
    _logger.debug("sse unsubscribe org=%s total=%d", org_id, len(_subs.get(org_id, set())))


async def publish(org_id: int, event: dict[str, Any]) -> None:
    """Publica evento para todos os clientes SSE conectados da org."""
    queues = list(_subs.get(org_id, set()))
    if not queues:
        return
    for q in queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            _logger.warning("sse queue full org=%s, event dropped", org_id)
