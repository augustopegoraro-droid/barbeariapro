"""Integração dos pedidos de remarcação (barbeiro cria → gestor aprova).

Usa `auth_headers` (owner = gestor) e `barber_headers` (barbeiro) do conftest;
skip gracioso sem DB semeado.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_barbeiro_cria_pedido(client, barber_headers):
    r = await client.post(
        "/remarcacoes",
        json={"reason": "Não posso trabalhar sexta à tarde"},
        headers=barber_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pendente"
    assert body["barber_id"] > 0
    assert body["source"] == "app"


async def test_gestor_lista_e_conta_pendentes(client, barber_headers, auth_headers):
    # cria um pedido como barbeiro
    await client.post(
        "/remarcacoes", json={"reason": "pedido p/ contagem"}, headers=barber_headers
    )
    # gestor lista pendentes
    r = await client.get("/remarcacoes?status=pendente", headers=auth_headers)
    assert r.status_code == 200, r.text
    lst = r.json()
    assert isinstance(lst, list) and len(lst) >= 1
    assert all(item["status"] == "pendente" for item in lst)
    # badge do sino
    c = await client.get("/remarcacoes/pendentes/count", headers=auth_headers)
    assert c.status_code == 200, c.text
    assert c.json()["count"] >= 1


async def test_barbeiro_nao_pode_listar(client, barber_headers):
    r = await client.get("/remarcacoes", headers=barber_headers)
    assert r.status_code == 403, r.text


async def test_nao_barbeiro_nao_cria(client, auth_headers):
    # owner não tem barber_id → não solicita remarcação.
    r = await client.post("/remarcacoes", json={"reason": "x"}, headers=auth_headers)
    assert r.status_code == 403, r.text


async def test_gestor_aprova_e_reaprovar_da_conflito(client, barber_headers, auth_headers):
    created = await client.post(
        "/remarcacoes", json={"reason": "aprovar este"}, headers=barber_headers
    )
    rid = created.json()["id"]

    ok = await client.patch(
        f"/remarcacoes/{rid}",
        json={"approve": True, "note": "beleza"},
        headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "aprovada"
    assert body["reviewed_by_user_id"] is not None
    assert body["reviewed_at"] is not None

    # decidir de novo → 409
    again = await client.patch(
        f"/remarcacoes/{rid}", json={"approve": False}, headers=auth_headers
    )
    assert again.status_code == 409, again.text


async def test_barbeiro_nao_pode_aprovar(client, barber_headers):
    created = await client.post(
        "/remarcacoes", json={"reason": "tentar aprovar sozinho"}, headers=barber_headers
    )
    rid = created.json()["id"]
    r = await client.patch(
        f"/remarcacoes/{rid}", json={"approve": True}, headers=barber_headers
    )
    assert r.status_code == 403, r.text

# Nota: o disparo de remarcação VIA Kernel IA (texto livre → tool) depende do LLM
# (OPENAI_API_KEY válida) e não é determinístico → coberto manualmente, não aqui.
# O fluxo de dados de /remarcacoes é validado deterministicamente pelos testes acima.
