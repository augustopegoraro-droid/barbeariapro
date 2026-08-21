"""Feed de novidades (Feature 1): painel, RBAC, RLS, rota pública e cache.

O storage de mídia é local (`MEDIA_ROOT`), então o fixture aponta a raiz para um
tmpdir — nenhum teste escreve em `/app/uploads` (molde `test_barber_photo.py`).

Limpeza: `feed_posts` NÃO tem GRANT de DELETE ao `barber_app` (é o desenho —
arquivar é `deleted_at`), então o cleanup arquiva em vez de apagar.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import media
from app.services.public_cache import feed_cache_key
from models import FeedPost
from tests.conftest import SEED_ORG_ID
from tests.test_public_site import BASE, public_seed  # noqa: F401  (fixture)

MARK = "FeedTeste"


@pytest.fixture(autouse=True)
def media_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(settings, "media_public_base", "https://api.test/media")
    yield tmp_path


async def _clear_feed_cache() -> None:
    try:
        from app.db.redis import get_redis

        await get_redis().delete(feed_cache_key(SEED_ORG_ID))
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    """Zera o mural antes e depois: os testes contam itens da vitrine."""
    await _archive_all()
    await _clear_feed_cache()
    yield
    await _archive_all()
    await _clear_feed_cache()


async def _archive_all() -> None:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            rows = (
                await s.execute(select(FeedPost).where(FeedPost.deleted_at.is_(None)))
            ).scalars().all()
            for row in rows:
                row.deleted_at = datetime.now(timezone.utc)


def _title() -> str:
    return f"{MARK} {uuid.uuid4().int % 1_000_000}"


def _png_bytes(width=1600, height=600, color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


async def _create(client, headers, **over):
    payload = {"title": _title(), "body": "Promoção de teste."}
    payload.update(over)
    resp = await client.post("/feed", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── serviço de mídia (unit) ─────────────────────────────────────────────────


def test_feed_image_preserva_proporcao(media_tmp):
    """Ao contrário de `save_barber_photo`, não recorta em quadrado."""
    rel = media.save_feed_image(3, 9, _png_bytes(1600, 600), "image/png")
    assert rel.startswith("org3/feed-9.webp?v=")

    with Image.open(media_tmp / "org3" / "feed-9.webp") as img:
        assert img.width == media.FEED_MAX_WIDTH  # encolheu de 1600
        assert img.height == 480                  # 600 * 1280/1600 → proporção mantida
        assert img.width != img.height


def test_feed_image_nao_amplia_imagem_pequena(media_tmp):
    media.save_feed_image(3, 10, _png_bytes(400, 300), "image/png")
    with Image.open(media_tmp / "org3" / "feed-10.webp") as img:
        assert (img.width, img.height) == (400, 300)


def test_feed_image_recusa_nao_imagem(media_tmp):
    with pytest.raises(media.MediaError):
        media.save_feed_image(3, 11, b"<svg><script/></svg>", "image/svg+xml")


# ─── painel: CRUD + RBAC ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_criar_editar_e_arquivar(client, auth_headers):
    post = await _create(client, auth_headers)
    post_id = post["id"]
    assert post["is_published"] is True
    assert post["image_url"] is None
    assert uuid.UUID(post["public_id"])  # public_id gerado pelo banco

    patched = await client.patch(
        f"/feed/{post_id}", headers=auth_headers, json={"title": f"{MARK} editado", "pinned": True}
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == f"{MARK} editado"
    assert patched.json()["pinned"] is True

    listed = await client.get("/feed", headers=auth_headers)
    assert any(p["id"] == post_id for p in listed.json())

    archived = await client.delete(f"/feed/{post_id}", headers=auth_headers)
    assert archived.status_code == 200

    listed = await client.get("/feed", headers=auth_headers)
    assert all(p["id"] != post_id for p in listed.json())
    # arquivado é 404 daqui em diante (soft delete, mas invisível)
    assert (await client.patch(f"/feed/{post_id}", headers=auth_headers, json={"pinned": False})).status_code == 404


@pytest.mark.asyncio
async def test_rascunho_so_aparece_com_include_unpublished(client, auth_headers):
    post = await _create(client, auth_headers, is_published=False)

    publicos = await client.get("/feed", headers=auth_headers)
    assert all(p["id"] != post["id"] for p in publicos.json())

    todos = await client.get(
        "/feed", headers=auth_headers, params={"include_unpublished": "true"}
    )
    assert any(p["id"] == post["id"] for p in todos.json())


@pytest.mark.asyncio
async def test_recepcao_le_mas_nao_publica(client, auth_headers, reception_headers):
    await _create(client, auth_headers)

    lido = await client.get("/feed", headers=reception_headers)
    assert lido.status_code == 200
    assert len(lido.json()) == 1

    negado = await client.post(
        "/feed", headers=reception_headers, json={"title": _title(), "body": "x"}
    )
    assert negado.status_code == 403

    # rascunho é conteúdo não divulgado: nem com o flag explícito
    rascunhos = await client.get(
        "/feed", headers=reception_headers, params={"include_unpublished": "true"}
    )
    assert rascunhos.status_code == 403


@pytest.mark.asyncio
async def test_barbeiro_403_em_tudo(client, auth_headers, barber_headers):
    post = await _create(client, auth_headers)

    assert (await client.get("/feed", headers=barber_headers)).status_code == 403
    assert (
        await client.post("/feed", headers=barber_headers, json={"title": _title(), "body": "x"})
    ).status_code == 403
    assert (
        await client.patch(f"/feed/{post['id']}", headers=barber_headers, json={"pinned": True})
    ).status_code == 403
    assert (await client.delete(f"/feed/{post['id']}", headers=barber_headers)).status_code == 403


@pytest.mark.asyncio
async def test_titulo_curto_422(client, auth_headers):
    resp = await client.post("/feed", headers=auth_headers, json={"title": "a", "body": "x"})
    assert resp.status_code == 422


# ─── imagem ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_e_remocao_de_imagem(client, auth_headers, media_tmp):
    post = await _create(client, auth_headers)

    enviado = await client.put(
        f"/feed/{post['id']}/imagem",
        headers=auth_headers,
        files={"file": ("cartaz.png", _png_bytes(1600, 600), "image/png")},
    )
    assert enviado.status_code == 200, enviado.text
    url = enviado.json()["image_url"]
    assert url.startswith(f"https://api.test/media/org{SEED_ORG_ID}/feed-{post['id']}.webp?v=")

    # reencodado preservando proporção (não é quadrado)
    with Image.open(media_tmp / f"org{SEED_ORG_ID}" / f"feed-{post['id']}.webp") as img:
        assert img.format == "WEBP"
        assert img.width != img.height

    removido = await client.delete(f"/feed/{post['id']}/imagem", headers=auth_headers)
    assert removido.status_code == 200
    assert removido.json()["image_url"] is None


@pytest.mark.asyncio
async def test_upload_tipo_invalido_422(client, auth_headers):
    post = await _create(client, auth_headers)
    resp = await client.put(
        f"/feed/{post['id']}/imagem",
        headers=auth_headers,
        files={"file": ("payload.svg", b"<svg onload=alert(1)/>", "image/svg+xml")},
    )
    assert resp.status_code == 422


# ─── rota pública ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publico_so_devolve_publicado_nao_arquivado_e_no_passado(
    client, auth_headers, public_seed
):
    visivel = await _create(client, auth_headers, title=f"{MARK} visivel")
    await _create(client, auth_headers, title=f"{MARK} rascunho", is_published=False)
    futuro = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    await _create(client, auth_headers, title=f"{MARK} futuro", published_at=futuro)
    arquivado = await _create(client, auth_headers, title=f"{MARK} arquivado")
    await client.delete(f"/feed/{arquivado['id']}", headers=auth_headers)

    resp = await client.get(f"{BASE}/feed")
    assert resp.status_code == 200
    titulos = [p["title"] for p in resp.json()["posts"]]
    assert titulos == [f"{MARK} visivel"]
    # a vitrine expõe o uuid, nunca o id sequencial do painel
    assert uuid.UUID(resp.json()["posts"][0]["id"])
    assert str(visivel["id"]) != resp.json()["posts"][0]["id"]


@pytest.mark.asyncio
async def test_publico_ordena_fixado_primeiro(client, auth_headers, public_seed):
    antigo = datetime.now(timezone.utc) - timedelta(days=10)
    fixado = await _create(
        client, auth_headers, title=f"{MARK} fixado",
        pinned=True, published_at=antigo.isoformat(),
    )
    await _create(client, auth_headers, title=f"{MARK} recente")

    posts = (await client.get(f"{BASE}/feed")).json()["posts"]
    assert posts[0]["title"] == f"{MARK} fixado"
    assert fixado["pinned"] is True


@pytest.mark.asyncio
async def test_publico_paginacao_por_cursor_nao_duplica_nem_pula(
    client, auth_headers, public_seed
):
    """Com offset, um post novo no topo entre as páginas empurraria a lista e
    repetiria um item. Com cursor em `published_at`, a 2ª página é estável."""
    base_time = datetime.now(timezone.utc) - timedelta(days=1)
    esperados = []
    for i in range(5):
        p = await _create(
            client, auth_headers,
            title=f"{MARK} p{i}",
            published_at=(base_time + timedelta(minutes=i)).isoformat(),
        )
        esperados.append(p["title"])
    esperados.reverse()  # published_at DESC

    pagina1 = (await client.get(f"{BASE}/feed", params={"limit": 2})).json()["posts"]
    assert [p["title"] for p in pagina1] == esperados[:2]

    # post novo entra no topo ENTRE as páginas
    await _create(client, auth_headers, title=f"{MARK} intruso")

    cursor = pagina1[-1]["published_at"]
    pagina2 = (
        await client.get(f"{BASE}/feed", params={"limit": 2, "before": cursor})
    ).json()["posts"]
    assert [p["title"] for p in pagina2] == esperados[2:4]

    vistos = [p["title"] for p in pagina1 + pagina2]
    assert len(vistos) == len(set(vistos)), "cursor duplicou item"
    assert f"{MARK} intruso" not in vistos


@pytest.mark.asyncio
async def test_publico_limit_acima_do_teto_422(client, public_seed):
    resp = await client.get(f"{BASE}/feed", params={"limit": 999})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_publicar_invalida_o_cache_do_feed(client, auth_headers, public_seed):
    """Sem a invalidação, o cache de 60s da 1ª página esconderia o post novo."""
    primeira = await client.get(f"{BASE}/feed")
    assert primeira.status_code == 200
    assert primeira.json()["posts"] == []

    novo = await _create(client, auth_headers, title=f"{MARK} cache")
    depois = (await client.get(f"{BASE}/feed")).json()["posts"]
    assert [p["title"] for p in depois] == [f"{MARK} cache"]
    assert novo["title"] == f"{MARK} cache"


@pytest.mark.asyncio
async def test_escrita_registra_invalidacao_em_background(client, auth_headers, monkeypatch):
    """A invalidação é `BackgroundTasks` (pós-commit), nunca no caminho crítico."""
    chamadas: list[tuple[int, list[str]]] = []

    async def _spy(org_id: int, tags: list[str]) -> None:
        chamadas.append((org_id, tags))

    monkeypatch.setattr("app.api.feed.invalidate_public_tags", _spy)

    post = await _create(client, auth_headers)
    assert chamadas == [(SEED_ORG_ID, ["public-feed"])]

    await client.patch(f"/feed/{post['id']}", headers=auth_headers, json={"pinned": True})
    await client.delete(f"/feed/{post['id']}", headers=auth_headers)
    assert len(chamadas) == 3
    assert all(tags == ["public-feed"] for _, tags in chamadas)


# ─── RLS ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rls_isola_post_entre_orgs(client, auth_headers):
    post = await _create(client, auth_headers)
    other_org_id = SEED_ORG_ID + 999_000

    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org_id)
        rows = (
            await session.execute(select(FeedPost).where(FeedPost.id == post["id"]))
        ).scalars().all()
        assert rows == []
