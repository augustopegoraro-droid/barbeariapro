# file: app/core/rate_limit.py
"""Limiter compartilhado (slowapi + storage Redis) — V2.

Módulo separado (não `app.main`) para os routers importarem `limiter` sem
import circular. Storage Redis: contadores efêmeros, mesmo Redis do resto do
D-68 (rate-limit/lockout/tickets SSE/denylist).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Baseline global (todas as rotas, inclusive webhooks/imports) + limites mais
# apertados aplicados via @limiter.limit(...) nas rotas sensíveis (login,
# refresh, troca/reset de senha).
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=["300/minute"],
    enabled=settings.rate_limit_enabled,
)
