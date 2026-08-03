"""Catálogo de produtos vendáveis (Fase 1 do módulo de Produtos/Estoque/Vendas —
plano em /Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Cadastro de categorias/produtos/variações, sem estoque nem venda ainda (Fases
2+). Todo produto ganha, na criação, uma primeira variante — se `variants` vier
vazio no corpo, cria-se uma variante default "Único" com o preço informado em
`price`; do contrário, usa as variações do corpo. Arquivar (não deletar) é o
padrão do repo (molde `servicos.py`/`equipe.py`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services.audit import record_event
from models import Product, ProductCategory, ProductVariant, User

router = APIRouter(prefix="/produtos", tags=["produtos"])


async def _require_view(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "products.view")


async def _require_manage(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "products.manage")


# ── Schemas ──────────────────────────────────────────────────────────────────


class CategoriaOut(BaseModel):
    id: int
    name: str
    position: int
    active: bool

    class Config:
        from_attributes = True


class CategoriaIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    position: int = Field(1, ge=1)


class CategoriaUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    position: Optional[int] = Field(None, ge=1)
    active: Optional[bool] = None


class VarianteOut(BaseModel):
    id: int
    name: str
    sku: Optional[str]
    price: float
    cost_avg: float
    stock_qty: float
    min_stock: float
    active: bool


class VarianteIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    sku: Optional[str] = Field(None, max_length=64)
    price: Decimal = Field(..., ge=Decimal("0"))
    min_stock: Decimal = Field(Decimal("0"), ge=Decimal("0"))


class VarianteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    sku: Optional[str] = Field(None, max_length=64)
    price: Optional[Decimal] = Field(None, ge=Decimal("0"))
    min_stock: Optional[Decimal] = Field(None, ge=Decimal("0"))
    active: Optional[bool] = None


class ProdutoOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category_id: Optional[int]
    category_name: Optional[str]
    unit_of_measure: str
    tracks_stock: bool
    active: bool
    variants: list[VarianteOut]


class ProdutoListOut(BaseModel):
    id: int
    name: str
    category_id: Optional[int]
    category_name: Optional[str]
    unit_of_measure: str
    tracks_stock: bool
    active: bool
    variant_count: int
    price_from: Optional[float]


class ProdutoIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    category_id: Optional[int] = None
    unit_of_measure: str = Field("un", max_length=20)
    tracks_stock: bool = True
    price: Optional[Decimal] = Field(
        None, ge=Decimal("0"), description="Preço da variante default 'Único' (ignorado se `variants` vier preenchido)"
    )
    variants: Optional[list[VarianteIn]] = None


class ProdutoUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    category_id: Optional[int] = None
    unit_of_measure: Optional[str] = Field(None, max_length=20)
    tracks_stock: Optional[bool] = None
    active: Optional[bool] = None


def _variante_out(v: ProductVariant) -> VarianteOut:
    return VarianteOut(
        id=v.id,
        name=v.name,
        sku=v.sku,
        price=float(v.price),
        cost_avg=float(v.cost_avg),
        stock_qty=float(v.stock_qty),
        min_stock=float(v.min_stock),
        active=v.active,
    )


def _produto_out(p: Product) -> ProdutoOut:
    return ProdutoOut(
        id=p.id,
        name=p.name,
        description=p.description,
        category_id=p.category_id,
        category_name=p.category.name if p.category else None,
        unit_of_measure=p.unit_of_measure,
        tracks_stock=p.tracks_stock,
        active=p.active,
        variants=[_variante_out(v) for v in p.variants],
    )


def _produto_list_out(p: Product) -> ProdutoListOut:
    active_variants = [v for v in p.variants if v.active]
    prices = [v.price for v in active_variants] or [v.price for v in p.variants]
    return ProdutoListOut(
        id=p.id,
        name=p.name,
        category_id=p.category_id,
        category_name=p.category.name if p.category else None,
        unit_of_measure=p.unit_of_measure,
        tracks_stock=p.tracks_stock,
        active=p.active,
        variant_count=len(p.variants),
        price_from=float(min(prices)) if prices else None,
    )


async def _load_product(db: AsyncSession, product_id: int) -> Product:
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.variants), selectinload(Product.category))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Produto não encontrado.")
    return product


# ── Categorias ───────────────────────────────────────────────────────────────


@router.get("/categorias", response_model=list[CategoriaOut])
async def listar_categorias(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    include_inactive: bool = Query(False),
) -> list[CategoriaOut]:
    await _require_view(db, current_user)
    stmt = select(ProductCategory).order_by(ProductCategory.position, ProductCategory.name)
    if not include_inactive:
        stmt = stmt.where(ProductCategory.active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [CategoriaOut.model_validate(c) for c in rows]


@router.post("/categorias", response_model=CategoriaOut, status_code=http_status.HTTP_201_CREATED)
async def criar_categoria(
    body: CategoriaIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CategoriaOut:
    await _require_manage(db, current_user)

    existing = (
        await db.execute(
            select(ProductCategory).where(ProductCategory.name == body.name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Já existe uma categoria com esse nome.")

    category = ProductCategory(
        organization_id=current_user.organization_id,
        name=body.name,
        position=body.position,
    )
    db.add(category)
    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="products.category.create",
        resource_type="product_category",
        resource_id=category.id,
        after={"name": category.name, "position": category.position},
    )
    return CategoriaOut.model_validate(category)


@router.patch("/categorias/{id}", response_model=CategoriaOut)
async def atualizar_categoria(
    body: CategoriaUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> CategoriaOut:
    await _require_manage(db, current_user)

    category = (
        await db.execute(select(ProductCategory).where(ProductCategory.id == id))
    ).scalar_one_or_none()
    if category is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Categoria não encontrada.")

    before = {"name": category.name, "position": category.position, "active": category.active}
    if body.name is not None:
        category.name = body.name
    if body.position is not None:
        category.position = body.position
    if body.active is not None:
        category.active = body.active

    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="products.category.update",
        resource_type="product_category",
        resource_id=category.id,
        before=before,
        after={"name": category.name, "position": category.position, "active": category.active},
    )
    return CategoriaOut.model_validate(category)


# ── Produtos ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProdutoListOut])
async def listar_produtos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    include_inactive: bool = Query(False),
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None, max_length=150),
) -> list[ProdutoListOut]:
    await _require_view(db, current_user)

    stmt = (
        select(Product)
        .options(selectinload(Product.variants), selectinload(Product.category))
        .order_by(Product.name)
    )
    if not include_inactive:
        stmt = stmt.where(Product.active.is_(True))
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if search:
        stmt = stmt.where(Product.name.ilike(f"%{search}%"))

    rows = (await db.execute(stmt)).scalars().all()
    return [_produto_list_out(p) for p in rows]


@router.post("", response_model=ProdutoOut, status_code=http_status.HTTP_201_CREATED)
async def criar_produto(
    body: ProdutoIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ProdutoOut:
    await _require_manage(db, current_user)

    if body.category_id is not None:
        category = (
            await db.execute(
                select(ProductCategory).where(ProductCategory.id == body.category_id)
            )
        ).scalar_one_or_none()
        if category is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Categoria não encontrada.")

    variant_specs = body.variants
    if not variant_specs:
        if body.price is None:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Informe `price` (variante default) ou `variants` com pelo menos uma variação.",
            )
        variant_specs = [VarianteIn(name="Único", price=body.price)]

    product = Product(
        organization_id=current_user.organization_id,
        category_id=body.category_id,
        name=body.name,
        description=body.description,
        unit_of_measure=body.unit_of_measure,
        tracks_stock=body.tracks_stock,
    )
    db.add(product)
    await db.flush()

    for spec in variant_specs:
        db.add(
            ProductVariant(
                organization_id=current_user.organization_id,
                product_id=product.id,
                name=spec.name,
                sku=spec.sku,
                price=spec.price,
                min_stock=spec.min_stock,
            )
        )
    await db.flush()

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="products.product.create",
        resource_type="product",
        resource_id=product.id,
        after={"name": product.name, "tracks_stock": product.tracks_stock, "variants": len(variant_specs)},
    )
    return _produto_out(await _load_product(db, product.id))


@router.get("/{id}", response_model=ProdutoOut)
async def obter_produto(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> ProdutoOut:
    await _require_view(db, current_user)
    return _produto_out(await _load_product(db, id))


@router.patch("/{id}", response_model=ProdutoOut)
async def atualizar_produto(
    body: ProdutoUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> ProdutoOut:
    await _require_manage(db, current_user)
    product = await _load_product(db, id)

    if body.category_id is not None:
        category = (
            await db.execute(
                select(ProductCategory).where(ProductCategory.id == body.category_id)
            )
        ).scalar_one_or_none()
        if category is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Categoria não encontrada.")

    before = {"name": product.name, "active": product.active, "tracks_stock": product.tracks_stock}
    if body.name is not None:
        product.name = body.name
    if body.description is not None:
        product.description = body.description
    if body.category_id is not None:
        product.category_id = body.category_id
    if body.unit_of_measure is not None:
        product.unit_of_measure = body.unit_of_measure
    if body.tracks_stock is not None:
        product.tracks_stock = body.tracks_stock
    if body.active is not None:
        product.active = body.active

    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="products.product.update",
        resource_type="product",
        resource_id=product.id,
        before=before,
        after={"name": product.name, "active": product.active, "tracks_stock": product.tracks_stock},
    )
    return _produto_out(await _load_product(db, product.id))


# ── Variações ────────────────────────────────────────────────────────────────


@router.post("/{id}/variacoes", response_model=VarianteOut, status_code=http_status.HTTP_201_CREATED)
async def criar_variacao(
    body: VarianteIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> VarianteOut:
    await _require_manage(db, current_user)
    product = await _load_product(db, id)

    variant = ProductVariant(
        organization_id=current_user.organization_id,
        product_id=product.id,
        name=body.name,
        sku=body.sku,
        price=body.price,
        min_stock=body.min_stock,
    )
    db.add(variant)
    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="products.variant.create",
        resource_type="product_variant",
        resource_id=variant.id,
        after={"product_id": product.id, "name": variant.name, "price": float(variant.price)},
    )
    return _variante_out(variant)


@router.patch("/variacoes/{id}", response_model=VarianteOut)
async def atualizar_variacao(
    body: VarianteUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> VarianteOut:
    await _require_manage(db, current_user)

    variant = (
        await db.execute(select(ProductVariant).where(ProductVariant.id == id))
    ).scalar_one_or_none()
    if variant is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Variação não encontrada.")

    before = {"name": variant.name, "price": float(variant.price), "active": variant.active}
    if body.name is not None:
        variant.name = body.name
    if body.sku is not None:
        variant.sku = body.sku
    if body.price is not None:
        variant.price = body.price
    if body.min_stock is not None:
        variant.min_stock = body.min_stock
    if body.active is not None:
        variant.active = body.active

    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="products.variant.update",
        resource_type="product_variant",
        resource_id=variant.id,
        before=before,
        after={"name": variant.name, "price": float(variant.price), "active": variant.active},
    )
    return _variante_out(variant)
