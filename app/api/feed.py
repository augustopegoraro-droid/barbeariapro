# file: app/api/feed.py
"""Feed de novidades/promoções — lado do painel (Feature 1).

O gestor publica (título + texto + foto opcional) e o cliente final lê no site
público (`GET /public/{subdomain}/feed`, em `app/api/public.py`).

Molde `produtos.py` (permissão nomeada no topo de cada rota, RLS como barreira
de tenant, `record_event` em toda escrita) + `equipe.py::enviar_foto_barbeiro`
(upload de imagem). Arquivar é `deleted_at` — a tabela não tem GRANT de DELETE.

Toda escrita registra `invalidate_public_tags(org_id, ["public-feed"])` em
`BackgroundTasks`: roda depois do commit, e falha nela nunca derruba a escrita.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    UploadFile,
    status as http_status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services import media
from app.services.audit import record_event
from app.services.authz import resolve_permissions
from app.services.public_cache import FEED_TAG, invalidate_public_tags
from models import FeedPost, User

router = APIRouter(prefix="/feed", tags=["feed"])

VIEW = "content.feed.view"
MANAGE = "content.feed.manage"


# ── Schemas ──────────────────────────────────────────────────────────────────


class PostOut(BaseModel):
    id: int
    public_id: str
    title: str
    body: str
    image_url: Optional[str]
    is_published: bool
    published_at: datetime
    pinned: bool


class PostIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    body: str = Field(..., min_length=1, max_length=2000)
    is_published: bool = True
    pinned: bool = False
    published_at: Optional[datetime] = None


class PostUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=120)
    body: Optional[str] = Field(None, min_length=1, max_length=2000)
    is_published: Optional[bool] = None
    pinned: Optional[bool] = None
    published_at: Optional[datetime] = None


def _post_out(p: FeedPost) -> PostOut:
    return PostOut(
        id=p.id,
        public_id=str(p.public_id),
        title=p.title,
        body=p.body,
        image_url=media.public_url(p.image_path),
        is_published=p.is_published,
        published_at=p.published_at,
        pinned=p.pinned,
    )


async def _load_post(db: AsyncSession, post_id: int) -> FeedPost:
    post = (
        await db.execute(
            select(FeedPost)
            .where(FeedPost.id == post_id)
            .where(FeedPost.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Novidade não encontrada.")
    return post


def _audit(user: User, action: str, post: FeedPost, **extra) -> None:
    record_event(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action=action,
        resource_type="feed_post",
        resource_id=post.id,
        **extra,
    )


# ── Leitura ──────────────────────────────────────────────────────────────────


@router.get("", response_model=list[PostOut])
async def listar_posts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    include_unpublished: bool = Query(False),
) -> list[PostOut]:
    """Mural da org. Rascunhos só para quem também pode publicar."""
    await require_permission(db, current_user, VIEW)

    stmt = (
        select(FeedPost)
        .where(FeedPost.deleted_at.is_(None))
        .order_by(FeedPost.pinned.desc(), FeedPost.published_at.desc(), FeedPost.id.desc())
    )
    if include_unpublished:
        # Rascunho é conteúdo não divulgado: quem só tem `view` (recepção) não vê.
        if MANAGE not in await resolve_permissions(db, current_user):
            raise HTTPException(
                http_status.HTTP_403_FORBIDDEN,
                "Sem permissão para ver novidades não publicadas.",
            )
    else:
        stmt = stmt.where(FeedPost.is_published.is_(True))

    rows = (await db.execute(stmt)).scalars().all()
    return [_post_out(p) for p in rows]


# ── Escrita ──────────────────────────────────────────────────────────────────


@router.post("", response_model=PostOut, status_code=http_status.HTTP_201_CREATED)
async def criar_post(
    body: PostIn,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PostOut:
    await require_permission(db, current_user, MANAGE)

    post = FeedPost(
        organization_id=current_user.organization_id,
        title=body.title,
        body=body.body,
        is_published=body.is_published,
        pinned=body.pinned,
        created_by_user_id=current_user.id,
    )
    if body.published_at is not None:
        post.published_at = body.published_at
    db.add(post)
    await db.flush()
    await db.refresh(post)

    _audit(
        current_user,
        "content.feed.create",
        post,
        after={"title": post.title, "is_published": post.is_published, "pinned": post.pinned},
    )
    background_tasks.add_task(
        invalidate_public_tags, current_user.organization_id, [FEED_TAG]
    )
    return _post_out(post)


@router.patch("/{id}", response_model=PostOut)
async def atualizar_post(
    body: PostUpdate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> PostOut:
    await require_permission(db, current_user, MANAGE)
    post = await _load_post(db, id)

    before = {
        "title": post.title,
        "is_published": post.is_published,
        "pinned": post.pinned,
    }
    if body.title is not None:
        post.title = body.title
    if body.body is not None:
        post.body = body.body
    if body.is_published is not None:
        post.is_published = body.is_published
    if body.pinned is not None:
        post.pinned = body.pinned
    if body.published_at is not None:
        post.published_at = body.published_at
    post.updated_at = datetime.now(timezone.utc)

    await db.flush()
    _audit(
        current_user,
        "content.feed.update",
        post,
        before=before,
        after={"title": post.title, "is_published": post.is_published, "pinned": post.pinned},
    )
    background_tasks.add_task(
        invalidate_public_tags, current_user.organization_id, [FEED_TAG]
    )
    return _post_out(post)


@router.delete("/{id}", response_model=PostOut)
async def arquivar_post(
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> PostOut:
    """Arquiva (soft delete). A linha nunca é apagada — nem há GRANT para isso."""
    await require_permission(db, current_user, MANAGE)
    post = await _load_post(db, id)

    post.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    _audit(current_user, "content.feed.delete", post, before={"title": post.title})
    background_tasks.add_task(
        invalidate_public_tags, current_user.organization_id, [FEED_TAG]
    )
    return _post_out(post)


# ── Imagem ───────────────────────────────────────────────────────────────────


@router.put("/{id}/imagem", response_model=PostOut)
async def enviar_imagem(
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    file: Annotated[UploadFile, File(description="JPG, PNG, WebP ou HEIC (máx. 8 MB)")],
    id: int = Path(..., gt=0),
) -> PostOut:
    """Substitui a imagem do post (PUT: um post tem no máximo uma).

    Re-encodada em WebP preservando a proporção (cartaz não é retrato — ver
    `media.save_image_keep_ratio`), sem EXIF.
    """
    await require_permission(db, current_user, MANAGE)
    post = await _load_post(db, id)

    raw = await file.read()
    try:
        post.image_path = media.save_feed_image(
            current_user.organization_id, post.id, raw, file.content_type
        )
    except media.MediaError as exc:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    post.updated_at = datetime.now(timezone.utc)
    await db.flush()
    _audit(current_user, "content.feed.image.update", post)
    background_tasks.add_task(
        invalidate_public_tags, current_user.organization_id, [FEED_TAG]
    )
    return _post_out(post)


@router.delete("/{id}/imagem", response_model=PostOut)
async def remover_imagem(
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> PostOut:
    """Idempotente. Limpa o campo primeiro e só então apaga o arquivo: se o
    disco falhar, sobra um órfão invisível — nunca uma linha apontando ao vazio."""
    await require_permission(db, current_user, MANAGE)
    post = await _load_post(db, id)

    post.image_path = None
    post.updated_at = datetime.now(timezone.utc)
    await db.flush()
    media.delete_feed_image(current_user.organization_id, post.id)
    _audit(current_user, "content.feed.image.delete", post)
    background_tasks.add_task(
        invalidate_public_tags, current_user.organization_id, [FEED_TAG]
    )
    return _post_out(post)
