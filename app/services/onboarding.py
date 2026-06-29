"""Onboarding de uma nova org (substitui o uso manual de `scripts/seed.py`).

Fluxo (chamado pelo router de plataforma):
1. `platform.create_org(...)` (SECURITY DEFINER) cria organização + assinatura e
   devolve o novo `org_id` (ignora a RLS — o app não cria org sob RLS).
2. Aqui, na MESMA sessão helper, `set_current_org(new_org_id)` e semeia os filhos
   via ORM como `barber_app` (agora as policies casam por `organization_id`):
   Unit, BusinessHours (Seg–Sáb), User owner (role owner), Services do catálogo.

O `SERVICES_CATALOG` mora aqui (fonte única) e é reutilizado pelo `scripts/seed.py`.
A sessão é helper/isolada — o endpoint de plataforma nunca seta o GUC na sua própria
sessão (coerente com a arquitetura cross-tenant).
"""

from __future__ import annotations

from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import platform as platform_svc
from models import (
    BusinessHours,
    Service,
    ServiceCategory,
    Unit,
    UnitRole,
    User,
    UserUnit,
)

# ─── catálogo oficial de serviços (fonte única; reutilizado pelo seed) ──────────
# (nome, categoria, duração_min, preço, has_variable_price)
SERVICES_CATALOG: list[tuple[str, ServiceCategory, int, str, bool]] = [
    ("Corte Feminino", ServiceCategory.cabelo, 60, "190.00", False),
    ("Corte Masculino", ServiceCategory.cabelo, 45, "90.00", False),
    ("Corte Infantil", ServiceCategory.cabelo, 30, "80.00", False),
    ("Barba", ServiceCategory.barba, 30, "50.00", False),
    ("Corte + Barba", ServiceCategory.combo, 75, "140.00", False),
    ("Escova", ServiceCategory.cabelo, 60, "90.00", True),
    ("Manicure e Pedicure", ServiceCategory.estetica, 90, "75.00", False),
    ("Hidratação", ServiceCategory.quimica, 60, "90.00", True),
    ("Coloração", ServiceCategory.quimica, 120, "160.00", True),
    ("Selagem Masculina", ServiceCategory.quimica, 120, "180.00", False),
    ("Selagem Feminina", ServiceCategory.quimica, 150, "380.00", False),
    ("Sobrancelha", ServiceCategory.estetica, 30, "50.00", False),
    ("Sobrancelha com Henna", ServiceCategory.estetica, 45, "60.00", False),
    ("Mechas", ServiceCategory.quimica, 180, "600.00", True),
    ("Depilação de Nariz e Orelha", ServiceCategory.estetica, 20, "35.00", False),
]

# Horário comercial padrão: Seg–Sex 09–19h, Sáb 09–17h (schema: 0=Dom..6=Sáb).
_DEFAULT_HOURS: list[tuple[int, time, time]] = [
    *[(d, time(9, 0), time(19, 0)) for d in range(1, 6)],
    (6, time(9, 0), time(17, 0)),
]


async def _seed_org_children(
    session: AsyncSession,
    *,
    org_id: int,
    org_name: str,
    owner_email: str,
    owner_password: str,
) -> dict:
    """Semeia unidade, horários, usuário owner e catálogo de serviços na org.

    Pressupõe que a sessão já está sob RLS da `org_id` (set_current_org chamado
    pelo caller). Retorna um resumo {unit_id, owner_user_id, services}."""
    unit = Unit(
        organization_id=org_id,
        name=f"{org_name} - Unidade Central",
        timezone="America/Sao_Paulo",
    )
    session.add(unit)
    await session.flush()

    for weekday, open_t, close_t in _DEFAULT_HOURS:
        session.add(
            BusinessHours(
                unit_id=unit.id, weekday=weekday, open_time=open_t, close_time=close_t
            )
        )

    owner = User(
        organization_id=org_id,
        email=owner_email.strip().lower(),
        password_hash=hash_password(owner_password),
    )
    session.add(owner)
    await session.flush()
    session.add(UserUnit(user_id=owner.id, unit_id=unit.id, role=UnitRole.owner))

    for name, cat, dur, price, variable in SERVICES_CATALOG:
        session.add(
            Service(
                organization_id=org_id,
                name=name,
                category=cat,
                default_duration_min=dur,
                price=price,
                has_variable_price=variable,
            )
        )

    return {
        "unit_id": unit.id,
        "owner_user_id": owner.id,
        "services": len(SERVICES_CATALOG),
    }


async def provision_org(
    *,
    name: str,
    subdomain: str | None,
    plan_id: int,
    owner_email: str,
    owner_password: str,
) -> dict:
    """Cria uma org completa (org + assinatura + unidade + owner + serviços).

    Atômico: tudo numa única transação de sessão helper isolada. Devolve um resumo
    com `org_id`. Em erro, faz rollback (nada é criado)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            org_id = await platform_svc.create_org(
                session, name=name, subdomain=subdomain, plan_id=plan_id
            )
            # A org recém-criada já existe (via SECURITY DEFINER); escopa a sessão
            # a ela para semear os filhos sob RLS como barber_app.
            await set_current_org(session, org_id)
            children = await _seed_org_children(
                session,
                org_id=org_id,
                org_name=name,
                owner_email=owner_email,
                owner_password=owner_password,
            )
    return {"org_id": org_id, **children}
