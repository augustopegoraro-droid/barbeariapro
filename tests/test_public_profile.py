"""Perfil do cliente final no site/app (Fase A do app nativo).

Cobre `GET/PATCH /public/{sub}/me/profile` e o upload/remoção de foto. O ponto
sensível é o nome do arquivo: `/media` é `StaticFiles` público sem auth, então
a foto do cliente é indexada pelo `public_id` (UUID) — nunca pelo id numérico,
que tornaria o acervo de fotos de rosto enumerável (LGPD).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from models import Client
from tests.conftest import SEED_ORG_ID

from tests.test_public_site import BASE, _create_session, public_seed  # noqa: F401


def _png_bytes(size: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (200, 120, 40)).save(buf, format="PNG")
    return buf.getvalue()


async def _client_row(phone: str) -> Client:
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        return (
            await s.execute(select(Client).where(Client.phone_e164 == phone))
        ).scalar_one()


@pytest.mark.asyncio
async def test_perfil_sem_sessao_401(client, public_seed):
    client.cookies.clear()
    resp = await client.get(f"{BASE}/me/profile")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_perfil(client, public_seed):
    _, phone = await _create_session(client, name="Joana Silva")
    resp = await client.get(f"{BASE}/me/profile")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Joana Silva"
    assert body["email"] is None
    assert body["photo_url"] is None
    assert body["member_since"]
    # telefone só mascarado — nunca completo
    assert phone not in body["phone_masked"]
    assert "***" in body["phone_masked"]


@pytest.mark.asyncio
async def test_patch_nome_e_email(client, public_seed):
    _, phone = await _create_session(client, name="Joana Silva")
    resp = await client.patch(
        f"{BASE}/me/profile",
        json={"name": "  Joana S. Costa  ", "email": "joana@example.com"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Joana S. Costa"
    assert resp.json()["email"] == "joana@example.com"

    row = await _client_row(phone)
    assert row.name == "Joana S. Costa"
    assert row.email == "joana@example.com"

    # limpar e-mail é possível (null explícito)
    resp = await client.patch(f"{BASE}/me/profile", json={"email": None})
    assert resp.status_code == 200
    assert resp.json()["email"] is None


@pytest.mark.asyncio
async def test_patch_nao_altera_telefone(client, public_seed):
    """Telefone é somente leitura: mandar o campo não muda nada (v1 sem OTP)."""
    _, phone = await _create_session(client)
    resp = await client.patch(
        f"{BASE}/me/profile",
        json={"name": "Outro Nome", "phone": "+5511999998888", "phone_e164": "+5511999998888"},
    )
    assert resp.status_code == 200, resp.text
    row = await _client_row(phone)
    assert row.phone_e164 == phone
    assert row.name == "Outro Nome"


@pytest.mark.asyncio
async def test_upload_foto_usa_public_id(client, public_seed, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    _, phone = await _create_session(client)
    row = await _client_row(phone)

    resp = await client.put(
        f"{BASE}/me/profile/foto",
        files={"file": ("selfie.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    photo_url = resp.json()["photo_url"]
    assert photo_url and str(row.public_id) in photo_url
    # id numérico NÃO pode aparecer no nome do arquivo (seria enumerável)
    assert f"client-{row.id}.webp" not in photo_url

    salvo = tmp_path / f"org{SEED_ORG_ID}" / f"client-{row.public_id}.webp"
    assert salvo.exists()

    atualizado = await _client_row(phone)
    assert atualizado.photo_path.startswith(f"org{SEED_ORG_ID}/client-{row.public_id}.webp?v=")

    # remoção limpa campo e arquivo
    resp = await client.delete(f"{BASE}/me/profile/foto")
    assert resp.status_code == 200, resp.text
    assert resp.json()["photo_url"] is None
    assert not salvo.exists()


@pytest.mark.asyncio
async def test_upload_tipo_invalido_422(client, public_seed, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    await _create_session(client)
    resp = await client.put(
        f"{BASE}/me/profile/foto",
        files={"file": ("payload.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")},
    )
    assert resp.status_code == 422, resp.text
