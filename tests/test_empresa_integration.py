"""
Testes de integração do endpoint de configuração da empresa (/empresa).

Cobrem: leitura agregada (org + unidade + horários + plano + uso), atualização
cadastral com round-trip (restaura o estado original), replace-all da grade de
horários com validação, e bloqueio de acesso para role barber (RBAC).

Rodam contra o Postgres semeado (org 3). Fixtures em tests/conftest.py.
"""
from __future__ import annotations

import os

import pytest

BARBER_EMAIL = os.environ.get("SEED_BARBER_EMAIL", "marciana@barbeariapro.com")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "senha123")
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))


async def _barber_headers(client):
    resp = await client.post(
        "/auth/login",
        json={
            "email": BARBER_EMAIL,
            "password": SEED_PASSWORD,
            "organization_id": SEED_ORG_ID,
        },
    )
    if resp.status_code != 200:
        pytest.skip("usuário barbeiro semeado indisponível")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ═══════════════════════════════════════════════════════════════
# GET /empresa — estrutura agregada
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_empresa_sem_token_401(client):
    resp = await client.get("/empresa")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_empresa_estrutura(client, auth_headers):
    resp = await client.get("/empresa", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) >= {
        "organization",
        "unit",
        "business_hours",
        "subscription",
        "usage",
    }
    assert body["organization"]["id"]
    assert isinstance(body["business_hours"], list)
    assert body["usage"]["barbers"] >= 0
    assert body["usage"]["units"] >= 0
    # Org 3 tem ao menos uma unidade e uma assinatura (MVP) no seed.
    assert body["unit"] is not None
    if body["subscription"] is not None:
        assert body["subscription"]["plan"]["name"]
        assert body["subscription"]["plan"]["max_barbers"] > 0


# ═══════════════════════════════════════════════════════════════
# PATCH /empresa — round-trip cadastral
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_patch_empresa_atualiza_e_restaura(client, auth_headers):
    original = (await client.get("/empresa", headers=auth_headers)).json()[
        "organization"
    ]
    try:
        edited = await client.patch(
            "/empresa",
            headers=auth_headers,
            json={"phone": "+55 63 98888-0000", "instagram": "@taylorethedy"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["phone"] == "+55 63 98888-0000"
        assert edited.json()["instagram"] == "@taylorethedy"
        # string vazia limpa o campo (vira null)
        cleared = await client.patch(
            "/empresa", headers=auth_headers, json={"instagram": ""}
        )
        assert cleared.json()["instagram"] is None
    finally:
        await client.patch(
            "/empresa",
            headers=auth_headers,
            json={
                "phone": original["phone"],
                "instagram": original["instagram"],
            },
        )


# ═══════════════════════════════════════════════════════════════
# PUT /empresa/horarios — replace-all + validação
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_put_horarios_replace_e_restaura(client, auth_headers):
    original = (await client.get("/empresa", headers=auth_headers)).json()[
        "business_hours"
    ]
    try:
        novo = [
            {"weekday": 1, "open_time": "09:00", "close_time": "18:00"},
            {"weekday": 2, "open_time": "09:00", "close_time": "12:00"},
        ]
        resp = await client.put(
            "/empresa/horarios", headers=auth_headers, json={"slots": novo}
        )
        assert resp.status_code == 200, resp.text
        weekdays = sorted(s["weekday"] for s in resp.json())
        assert weekdays == [1, 2]

        # confirma persistência via GET
        check = (await client.get("/empresa", headers=auth_headers)).json()
        assert sorted(s["weekday"] for s in check["business_hours"]) == [1, 2]
    finally:
        # restaura o conjunto original (normaliza HH:MM:SS → HH:MM)
        restore = [
            {
                "weekday": s["weekday"],
                "open_time": s["open_time"][:5],
                "close_time": s["close_time"][:5],
            }
            for s in original
        ]
        await client.put(
            "/empresa/horarios", headers=auth_headers, json={"slots": restore}
        )


@pytest.mark.asyncio
async def test_put_horarios_fechamento_invalido_422(client, auth_headers):
    resp = await client.put(
        "/empresa/horarios",
        headers=auth_headers,
        json={"slots": [{"weekday": 1, "open_time": "18:00", "close_time": "09:00"}]},
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════
# RBAC — barber não acessa configuração da empresa
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_barber_nao_acessa_empresa_403(client):
    headers = await _barber_headers(client)
    resp = await client.get("/empresa", headers=headers)
    assert resp.status_code == 403
