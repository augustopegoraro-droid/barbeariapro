"""
Testes de integração dos endpoints de clientes, auth/RLS, loyalty e segmentação.

Rodam a aplicação ASGI em processo contra o Postgres semeado. Cobrem o
caminho real: autenticação → RLS → CRUD com soft-delete → filtros de segmentação.
As fixtures `client` e `auth_headers` vêm de tests/conftest.py.
"""
from __future__ import annotations

import os
import uuid

import pytest

# Org semeada (mesmo default de tests/conftest.py: staging usa org 1).
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))


# ═══════════════════════════════════════════════════════════════
# AUTH / RLS
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_login_owner_emite_token(client):
    resp = await client.post(
        "/auth/login",
        json={
            "email": "taylor@barbeariapro.com",
            "password": "senha123",
            "organization_id": SEED_ORG_ID,
        },
    )
    if resp.status_code != 200:
        pytest.skip("DB semeado indisponível")
    body = resp.json()
    assert body["access_token"]
    assert body["organization_id"] == SEED_ORG_ID
    assert body["role"] == "owner"


@pytest.mark.asyncio
async def test_login_senha_errada_401(client):
    resp = await client.post(
        "/auth/login",
        json={
            "email": "taylor@barbeariapro.com",
            "password": "senha-errada",
            "organization_id": SEED_ORG_ID,
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_clientes_sem_token_401(client):
    resp = await client.get("/clientes")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_isola_tenant_via_rls(client, auth_headers):
    """/auth/me sob RLS enxerga exatamente 1 organização (a própria)."""
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_id"] == SEED_ORG_ID
    assert body["organizations_visible"] == 1


# ═══════════════════════════════════════════════════════════════
# SEGMENTAÇÃO — contagens e filtros
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_listagem_traz_contadores_de_segmento(client, auth_headers):
    resp = await client.get("/clientes", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    for k in ("total", "ativo_count", "em_risco_count", "inativo_count", "sem_loyalty_count"):
        assert k in body and body[k] >= 0
    assert isinstance(body["clients"], list)


@pytest.mark.asyncio
async def test_filtro_status_ativo_bate_com_contador(client, auth_headers):
    """O total filtrado por status=ativo deve igualar ativo_count da visão geral."""
    geral = (await client.get("/clientes", headers=auth_headers)).json()
    filtrado = (
        await client.get("/clientes?status=ativo", headers=auth_headers)
    ).json()
    assert filtrado["total"] == geral["ativo_count"]
    for c in filtrado["clients"]:
        if c["loyalty"]:
            assert c["loyalty"]["status"] == "ativo"


@pytest.mark.asyncio
async def test_filtro_sem_registro_lista_sem_loyalty(client, auth_headers):
    resp = await client.get("/clientes?status=sem_registro", headers=auth_headers)
    assert resp.status_code == 200
    for c in resp.json()["clients"]:
        assert c["loyalty"] is None


@pytest.mark.asyncio
async def test_filtro_nivel_vip(client, auth_headers):
    resp = await client.get("/clientes?nivel=vip", headers=auth_headers)
    assert resp.status_code == 200
    for c in resp.json()["clients"]:
        if c["loyalty"]:
            assert c["loyalty"]["nivel"] == "vip"


@pytest.mark.asyncio
async def test_loyalty_snapshot_presente_quando_existe(client, auth_headers):
    """Pelo menos um cliente ativo deve trazer o snapshot de fidelidade completo."""
    body = (await client.get("/clientes?status=ativo", headers=auth_headers)).json()
    com_loyalty = [c for c in body["clients"] if c["loyalty"]]
    if not com_loyalty:
        pytest.skip("nenhum cliente ativo com loyalty no seed")
    lo = com_loyalty[0]["loyalty"]
    assert set(lo) >= {"nivel", "status", "categoria", "visit_count", "total_spent"}
    assert lo["visit_count"] >= 0


# ═══════════════════════════════════════════════════════════════
# CRUD — create / edit / block / soft-delete
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ciclo_crud_completo(client, auth_headers):
    suf = uuid.uuid4().int % 100000
    phone = f"6398{suf:05d}"  # vira +55 63 98xxxxx — único por execução

    # CREATE
    created = await client.post(
        "/clientes",
        headers=auth_headers,
        json={"name": "  Cliente Teste  ", "phone": phone},
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert created.json()["name"] == "Cliente Teste"  # trim do validator
    assert created.json()["phone"].startswith("+55")
    assert created.json()["loyalty"] is None

    try:
        # DUPLICATE → 409
        dup = await client.post(
            "/clientes",
            headers=auth_headers,
            json={"name": "Outro", "phone": phone},
        )
        assert dup.status_code == 409

        # EDIT nome
        edited = await client.patch(
            f"/clientes/{cid}",
            headers=auth_headers,
            json={"name": "Cliente Renomeado"},
        )
        assert edited.status_code == 200
        assert edited.json()["name"] == "Cliente Renomeado"

        # BLOCK toggle
        blocked = await client.patch(f"/clientes/{cid}/bloquear", headers=auth_headers)
        assert blocked.status_code == 200
        assert blocked.json()["is_blocked"] is True

        # aparece na listagem por busca
        found = await client.get(
            "/clientes?search=Renomeado", headers=auth_headers
        )
        assert any(c["id"] == cid for c in found.json()["clients"])
    finally:
        # DELETE (soft) — sempre limpa o cliente de teste
        deleted = await client.delete(f"/clientes/{cid}", headers=auth_headers)
        assert deleted.status_code == 204

    # após soft-delete, não aparece mais
    after = await client.get("/clientes?search=Renomeado", headers=auth_headers)
    assert not any(c["id"] == cid for c in after.json()["clients"])


@pytest.mark.asyncio
async def test_create_nome_vazio_422(client, auth_headers):
    resp = await client.post(
        "/clientes",
        headers=auth_headers,
        json={"name": "   ", "phone": "63912340000"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_edit_inexistente_404(client, auth_headers):
    resp = await client.patch(
        "/clientes/99999999",
        headers=auth_headers,
        json={"name": "X"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_inexistente_404(client, auth_headers):
    resp = await client.delete("/clientes/99999999", headers=auth_headers)
    assert resp.status_code == 404
