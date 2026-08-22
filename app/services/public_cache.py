# file: app/services/public_cache.py
"""Sincronização do site público com o painel (D-84).

O site público (`barbearia-public/`, D-79/D-82) lê a vitrine de
`GET /public/{subdomain}/info`, que passa por DUAS camadas de cache:

1. **Redis** (`public_info:{org_id}`, TTL 60s) — no backend, em `app/api/public.py`.
2. **ISR do Next** (`export const revalidate` na home e em `/agendar`) — o site
   guarda o HTML/fetch renderizado por até 5 min.

Sem invalidação, cadastrar um profissional (ou serviço/horário) no painel só
aparecia no site minutos depois. Este módulo é a porta única de invalidação:
apaga a chave do Redis e dispara a *on-demand revalidation* do Next
(`POST {PUBLIC_SITE_INTERNAL_URL}/api/revalidate`, autenticada por
`PUBLIC_REVALIDATE_SECRET`, que invalida a tag `public-info`).

Regras:
- **Nunca derruba a escrita do painel.** Toda falha é engolida e logada — o pior
  caso é o comportamento antigo (o site atualiza no vencimento do TTL).
- Chamar sempre via `BackgroundTasks` do FastAPI: roda DEPOIS da resposta (logo,
  depois do commit de `get_tenant_db`), então a vitrine nunca é recacheada com o
  estado anterior, e o gestor não espera a rede do site responder.
- Sem `PUBLIC_SITE_INTERNAL_URL`/`PUBLIC_REVALIDATE_SECRET` configurados, só o
  Redis é invalidado (dev local sem o site no ar, staging).
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx

from app.core.config import settings
from app.db.redis import get_redis

logger = logging.getLogger(__name__)

INFO_CACHE_TTL_SECONDS = 60
FEED_CACHE_TTL_SECONDS = 60
PLANS_CACHE_TTL_SECONDS = 60
REVALIDATE_TAG = "public-info"
FEED_TAG = "public-feed"
# Planos de assinatura vendidos no site (Stripe Connect, Feature 2). A lista
# depende do `charges_enabled` da org, então o webhook `account.updated` e o
# `POST /connect/sync` invalidam esta tag junto com a vitrine.
PLANS_TAG = "public-plans"
_REVALIDATE_TIMEOUT_SECONDS = 5.0


def info_cache_key(org_id: int) -> str:
    return f"public_info:{org_id}"


def feed_cache_key(org_id: int) -> str:
    return f"public_feed:{org_id}"


def plans_cache_key(org_id: int) -> str:
    return f"public_plans:{org_id}"


# Cada tag conhecida tem (no máximo) uma chave Redis correspondente no backend.
# A tag também é o que o Next revalida (ISR). Tag desconhecida = só ignorada
# aqui e recusada pela allowlist do route handler — nunca invalida "tudo".
_TAG_KEYS: dict[str, Callable[[int], str]] = {
    REVALIDATE_TAG: info_cache_key,
    FEED_TAG: feed_cache_key,
    PLANS_TAG: plans_cache_key,
}


async def invalidate_public_tags(org_id: int, tags: list[str]) -> None:
    """Invalida as tags do site público da org nas duas camadas de cache.

    Registrar em `BackgroundTasks` em qualquer escrita que mude o que o site
    mostra. Toda falha é engolida e logada — o pior caso é o comportamento
    antigo (o site atualiza no vencimento do TTL).
    """
    keys = [_TAG_KEYS[t](org_id) for t in tags if t in _TAG_KEYS]
    if keys:
        try:
            await get_redis().delete(*keys)
        except Exception:  # pragma: no cover — Redis fora não pode quebrar o painel
            logger.warning(
                "public_cache: falha ao invalidar Redis da org %s", org_id, exc_info=True
            )

    if tags and settings.public_site_internal_url and settings.public_revalidate_secret:
        await _revalidate_site(tags)


async def invalidate_public_info(org_id: int) -> None:
    """Invalida a vitrine (`GET /public/{sub}/info`).

    Wrapper fino sobre `invalidate_public_tags` — é o que os ~10 call-sites do
    painel (profissionais, serviços, horários, visibilidade) chamam.
    """
    await invalidate_public_tags(org_id, [REVALIDATE_TAG])


async def _revalidate_site(tags: list[str]) -> None:
    url = f"{settings.public_site_internal_url.rstrip('/')}/api/revalidate"
    try:
        async with httpx.AsyncClient(timeout=_REVALIDATE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                headers={"X-Revalidate-Secret": settings.public_revalidate_secret},
                # `tag` (singular) segue no corpo para o caso de o site antigo
                # ainda estar no ar durante o deploy; o novo lê `tags`.
                json={"tags": tags, "tag": tags[0]},
            )
        if resp.status_code >= 400:
            logger.warning("public_cache: revalidate do site devolveu %s", resp.status_code)
    except Exception:
        logger.warning("public_cache: falha ao revalidar o site público", exc_info=True)
