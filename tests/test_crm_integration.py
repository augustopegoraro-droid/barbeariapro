"""
Testes de integração do CRM/Kanban (funil de leads).

Rodam a aplicação ASGI em processo contra o Postgres semeado (org 3), sob RLS.
Cada teste é autocontido: cria o(s) lead(s), valida e remove ao final, para não
poluir o board compartilhado. Fixtures `client` e `auth_headers` vêm de conftest.
"""
from __future__ import annotations

import pytest

STAGES = {"novo_contato", "conversando", "agendado", "concluido", "perdido"}


async def _create(client, auth_headers, **body):
    body.setdefault("name", "Lead Teste")
    return await client.post("/crm/leads", json=body, headers=auth_headers)


# ─────────────────────────────── AUTH ───────────────────────────────────
@pytest.mark.asyncio
async def test_board_sem_token_401(client):
    resp = await client.get("/crm/board")
    assert resp.status_code == 401


# ─────────────────────────────── BOARD ──────────────────────────────────
@pytest.mark.asyncio
async def test_board_retorna_cinco_colunas_ordenadas(client, auth_headers):
    resp = await client.get("/crm/board", headers=auth_headers)
    assert resp.status_code == 200
    cols = resp.json()["columns"]
    assert [c["stage"] for c in cols] == [
        "novo_contato",
        "conversando",
        "agendado",
        "concluido",
        "perdido",
    ]
    for c in cols:
        assert c["count"] == len(c["leads"])


# ─────────────────────────────── CRUD ───────────────────────────────────
@pytest.mark.asyncio
async def test_criar_lead_entra_em_novo_contato_com_evento(client, auth_headers):
    resp = await _create(
        client, auth_headers, name="Maria Lead", phone="+5511988887777",
        source="instagram",
    )
    assert resp.status_code == 201, resp.text
    lead = resp.json()
    assert lead["stage"] == "novo_contato"
    assert lead["source"] == "instagram"
    assert lead["phone"] == "+5511988887777"

    # aparece no detalhe com evento 'created'
    det = await client.get(f"/crm/leads/{lead['id']}", headers=auth_headers)
    assert det.status_code == 200
    events = det.json()["events"]
    assert any(e["event_type"] == "created" for e in events)

    # cleanup
    d = await client.delete(f"/crm/leads/{lead['id']}", headers=auth_headers)
    assert d.status_code == 204


@pytest.mark.asyncio
async def test_criar_lead_em_estagio_especifico(client, auth_headers):
    resp = await _create(client, auth_headers, name="Direto Conversando", stage="conversando")
    assert resp.status_code == 201
    lead = resp.json()
    assert lead["stage"] == "conversando"
    await client.delete(f"/crm/leads/{lead['id']}", headers=auth_headers)


@pytest.mark.asyncio
async def test_nome_vazio_rejeitado(client, auth_headers):
    resp = await _create(client, auth_headers, name="   ")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_estagio_invalido_rejeitado(client, auth_headers):
    resp = await _create(client, auth_headers, name="X", stage="inexistente")
    assert resp.status_code == 422


# ─────────────────────────── MOVER (Kanban) ─────────────────────────────
@pytest.mark.asyncio
async def test_mover_lead_muda_estagio_e_registra_evento(client, auth_headers):
    created = await _create(client, auth_headers, name="Move Me")
    lead_id = created.json()["id"]

    mv = await client.post(
        f"/crm/leads/{lead_id}/move",
        json={"stage": "agendado"},
        headers=auth_headers,
    )
    assert mv.status_code == 200, mv.text
    assert mv.json()["stage"] == "agendado"

    det = await client.get(f"/crm/leads/{lead_id}", headers=auth_headers)
    evs = det.json()["events"]
    assert any(
        e["event_type"] == "stage_changed"
        and e["from_stage"] == "novo_contato"
        and e["to_stage"] == "agendado"
        for e in evs
    )

    # confirma posição no board (coluna agendado)
    board = await client.get("/crm/board", headers=auth_headers)
    agendado = next(c for c in board.json()["columns"] if c["stage"] == "agendado")
    assert any(l["id"] == lead_id for l in agendado["leads"])

    await client.delete(f"/crm/leads/{lead_id}", headers=auth_headers)


@pytest.mark.asyncio
async def test_mover_mesmo_estagio_nao_duplica_evento(client, auth_headers):
    created = await _create(client, auth_headers, name="Same Stage", stage="conversando")
    lead_id = created.json()["id"]

    await client.post(
        f"/crm/leads/{lead_id}/move",
        json={"stage": "conversando", "position": 5},
        headers=auth_headers,
    )
    det = await client.get(f"/crm/leads/{lead_id}", headers=auth_headers)
    stage_events = [e for e in det.json()["events"] if e["event_type"] == "stage_changed"]
    assert stage_events == []  # não mudou de coluna → sem evento de troca

    await client.delete(f"/crm/leads/{lead_id}", headers=auth_headers)


# ─────────────────────────────── EDITAR ─────────────────────────────────
@pytest.mark.asyncio
async def test_editar_lead(client, auth_headers):
    created = await _create(client, auth_headers, name="Antes")
    lead_id = created.json()["id"]

    pr = await client.patch(
        f"/crm/leads/{lead_id}",
        json={"name": "Depois", "notes": "cliente quer corte sábado"},
        headers=auth_headers,
    )
    assert pr.status_code == 200
    assert pr.json()["name"] == "Depois"
    assert pr.json()["notes"] == "cliente quer corte sábado"

    await client.delete(f"/crm/leads/{lead_id}", headers=auth_headers)


# ─────────────────────────────── DELETE ─────────────────────────────────
@pytest.mark.asyncio
async def test_deletar_lead_some_do_board(client, auth_headers):
    created = await _create(client, auth_headers, name="Some Logo")
    lead_id = created.json()["id"]

    d = await client.delete(f"/crm/leads/{lead_id}", headers=auth_headers)
    assert d.status_code == 204

    det = await client.get(f"/crm/leads/{lead_id}", headers=auth_headers)
    assert det.status_code == 404


@pytest.mark.asyncio
async def test_lead_inexistente_404(client, auth_headers):
    resp = await client.get("/crm/leads/99999999", headers=auth_headers)
    assert resp.status_code == 404
