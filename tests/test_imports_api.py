"""Rotas de migração da Trinks (`/admin/import/trinks/*`).

Valida: exige auth (gestor), upload do corpo bruto, dry-run não grava e devolve os
relatórios de parsing/importação. Usa a org semeada (fixtures do conftest).
"""
from __future__ import annotations

from pathlib import Path

import pytest

FIXT = Path(__file__).parent / "fixtures" / "trinks"
CLIENTS = (FIXT / "clientes_sample.csv").read_bytes()
APPTS = (FIXT / "agendamentos_sample.csv").read_bytes()
RANKING = (FIXT / "ranking_sample.csv").read_bytes()
DEBTS = (FIXT / "debitos_sample.csv").read_bytes()
CSV_HEADERS = {"Content-Type": "text/csv"}


@pytest.mark.asyncio
async def test_clients_exige_auth(client):
    r = await client.post("/admin/import/trinks/clients", content=CLIENTS, headers=CSV_HEADERS)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_clients_dry_run_nao_grava(client, auth_headers):
    r = await client.post(
        "/admin/import/trinks/clients",
        content=CLIENTS,
        headers={**auth_headers, **CSV_HEADERS},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["commit"] is False
    assert body["parse"]["importable"] == 3          # João, Maria, Carla
    assert body["parse"]["dup_in_file"] == 1
    assert "inserted" in body["import"]              # dry-run: contabiliza, não grava


@pytest.mark.asyncio
async def test_appointments_dry_run(client, auth_headers):
    r = await client.post(
        "/admin/import/trinks/appointments",
        content=APPTS,
        headers={**auth_headers, **CSV_HEADERS},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["commit"] is False
    assert body["parse"]["parsed"] == 4
    assert body["parse"]["cancelled_skipped"] == 1


@pytest.mark.asyncio
async def test_corpo_vazio_400(client, auth_headers):
    r = await client.post("/admin/import/trinks/clients", content=b"", headers=auth_headers)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_ranking_dry_run(client, auth_headers):
    r = await client.post(
        "/admin/import/trinks/ranking",
        content=RANKING,
        headers={**auth_headers, **CSV_HEADERS},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["commit"] is False
    assert body["parse"]["parsed"] == 2
    assert "email_filled" in body["enrich"]


@pytest.mark.asyncio
async def test_debts_import_dry_run(client, auth_headers):
    r = await client.post(
        "/admin/import/trinks/debts",
        content=DEBTS,
        headers={**auth_headers, **CSV_HEADERS},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parse"]["parsed"] == 2
    assert body["import"]["created"] == 2  # dry-run: conta, não grava


@pytest.mark.asyncio
async def test_debts_exige_auth(client):
    r = await client.get("/admin/debts")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_debts_summary_ok(client, auth_headers):
    r = await client.get("/admin/debts/summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert {"open_count", "open_total", "paid_count"} <= r.json().keys()
