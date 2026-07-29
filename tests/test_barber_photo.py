"""Foto do profissional (D-85): upload, normalização, remoção e vitrine.

O storage é local (`MEDIA_ROOT`), então o fixture aponta a raiz para um tmpdir —
nenhum teste escreve em `/app/uploads` nem depende de volume montado.
"""
from __future__ import annotations

import io

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import media
from models import Barber
from tests.conftest import SEED_ORG_ID
from tests.test_public_site import BASE, public_seed  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def media_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(settings, "media_public_base", "https://api.test/media")
    yield tmp_path


def _png_bytes(width=1200, height=600, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


async def _barber_id() -> int:
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        return (
            await s.execute(select(Barber.id).where(Barber.deleted_at.is_(None)).limit(1))
        ).scalars().first()


async def _photo_path(barber_id: int) -> str | None:
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        return (
            await s.execute(select(Barber.photo_path).where(Barber.id == barber_id))
        ).scalar_one()


@pytest_asyncio.fixture
async def _cleanup_photo():
    """Devolve o barbeiro ao estado sem foto ao fim do teste."""
    ids: list[int] = []
    yield ids
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            for bid in ids:
                b = (await s.execute(select(Barber).where(Barber.id == bid))).scalar_one()
                b.photo_path = None


# ─── serviço de mídia (unit) ─────────────────────────────────────────────────

def test_normaliza_para_webp_quadrado(media_tmp):
    rel = media.save_barber_photo(7, 42, _png_bytes(1200, 600), "image/png")

    assert rel.startswith("org7/barber-42.webp?v=")
    arquivo = media_tmp / "org7" / "barber-42.webp"
    with Image.open(arquivo) as img:
        assert img.format == "WEBP"
        assert img.size == (media.OUTPUT_SIZE, media.OUTPUT_SIZE), "deveria virar quadrado"
    assert arquivo.stat().st_size < 200_000, "800px WebP não deveria passar de ~200KB"
    assert not list(media_tmp.rglob("*.tmp")), "temporário de escrita ficou para trás"


def test_orgs_nao_colidem(media_tmp):
    media.save_barber_photo(1, 5, _png_bytes(color=(10, 200, 10)), "image/png")
    media.save_barber_photo(2, 5, _png_bytes(color=(10, 10, 200)), "image/png")

    assert (media_tmp / "org1" / "barber-5.webp").exists()
    assert (media_tmp / "org2" / "barber-5.webp").exists()


def test_versao_muda_ao_substituir(media_tmp):
    """Nome de arquivo é estável, então o ?v= é o que fura o cache — inclusive
    em duas trocas dentro do mesmo segundo (daí mtime em nanossegundos)."""
    primeira = media.save_barber_photo(1, 9, _png_bytes(), "image/png")
    segunda = media.save_barber_photo(1, 9, _png_bytes(color=(0, 0, 255)), "image/png")

    assert primeira != segunda
    assert segunda.startswith("org1/barber-9.webp?v=")


@pytest.mark.skipif(not media.HEIC_SUPPORTED, reason="pillow-heif não instalado")
def test_aceita_heic_de_iphone(media_tmp):
    """Foto de iPhone chega como HEIC — o Pillow puro não decodifica."""
    buf = io.BytesIO()
    Image.new("RGB", (900, 1200), (120, 90, 60)).save(buf, format="HEIF")

    rel = media.save_barber_photo(1, 11, buf.getvalue(), "image/heic")

    with Image.open(media_tmp / "org1" / "barber-11.webp") as img:
        assert img.format == "WEBP"
        assert img.size == (media.OUTPUT_SIZE, media.OUTPUT_SIZE)
    assert rel.startswith("org1/barber-11.webp?v=")


def test_exif_de_orientacao_e_geolocalizacao_nao_sobrevivem(media_tmp):
    """WebP de saída não carrega o EXIF do original (leva GPS em foto de celular)."""
    original = Image.new("RGB", (1000, 500), (90, 120, 200))
    exif = original.getexif()
    exif[274] = 6  # Orientation: girar 90°
    exif[271] = "TesteCam"  # Make
    buf = io.BytesIO()
    original.save(buf, format="JPEG", exif=exif)

    media.save_barber_photo(1, 12, buf.getvalue(), "image/jpeg")

    with Image.open(media_tmp / "org1" / "barber-12.webp") as img:
        assert not dict(img.getexif()), "EXIF deveria ter sido descartado"


def test_arquivo_nao_imagem_recusado(media_tmp):
    with pytest.raises(media.MediaError):
        media.save_barber_photo(1, 1, b"<svg onload=alert(1)></svg>", "image/svg+xml")
    with pytest.raises(media.MediaError):
        media.save_barber_photo(1, 1, b"nao sou imagem", "image/png")
    assert not list(media_tmp.rglob("*.webp")), "nada deveria chegar ao disco"


def test_tamanho_maximo(media_tmp):
    with pytest.raises(media.MediaError, match="muito grande"):
        media.save_barber_photo(1, 1, b"x" * (media.MAX_UPLOAD_BYTES + 1), "image/png")


def test_public_url_monta_absoluto():
    assert media.public_url(None) is None
    assert media.public_url("org1/barber-2.webp?v=9") == (
        "https://api.test/media/org1/barber-2.webp?v=9"
    )


def test_delete_e_idempotente(media_tmp):
    media.save_barber_photo(1, 3, _png_bytes(), "image/png")
    media.delete_barber_photo(1, 3)
    media.delete_barber_photo(1, 3)  # não levanta
    assert not (media_tmp / "org1" / "barber-3.webp").exists()


# ─── API ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_e_remocao_pela_api(client, auth_headers, _cleanup_photo, media_tmp):
    barber_id = await _barber_id()
    _cleanup_photo.append(barber_id)

    resp = await client.put(
        f"/equipe/barbeiros/{barber_id}/foto",
        headers=auth_headers,
        files={"file": ("foto.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["photo_url"].startswith("https://api.test/media/")
    assert (media_tmp / f"org{SEED_ORG_ID}" / f"barber-{barber_id}.webp").exists()
    assert await _photo_path(barber_id) is not None

    listagem = await client.get("/equipe", headers=auth_headers)
    alvo = next(b for b in listagem.json()["barbers"] if b["id"] == barber_id)
    assert alvo["photo_url"], "a listagem da equipe deveria expor a foto"

    apagou = await client.delete(f"/equipe/barbeiros/{barber_id}/foto", headers=auth_headers)
    assert apagou.status_code == 200, apagou.text
    assert apagou.json()["photo_url"] is None
    assert not (media_tmp / f"org{SEED_ORG_ID}" / f"barber-{barber_id}.webp").exists()
    assert await _photo_path(barber_id) is None


@pytest.mark.asyncio
async def test_upload_invalido_422(client, auth_headers):
    barber_id = await _barber_id()
    resp = await client.put(
        f"/equipe/barbeiros/{barber_id}/foto",
        headers=auth_headers,
        files={"file": ("x.txt", b"nao sou imagem", "text/plain")},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_barbeiro_inexistente_404(client, auth_headers):
    resp = await client.put(
        "/equipe/barbeiros/999999/foto",
        headers=auth_headers,
        files={"file": ("foto.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_barbeiro_nao_pode_enviar_foto(client, barber_headers):
    """Foto é gestão de equipe (`team.manage`) — barbeiro não tem."""
    barber_id = await _barber_id()
    resp = await client.put(
        f"/equipe/barbeiros/{barber_id}/foto",
        headers=barber_headers,
        files={"file": ("foto.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_foto_aparece_na_vitrine_publica(
    client, auth_headers, public_seed, _cleanup_photo, media_tmp
):
    barber_id = public_seed["barber_id"]
    _cleanup_photo.append(barber_id)

    await client.get(f"{BASE}/info")  # popula o cache da vitrine
    resp = await client.put(
        f"/equipe/barbeiros/{barber_id}/foto",
        headers=auth_headers,
        files={"file": ("foto.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, resp.text

    vitrine = await client.get(f"{BASE}/info")
    alvo = next(p for p in vitrine.json()["professionals"] if p["id"] == barber_id)
    assert alvo["photo_url"], "a foto deveria aparecer no site sem esperar o TTL (D-84)"
