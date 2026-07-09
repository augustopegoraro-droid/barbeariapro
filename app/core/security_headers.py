# file: app/core/security_headers.py
"""Middleware de cabeçalhos de segurança HTTP (V12 — nem a app nem o nginx
enviavam HSTS/CSP/X-Frame-Options/etc.).

CSP fica de fora de `/docs`/`/redoc` (Swagger/Redoc carregam script/CSS de
CDN) — só relevante quando `settings.docs_enabled=True` (dev/staging); em
produção esses paths nem existem (404), então a exceção é inerte lá.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if request.url.path not in _DOCS_PATHS:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response
