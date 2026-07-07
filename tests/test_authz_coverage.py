"""Teste de cobertura de autenticação — fecha a classe de bug "esqueci o guard".

Enumera todas as rotas do app e afirma que cada rota NÃO-pública tem, na sua
árvore de dependências, um ponto de autenticação conhecido (tenant/bot/plataforma).
Um endpoint novo sem auth faz este teste falhar (era a causa-raiz de V4/V7).
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.main import app

# Rotas propositalmente públicas ou que se autenticam DENTRO do handler.
PUBLIC_PATHS = {
    "/",
    "/health",
    "/health/db",
    "/auth/tenant",
    "/auth/login",
    "/platform/auth/login",      # login de plataforma (público, emite token)
    "/bot/wa-webhook",          # secret opcional (débito V1) — validação no handler
    "/chatwoot/webhook",         # token no handler (fail-closed)
    "/billing/webhooks/{provider_name}",  # assinatura do provider
    "/internal/billing/run-lifecycle",    # X-Bot-Token (secrets_match) no handler
    "/integracoes/google/calendar/callback",  # state JWT assinado
    "/crm/stream",               # autentica por ticket/token no handler (V4)
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

# Pontos de entrada de autenticação: se um deles aparece na árvore de deps da
# rota, ela está protegida (tenant JWT, bot token, ou plataforma).
AUTH_ENTRYPOINTS = {
    "get_tenant_db",
    "get_current_user",
    "get_auth_context",
    "get_bot_db",
    "_require_bot_token",
    "require_platform_admin",
    "_get_webhook_db",
}


def _callable_names(dependant) -> set[str]:
    names: set[str] = set()
    stack = [dependant]
    while stack:
        dep = stack.pop()
        if getattr(dep, "call", None) is not None:
            names.add(getattr(dep.call, "__name__", ""))
        stack.extend(getattr(dep, "dependencies", []))
    return names


def test_every_non_public_route_is_authenticated():
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in PUBLIC_PATHS:
            continue
        if not (_callable_names(route.dependant) & AUTH_ENTRYPOINTS):
            offenders.append(f"{sorted(route.methods)} {route.path}")
    assert not offenders, "rotas sem ponto de autenticação:\n" + "\n".join(offenders)
