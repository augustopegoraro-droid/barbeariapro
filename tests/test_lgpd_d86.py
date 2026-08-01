"""Fechamento dos gaps de LGPD levantados na auditoria de 2026-07-30 (D-86).

Cobre o que a Fase 8 (D-74) tinha deixado em aberto: base legal registrada na
entrada do titular, versão da política carimbada, export/anonimização cobrindo
todas as tabelas com PII, verificação da cadeia de auditoria e retenção
configurável.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select

from app.core.privacy import (
    PRIVACY_POLICY_VERSION,
    SOURCE_PANEL_SIGNUP,
)
from app.db.session import AsyncSessionLocal, set_current_org
from models import Client, ClientConsent, ConsentRecord, ConsentStatus

pytestmark = pytest.mark.asyncio

SEED_ORG = int(os.environ.get("SEED_ORG_ID", "1"))


async def _create_client(client, headers, *, accept: bool | None = None) -> int:
    suf = uuid.uuid4().int % 100000
    body = {"name": "Titular D86", "phone": f"6397{suf:05d}"}
    if accept is not None:
        body["accept_privacy"] = accept
    resp = await client.post("/clientes", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _consents(client_id: int) -> list[ConsentRecord]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            return list(
                (
                    await session.execute(
                        select(ConsentRecord)
                        .where(ConsentRecord.subject_type == "client")
                        .where(ConsentRecord.subject_id == client_id)
                        .order_by(ConsentRecord.id)
                    )
                ).scalars().all()
            )


# ─── base legal na entrada ───────────────────────────────────────────────────

async def test_cadastro_pelo_painel_registra_consentimento(client, auth_headers):
    """Antes do D-86 o cliente nascia sem nenhuma base legal e ainda assim
    entrava em lembrete/reativação."""
    client_id = await _create_client(client, auth_headers)

    records = await _consents(client_id)
    assert records, "cadastro pelo painel não registrou consentimento"
    assert records[-1].status == ConsentStatus.opt_in.value
    assert records[-1].source == SOURCE_PANEL_SIGNUP
    assert records[-1].policy_version == PRIVACY_POLICY_VERSION

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            state = (
                await session.execute(
                    select(ClientConsent).where(ClientConsent.client_id == client_id)
                )
            ).scalars().all()
    assert len(state) == 1 and state[0].status == ConsentStatus.opt_in


async def test_cadastro_sem_aceite_nasce_em_opt_out(client, auth_headers):
    client_id = await _create_client(client, auth_headers, accept=False)
    records = await _consents(client_id)
    assert records[-1].status == ConsentStatus.opt_out.value


async def test_consents_expoe_versao_da_politica(client, auth_headers):
    client_id = await _create_client(client, auth_headers)
    resp = await client.get(
        f"/admin/security/lgpd/clients/{client_id}/consents", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()[0]["policy_version"] == PRIVACY_POLICY_VERSION


# ─── export completo ─────────────────────────────────────────────────────────

async def test_export_cobre_todas_as_colecoes_de_pii(client, auth_headers):
    client_id = await _create_client(client, auth_headers)
    resp = await client.get(
        f"/admin/security/lgpd/clients/{client_id}/export", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    for chave in (
        "agendamentos",
        "pagamentos",
        "assinaturas",
        "conversas",
        "mensagens_enviadas",
        "leads",
        "sessoes_site",
        "consentimentos",
    ):
        assert chave in body, f"export não inclui {chave}"
        # Toda coleção diz explicitamente se truncou (o LIMIT 500 silencioso
        # anterior mentia por omissão).
        assert set(body[chave]) == {"total", "truncado", "itens"}
        assert body[chave]["truncado"] is False


# ─── anonimização completa ───────────────────────────────────────────────────

async def test_anonimizacao_limpa_conversa_e_sessao(client, auth_headers):
    """Anonimizar só a ficha deixava o titular identificável pela própria
    conversa de WhatsApp e pelo IP da sessão do site."""
    from models import ClientSession, Conversation, Message
    from models.enums import MessageSenderType

    client_id = await _create_client(client, auth_headers)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            cli = (
                await session.execute(select(Client).where(Client.id == client_id))
            ).scalar_one()
            conv = Conversation(
                organization_id=SEED_ORG,
                client_id=client_id,
                phone_e164=cli.phone_e164,
                last_message_preview="Oi, aqui é o João",
            )
            session.add(conv)
            await session.flush()
            session.add(
                Message(
                    organization_id=SEED_ORG,
                    conversation_id=conv.id,
                    sender_type=MessageSenderType.client,
                    body_text="Meu nome é João e moro na quadra 103",
                )
            )
            session.add(
                ClientSession(
                    organization_id=SEED_ORG,
                    client_id=client_id,
                    token_hash=uuid.uuid4().hex,
                    ip="200.1.2.3",
                    user_agent="Mozilla/5.0",
                )
            )
            conv_id = conv.id

    resp = await client.post(
        f"/admin/security/lgpd/clients/{client_id}/anonymize", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, SEED_ORG)
            conv = (
                await session.execute(select(Conversation).where(Conversation.id == conv_id))
            ).scalar_one()
            msgs = (
                await session.execute(
                    select(Message).where(Message.conversation_id == conv_id)
                )
            ).scalars().all()
            sessions = (
                await session.execute(
                    select(ClientSession).where(ClientSession.client_id == client_id)
                )
            ).scalars().all()

    assert conv.last_message_preview is None
    assert all(m.body_text is None for m in msgs)
    assert all(s.ip is None and s.user_agent is None for s in sessions)
    assert all(s.revoked_at is not None for s in sessions), "sessão do site não foi revogada"


async def test_anonimizacao_preserva_prova_de_consentimento(client, auth_headers):
    """`consent_records` é a defesa da própria organização — não some com o
    esquecimento."""
    client_id = await _create_client(client, auth_headers)
    antes = await _consents(client_id)

    resp = await client.post(
        f"/admin/security/lgpd/clients/{client_id}/anonymize", headers=auth_headers
    )
    assert resp.status_code == 200

    depois = await _consents(client_id)
    assert len(depois) >= len(antes) and antes


# ─── auditoria: cadeia de hash ───────────────────────────────────────────────

async def test_verificacao_da_cadeia_de_auditoria(client, auth_headers):
    from app.services import audit as audit_svc

    # Gera pelo menos um evento novo antes de verificar.
    await _create_client(client, auth_headers)
    await audit_svc.wait_for_pending()

    # Janela curta: o DB de staging carrega linhas antigas com `actor_user_id`
    # zerado pelo FK `ON DELETE SET NULL` que a 0048 removeu — quebras reais e
    # irrecuperáveis, que a verificação deve continuar apontando.
    resp = await client.get(
        "/admin/security/audit/verify", headers=auth_headers, params={"limit": 10}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True, f"cadeia quebrada ({body['kind']}) em {body['broken_at_id']}"
    assert body["checked"] > 0
    assert body["broken_at_id"] is None


async def test_verificacao_exige_permissao(client, barber_headers):
    resp = await client.get("/admin/security/audit/verify", headers=barber_headers)
    assert resp.status_code == 403


# ─── retenção ────────────────────────────────────────────────────────────────

async def test_retencao_leitura_e_alteracao(client, auth_headers):
    resp = await client.get("/admin/security/retention", headers=auth_headers)
    assert resp.status_code == 200
    original = resp.json()["audit_retention_months"]

    novo = 24 if original != 24 else 18
    resp = await client.put(
        "/admin/security/retention",
        headers=auth_headers,
        json={"audit_retention_months": novo},
    )
    assert resp.status_code == 200
    assert resp.json()["audit_retention_months"] == novo

    resp = await client.get("/admin/security/retention", headers=auth_headers)
    assert resp.json()["audit_retention_months"] == novo

    # restaura
    await client.put(
        "/admin/security/retention",
        headers=auth_headers,
        json={"audit_retention_months": original},
    )


async def test_retencao_rejeita_prazo_absurdo(client, auth_headers):
    resp = await client.put(
        "/admin/security/retention",
        headers=auth_headers,
        json={"audit_retention_months": 0},
    )
    assert resp.status_code == 422
    resp = await client.put(
        "/admin/security/retention",
        headers=auth_headers,
        json={"audit_retention_months": 999},
    )
    assert resp.status_code == 422


async def test_purga_de_sessoes_roda(client):
    """A função SECURITY DEFINER da 0047 existe e é executável pelo role da
    app (a purga roda cross-org, sem tenant setado)."""
    from app.services.retention import purge_expired_sessions

    result = await purge_expired_sessions()
    assert set(result) == {"staff_sessions", "client_sessions"}
    assert result["staff_sessions"] >= 0
