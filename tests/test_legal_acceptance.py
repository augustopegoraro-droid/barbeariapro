"""Aceite do termo de uso (funcionário) e do contrato de operador/DPA (dono) — D-87.

O D-86 fechou a entrada do cliente final; estes são os dois documentos de quem
opera o sistema. Cobre: estado pendente por versão, registro do aceite (estado +
histórico append-only + auditoria), restrição do DPA ao proprietário e reabertura
automática quando o texto muda de versão.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.privacy import DPA_VERSION, SOURCE_DPA_ACCEPT, SOURCE_TERMS_ACCEPT, TERMS_VERSION
from app.db.session import AsyncSessionLocal, set_current_org
from models import ConsentRecord, Organization, User

pytestmark = pytest.mark.asyncio

SEED_ORG = int(os.environ.get("SEED_ORG_ID", "1"))


async def _reset_acceptances() -> None:
    """Volta org e usuários ao estado "nunca aceitou" — os testes de aceite
    gravam estado persistente e precisam de um ponto de partida limpo."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            org = (
                await session.execute(select(Organization).where(Organization.id == SEED_ORG))
            ).scalar_one()
            org.dpa_version_accepted = None
            org.dpa_accepted_at = None
            org.dpa_accepted_by_user_id = None
            for user in (
                await session.execute(select(User).where(User.organization_id == SEED_ORG))
            ).scalars().all():
                user.terms_version_accepted = None
                user.terms_accepted_at = None


@pytest_asyncio.fixture(autouse=True)
async def _clean_state():
    await _reset_acceptances()
    yield
    await _reset_acceptances()


async def _history(channel: str) -> list[ConsentRecord]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            return list(
                (
                    await session.execute(
                        select(ConsentRecord)
                        .where(ConsentRecord.subject_type == "user")
                        .where(ConsentRecord.channel == channel)
                        .order_by(ConsentRecord.id)
                    )
                ).scalars().all()
            )


# ─── status ──────────────────────────────────────────────────────────────────

async def test_status_exige_autenticacao(client):
    assert (await client.get("/auth/me/legal")).status_code == 401


async def test_dono_comeca_com_os_dois_pendentes(client, auth_headers):
    resp = await client.get("/auth/me/legal", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "owner"
    assert body["terms"]["pending"] is True
    assert body["terms"]["version"] == TERMS_VERSION
    assert body["dpa"]["pending"] is True
    assert body["dpa"]["version"] == DPA_VERSION


async def test_barbeiro_nao_tem_dpa_pendente(client, barber_headers):
    """Contrato em nome da empresa não é pendência de quem não pode assiná-lo."""
    resp = await client.get("/auth/me/legal", headers=barber_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["terms"]["pending"] is True
    assert body["dpa"]["pending"] is False


# ─── aceite do termo ─────────────────────────────────────────────────────────

async def test_aceitar_termo_grava_estado_historico_e_auditoria(client, auth_headers):
    from app.services import audit as audit_svc
    from models import AuditLog

    resp = await client.post(
        "/auth/me/legal/accept", headers=auth_headers, json={"document": "terms"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["terms"]["pending"] is False
    assert body["terms"]["accepted_version"] == TERMS_VERSION
    assert body["terms"]["accepted_at"]

    registros = await _history("terms")
    assert registros, "aceite do termo não gravou histórico"
    assert registros[-1].status == "accepted"
    assert registros[-1].source == SOURCE_TERMS_ACCEPT
    assert registros[-1].policy_version == TERMS_VERSION
    assert registros[-1].ip is not None

    await audit_svc.wait_for_pending()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            eventos = (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.organization_id == SEED_ORG)
                    .where(AuditLog.action == "legal.terms.accept")
                )
            ).scalars().all()
    assert eventos, "aceite do termo não gerou evento de auditoria"


async def test_barbeiro_aceita_o_proprio_termo(client, barber_headers):
    resp = await client.post(
        "/auth/me/legal/accept", headers=barber_headers, json={"document": "terms"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["terms"]["pending"] is False


async def test_aceite_de_um_usuario_nao_vale_para_outro(client, auth_headers, barber_headers):
    await client.post(
        "/auth/me/legal/accept", headers=auth_headers, json={"document": "terms"}
    )
    resp = await client.get("/auth/me/legal", headers=barber_headers)
    assert resp.json()["terms"]["pending"] is True


# ─── aceite do contrato (DPA) ────────────────────────────────────────────────

async def test_dono_aceita_dpa_e_registra_quem_assinou(client, auth_headers):
    resp = await client.post(
        "/auth/me/legal/accept", headers=auth_headers, json={"document": "dpa"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dpa"]["pending"] is False

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            org = (
                await session.execute(select(Organization).where(Organization.id == SEED_ORG))
            ).scalar_one()
    assert org.dpa_version_accepted == DPA_VERSION
    assert org.dpa_accepted_by_user_id is not None

    registros = await _history("dpa")
    assert registros[-1].source == SOURCE_DPA_ACCEPT
    assert registros[-1].policy_version == DPA_VERSION


async def test_barbeiro_nao_pode_aceitar_dpa(client, barber_headers):
    resp = await client.post(
        "/auth/me/legal/accept", headers=barber_headers, json={"document": "dpa"}
    )
    assert resp.status_code == 403


async def test_dpa_aceito_vale_para_toda_a_org(client, auth_headers, barber_headers):
    """O contrato é da empresa: aceito pelo dono, some da pendência de todos."""
    await client.post("/auth/me/legal/accept", headers=auth_headers, json={"document": "dpa"})
    resp = await client.get("/auth/me/legal", headers=barber_headers)
    assert resp.json()["dpa"]["pending"] is False
    assert resp.json()["dpa"]["accepted_version"] == DPA_VERSION


# ─── versionamento ───────────────────────────────────────────────────────────

async def test_texto_novo_reabre_o_aceite(client, auth_headers):
    """Publicar uma versão nova torna o aceite pendente de novo, sem migration
    e sem tocar em nada além da constante."""
    await client.post(
        "/auth/me/legal/accept", headers=auth_headers, json={"document": "terms"}
    )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            user = (
                await session.execute(
                    select(User)
                    .where(User.organization_id == SEED_ORG)
                    .where(User.terms_version_accepted.is_not(None))
                    .limit(1)
                )
            ).scalar_one()
            user.terms_version_accepted = "1900-01-01"  # simula texto antigo

    resp = await client.get("/auth/me/legal", headers=auth_headers)
    assert resp.json()["terms"]["pending"] is True
    assert resp.json()["terms"]["accepted_version"] == "1900-01-01"


async def test_reaceitar_nao_sobrescreve_o_historico(client, auth_headers):
    antes = len(await _history("terms"))
    await client.post("/auth/me/legal/accept", headers=auth_headers, json={"document": "terms"})
    await client.post("/auth/me/legal/accept", headers=auth_headers, json={"document": "terms"})
    depois = await _history("terms")
    assert len(depois) == antes + 2, "histórico de aceite deve ser append-only"


async def test_documento_invalido_422(client, auth_headers):
    resp = await client.post(
        "/auth/me/legal/accept", headers=auth_headers, json={"document": "outro"}
    )
    assert resp.status_code == 422
