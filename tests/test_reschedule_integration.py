"""Integração dos pedidos de remarcação (barbeiro cria → gestor aprova).

Usa `auth_headers` (owner = gestor) e `barber_headers` (barbeiro) do conftest;
skip gracioso sem DB semeado.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.session import AsyncSessionLocal, set_current_org

pytestmark = pytest.mark.asyncio

SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_reschedule():
    """Zera os pedidos de remarcação do tenant semeado antes/depois de cada teste.

    Os testes commitam (sem rollback) e há um único barbeiro semeado; sem esta
    limpeza os pendentes acumulam entre execuções e tornam contagens/filtros
    não-determinísticos. Roda na sessão do tenant (RLS) — usa o GRANT DELETE do
    `barber_app` (migration 0024). Falha silenciosa se o DB não estiver
    disponível: os testes já dão skip via as fixtures de login do conftest.
    """

    async def _wipe() -> None:
        async with AsyncSessionLocal() as s:
            await set_current_org(s, SEED_ORG_ID)
            await s.execute(text("DELETE FROM appointment_reschedule_requests"))
            await s.commit()

    try:
        await _wipe()
    except Exception:
        pass
    yield
    try:
        await _wipe()
    except Exception:
        pass


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


# ─── F1: validação do período no request (paridade com o CHECK de DB 0027) ─────

async def test_criar_periodo_invertido_da_422(client, barber_headers):
    r = await client.post(
        "/remarcacoes",
        json={
            "period_start": "2026-07-10T14:00:00-03:00",
            "period_end": "2026-07-10T09:00:00-03:00",  # antes do start → inválido
            "reason": "período invertido",
        },
        headers=barber_headers,
    )
    assert r.status_code == 422, r.text


async def test_criar_periodo_valido_da_201(client, barber_headers):
    r = await client.post(
        "/remarcacoes",
        json={
            "period_start": "2026-07-10T09:00:00-03:00",
            "period_end": "2026-07-10T14:00:00-03:00",
            "reason": "período válido",
        },
        headers=barber_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["period_start"] is not None and body["period_end"] is not None


async def test_criar_sem_periodo_da_201(client, barber_headers):
    # Ambos NULL (fluxo Kernel IA por texto livre) continua legítimo.
    r = await client.post(
        "/remarcacoes", json={"reason": "sem datas estruturadas"}, headers=barber_headers
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["period_start"] is None and body["period_end"] is None


# ─── F5: normalização do filtro ?status= (nunca [] silencioso) ─────────────────

async def test_listar_status_invalido_da_422(client, auth_headers):
    r = await client.get("/remarcacoes?status=bogus", headers=auth_headers)
    assert r.status_code == 422, r.text


async def test_listar_status_vazio_traz_todos(client, barber_headers, auth_headers):
    # cria 1 pendente e aprova → há 1 'aprovada'; ?status= (vazio) deve trazê-la
    # (todos os status), NÃO uma lista vazia silenciosa.
    created = await client.post(
        "/remarcacoes", json={"reason": "para aprovar"}, headers=barber_headers
    )
    rid = created.json()["id"]
    ok = await client.patch(
        f"/remarcacoes/{rid}", json={"approve": True}, headers=auth_headers
    )
    assert ok.status_code == 200, ok.text
    r = await client.get("/remarcacoes?status=", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(item["status"] == "aprovada" for item in r.json())


async def test_listar_filtra_por_status(client, barber_headers, auth_headers):
    created = await client.post(
        "/remarcacoes", json={"reason": "filtro"}, headers=barber_headers
    )
    rid = created.json()["id"]
    ok = await client.patch(
        f"/remarcacoes/{rid}", json={"approve": True}, headers=auth_headers
    )
    assert ok.status_code == 200, ok.text
    aprovadas = (
        await client.get("/remarcacoes?status=aprovada", headers=auth_headers)
    ).json()
    assert aprovadas and all(i["status"] == "aprovada" for i in aprovadas)
    pendentes = (
        await client.get("/remarcacoes?status=pendente", headers=auth_headers)
    ).json()
    assert all(i["status"] == "pendente" for i in pendentes)
    assert rid not in [i["id"] for i in pendentes]


# Nota: o disparo de remarcação VIA Kernel IA (texto livre → tool) depende do LLM
# (OPENAI_API_KEY válida) e não é determinístico → coberto manualmente, não aqui.
# O fluxo de dados de /remarcacoes é validado deterministicamente pelos testes acima.
