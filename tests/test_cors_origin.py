# file: tests/test_cors_origin.py
"""CORS: a regex de origem cobre apex + subdomínios de tenant e barra forasteiros.

Valida o padrão recomendado para `CORS_ORIGIN_REGEX` no .env de produção — o
multi-tenant serve cada org num subdomínio (`<org>.taylorethedy.com`) e o apex
é o portal do cliente final, então uma allowlist fixa não escala.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

# Padrão de referência para CORS_ORIGIN_REGEX: apex taylorethedy.com + qualquer
# subdomínio de um nível (tenant/admin/api). Ancorado (fullmatch) e só https.
TENANT_ORIGIN_REGEX = r"https://([a-z0-9-]+\.)?taylorethedy\.com"


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_origin_regex=TENANT_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def _preflight(origin: str):
    return _client().options(
        "/ping",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


@pytest.mark.parametrize(
    "origin",
    [
        "https://taylorethedy.com",         # apex (portal do cliente final)
        "https://taylor.taylorethedy.com",  # tenant atual
        "https://org.taylorethedy.com",     # tenant futuro (slug renomeado)
        "https://admin.taylorethedy.com",   # superadmin
        "http://localhost:3000",            # dev (lista explícita, não a regex)
    ],
)
def test_origem_permitida(origin: str):
    resp = _preflight(origin)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.com",
        "https://taylorethedy.com.evil.com",  # sufixo forjado
        "https://eviltaylorethedy.com",       # prefixo colado
        "http://taylor.taylorethedy.com",     # http (a regex exige https)
    ],
)
def test_origem_barrada(origin: str):
    resp = _preflight(origin)
    # Preflight de origem não permitida: 400 e sem o header allow-origin.
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers
