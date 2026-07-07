"""Matriz de papéis nos endpoints migrados para require() (F2.5).

Prova a NÃO-REGRESSÃO da migração dos guards legados: cada guard mapeou para uma
permissão cujo conjunto de papéis (entre os 4 atuais) é idêntico ao antigo.
Skip se o DB não estiver semeado.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ─── manager-only preservado (recepção continua excluída) ───────────────────────
async def test_financeiro_denied_for_reception(client, reception_headers):
    r = await client.get(
        "/financeiro", params={"date": "2026-07-01"}, headers=reception_headers
    )
    assert r.status_code == 403


async def test_financeiro_allowed_for_owner(client, auth_headers):
    r = await client.get("/financeiro", params={"date": "2026-07-01"}, headers=auth_headers)
    assert r.status_code == 200


async def test_equipe_denied_for_reception(client, reception_headers):
    r = await client.get("/equipe", headers=reception_headers)
    assert r.status_code == 403


async def test_equipe_allowed_for_manager(client, manager_headers):
    r = await client.get("/equipe", headers=manager_headers)
    assert r.status_code == 200


async def test_gestor_mrr_denied_for_reception(client, reception_headers):
    r = await client.get("/admin/gestor/mrr", headers=reception_headers)
    assert r.status_code == 403


async def test_servicos_denied_for_reception(client, reception_headers):
    r = await client.get("/servicos", headers=reception_headers)
    assert r.status_code == 403


# ─── full-access preservado (recepção mantém, barbeiro continua fora) ───────────
async def test_clientes_list_allowed_for_reception(client, reception_headers):
    r = await client.get("/clientes", headers=reception_headers)
    assert r.status_code == 200


async def test_clientes_list_denied_for_barber(client, barber_headers):
    r = await client.get("/clientes", headers=barber_headers)
    assert r.status_code == 403


async def test_memberships_planos_allowed_for_reception(client, reception_headers):
    r = await client.get("/memberships/planos", headers=reception_headers)
    assert r.status_code == 200


async def test_crm_board_allowed_for_reception(client, reception_headers):
    r = await client.get("/crm/board", headers=reception_headers)
    assert r.status_code == 200


async def test_crm_board_denied_for_barber(client, barber_headers):
    r = await client.get("/crm/board", headers=barber_headers)
    assert r.status_code == 403
