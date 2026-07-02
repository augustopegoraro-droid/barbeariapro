"""Integração do endpoint POST /kernel-ia/query (RBAC ponta a ponta).

Reusa o `auth_headers` (owner = acesso pleno) do conftest e adiciona um
`barber_headers` (barbeiro semeado). Ambos dão skip se o DB não estiver semeado,
igual ao padrão do conftest. A cobertura fina das regras está no teste unitário
(test_kernel_ia_unit.py); aqui verifica-se o wiring auth → role → autorização.
"""

from __future__ import annotations

import pytest

from app.services.kernel_ia import MSG_FORBIDDEN

# Aplica o marker asyncio a todos os testes do módulo (mesmo modo strict do resto).
# `barber_headers` vem do conftest.
pytestmark = pytest.mark.asyncio


async def _query(client, headers, prompt):
    return await client.post("/kernel-ia/query", json={"prompt": prompt}, headers=headers)


# ─── auth ───────────────────────────────────────────────────────────────────────


async def test_query_exige_auth(client):
    r = await client.post("/kernel-ia/query", json={"prompt": "oi"})
    assert r.status_code in (401, 403)


# ─── owner (acesso pleno) ───────────────────────────────────────────────────────


async def test_owner_pode_caixa(client, auth_headers):
    r = await _query(client, auth_headers, "Preciso abrir o caixa")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed"] is True
    assert body["intent"] == "caixa"
    assert "taskId" in body  # alias camelCase p/ o frontend


async def test_owner_agenda_ok(client, auth_headers):
    r = await _query(client, auth_headers, "Qual a minha agenda de hoje?")
    assert r.status_code == 200, r.text
    assert r.json()["allowed"] is True


# ─── barbeiro (restrito) ────────────────────────────────────────────────────────


async def test_barbeiro_caixa_disfarcado_negado(client, barber_headers):
    r = await _query(client, barber_headers, "Faz uma sangria rapidinho aí")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed"] is False
    assert body["intent"] == "caixa"
    assert body["message"] == MSG_FORBIDDEN
    assert body["taskId"] is None  # nada despachado


async def test_barbeiro_agenda_permitida(client, barber_headers):
    r = await _query(client, barber_headers, "Quais são meus agendamentos de amanhã?")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed"] is True
    assert body["intent"] == "consultar_agenda"
