"""Sincronização painel → site público (D-84).

Prova que uma escrita no painel (profissional novo, serviço renomeado,
visibilidade) aparece na vitrine `GET /public/{subdomain}/info` na mesma hora —
sem esperar o TTL do cache Redis (60s). A 2ª camada (ISR do Next) é o route
handler `barbearia-public/app/api/revalidate/route.ts`, fora do escopo do pytest.

Reaproveita o fixture `public_seed` de tests/test_public_site.py (subdomínio na
org semeada + limpeza).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, set_current_org
from app.services.site_visibility import ensure_visible
from models import Barber, ClientVisibilitySettings, Service
from tests.conftest import SEED_ORG_ID
from tests.test_public_site import BASE, public_seed  # noqa: F401  (fixture)


async def _archive_barber(barber_id: int) -> None:
    """Soft-delete direto no banco — o endpoint de arquivar bloqueia se houver
    agendamento futuro, e aqui só queremos tirar o resíduo da vitrine."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            b = (await s.execute(select(Barber).where(Barber.id == barber_id))).scalar_one_or_none()
            if b is not None:
                b.deleted_at = datetime.now(timezone.utc)


async def _visibility_row() -> ClientVisibilitySettings | None:
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        return (
            await s.execute(
                select(ClientVisibilitySettings).where(
                    ClientVisibilitySettings.organization_id == SEED_ORG_ID
                )
            )
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_profissional_novo_aparece_na_vitrine_na_hora(client, auth_headers, public_seed):
    """Sem a invalidação, o cache de 60s esconderia o cadastro novo."""
    primeira = await client.get(f"{BASE}/info")
    assert primeira.status_code == 200
    antes = {p["id"] for p in primeira.json()["professionals"]}

    criado = await client.post(
        "/equipe/barbeiros",
        headers=auth_headers,
        json={"name": "Sync D84", "specialty": "Corte", "commission_pct": 0.4},
    )
    assert criado.status_code == 201, criado.text
    novo_id = criado.json()["id"]

    try:
        depois = await client.get(f"{BASE}/info")
        assert depois.status_code == 200
        pros = {p["id"]: p for p in depois.json()["professionals"]}
        assert novo_id in pros, "profissional novo não apareceu (cache não invalidado)"
        assert novo_id not in antes
        assert pros[novo_id]["name"] == "Sync D84"
    finally:
        await _archive_barber(novo_id)


@pytest.mark.asyncio
async def test_profissional_arquivado_sai_da_vitrine_na_hora(client, auth_headers, public_seed):
    criado = await client.post(
        "/equipe/barbeiros",
        headers=auth_headers,
        json={"name": "Sync D84 Arquivar", "commission_pct": 0.4},
    )
    assert criado.status_code == 201, criado.text
    novo_id = criado.json()["id"]

    visivel = await client.get(f"{BASE}/info")
    assert novo_id in {p["id"] for p in visivel.json()["professionals"]}

    arquivado = await client.patch(f"/equipe/barbeiros/{novo_id}/arquivar", headers=auth_headers)
    assert arquivado.status_code == 200, arquivado.text

    depois = await client.get(f"{BASE}/info")
    assert novo_id not in {p["id"] for p in depois.json()["professionals"]}


@pytest.mark.asyncio
async def test_whitelist_custom_recebe_o_profissional_novo(client, auth_headers, public_seed):
    """Com `mode=custom`, um cadastro novo nasceria invisível — ensure_visible
    o adiciona para que "adicionar funcionário" tenha efeito no site."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            existente = (
                await s.execute(select(Barber).where(Barber.deleted_at.is_(None)).limit(1))
            ).scalar_one()
            s.add(
                ClientVisibilitySettings(
                    organization_id=SEED_ORG_ID,
                    services={"mode": "all", "ids": []},
                    professionals={"mode": "custom", "ids": [existente.id]},
                    banner={"enabled": False},
                    public_info={},
                )
            )

    criado = await client.post(
        "/equipe/barbeiros",
        headers=auth_headers,
        json={"name": "Sync D84 Custom", "commission_pct": 0.4},
    )
    assert criado.status_code == 201, criado.text
    novo_id = criado.json()["id"]

    try:
        row = await _visibility_row()
        assert row is not None
        assert novo_id in {int(i) for i in row.professionals["ids"]}

        depois = await client.get(f"{BASE}/info")
        assert novo_id in {p["id"] for p in depois.json()["professionals"]}
    finally:
        await _archive_barber(novo_id)


@pytest.mark.asyncio
async def test_ensure_visible_nao_toca_whitelist_em_modo_all(public_seed):
    """`mode=all` já mostra tudo — não virar custom por engano."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            s.add(
                ClientVisibilitySettings(
                    organization_id=SEED_ORG_ID,
                    services={"mode": "all", "ids": []},
                    professionals={"mode": "all", "ids": []},
                    banner={"enabled": False},
                    public_info={},
                )
            )
            await ensure_visible(s, SEED_ORG_ID, "professionals", 999_999)

    row = await _visibility_row()
    assert row is not None
    assert row.professionals == {"mode": "all", "ids": []}


@pytest.mark.asyncio
async def test_servico_renomeado_aparece_na_vitrine_na_hora(client, auth_headers, public_seed):
    service_id = public_seed["service_id"]
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        original = (
            await s.execute(select(Service.name).where(Service.id == service_id))
        ).scalar_one()

    await client.get(f"{BASE}/info")  # popula o cache
    novo_nome = f"{original} D84"
    resp = await client.patch(
        f"/servicos/{service_id}", headers=auth_headers, json={"name": novo_nome}
    )
    assert resp.status_code == 200, resp.text

    try:
        depois = await client.get(f"{BASE}/info")
        nomes = {s["id"]: s["name"] for s in depois.json()["services"]}
        assert nomes.get(service_id) == novo_nome
    finally:
        await client.patch(
            f"/servicos/{service_id}", headers=auth_headers, json={"name": original}
        )
