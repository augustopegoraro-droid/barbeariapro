# file: scripts/seed.py
"""Seed completo do MVP BarbeariaPro.

Cria:
  - Plano "MVP"
  - Organização "Barbearia Taylor e Thedy"
  - 1 Unidade
  - 1 Usuário owner
  - 2 Barbeiros (Taylor, Thedy) vinculados à unidade
  - 4 Serviços (Corte, Barba, Combo, Pigmentação)
  - Horários de funcionamento Seg-Sex 09h-19h / Sáb 09h-17h

Uso:
    cp .env.example .env   # ajuste os segredos/URLs
    python scripts/seed.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from app.core.security import hash_password  # noqa: E402
from models import (  # noqa: E402
    Barber,
    BarberUnit,
    BusinessHours,
    Organization,
    Plan,
    Service,
    ServiceCategory,
    Subscription,
    Unit,
    UnitRole,
    User,
    UserUnit,
)

ADMIN_URL = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://barber_owner:owner_pwd@localhost:5432/barbeariapro",
)
APP_ROLE = os.environ.get("APP_DB_ROLE", "barber_app")
PASSWORD = os.environ.get("SEED_PASSWORD", "senha123")

NOW = datetime.now(timezone.utc)


def reaplicar_grants(session: Session) -> None:
    try:
        session.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        session.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE "
                f"ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
            )
        )
        session.execute(
            text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
        )
        print(f"[grants] aplicados para '{APP_ROLE}'.")
    except Exception as exc:
        print(f"[grants] AVISO: {exc}")


def get_or_create_plan(session: Session) -> Plan:
    plan = session.execute(select(Plan).where(Plan.name == "MVP")).scalar_one_or_none()
    if plan is None:
        plan = Plan(name="MVP", price_month=0, max_units=5, max_barbers=20)
        session.add(plan)
        session.flush()
        print(f"[plan] criado: id={plan.id}")
    return plan


def seed_org(session: Session, plan: Plan) -> tuple[int, int]:
    """Cria a organização principal e retorna (org_id, unit_id)."""
    org_name = "Barbearia Taylor e Thedy"
    existing = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()

    if existing is not None:
        unit = session.execute(
            select(Unit).where(Unit.organization_id == existing.id)
        ).scalar_one_or_none()
        unit_id = unit.id if unit else 0
        print(f"[org] '{org_name}' já existe: org_id={existing.id}, unit_id={unit_id}")
        return existing.id, unit_id

    org = Organization(name=org_name)
    session.add(org)
    session.flush()

    session.add(
        Subscription(
            organization_id=org.id,
            plan_id=plan.id,
            current_period_start=NOW,
            current_period_end=NOW + timedelta(days=365),
        )
    )

    unit = Unit(
        organization_id=org.id,
        name="Taylor e Thedy - Unidade Central",
        timezone="America/Sao_Paulo",
        address="Rua das Barbearias, 123",
    )
    session.add(unit)
    session.flush()

    # Usuário owner
    user = User(
        organization_id=org.id,
        email="proprietario@barbearia.test",
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    session.flush()
    session.add(UserUnit(user_id=user.id, unit_id=unit.id, role=UnitRole.owner))
    print(f"[org] criada: org_id={org.id}, unit_id={unit.id}")
    print(f"[user] owner: proprietario@barbearia.test / {PASSWORD}")

    # Barbeiros
    barbers_data = [
        ("Taylor", "Cortes clássicos e modernos"),
        ("Thedy", "Barba e coloração"),
    ]
    for bname, bspec in barbers_data:
        existing_b = session.execute(
            select(Barber)
            .where(Barber.organization_id == org.id)
            .where(Barber.name == bname)
        ).scalar_one_or_none()
        if existing_b is None:
            b = Barber(
                organization_id=org.id,
                name=bname,
                specialty=bspec,
                commission_pct="0.40",
            )
            session.add(b)
            session.flush()
            session.add(BarberUnit(barber_id=b.id, unit_id=unit.id))
            print(f"[barber] {bname}: id={b.id}")

    # Serviços
    services_data = [
        ("Corte de Cabelo", ServiceCategory.cabelo, 30, "35.00"),
        ("Barba", ServiceCategory.barba, 30, "25.00"),
        ("Corte + Barba", ServiceCategory.combo, 60, "55.00"),
        ("Pigmentação de Barba", ServiceCategory.quimica, 45, "60.00"),
    ]
    for sname, scat, sdur, sprice in services_data:
        existing_s = session.execute(
            select(Service)
            .where(Service.organization_id == org.id)
            .where(Service.name == sname)
        ).scalar_one_or_none()
        if existing_s is None:
            s = Service(
                organization_id=org.id,
                name=sname,
                category=scat,
                default_duration_min=sdur,
                price=sprice,
            )
            session.add(s)
            session.flush()
            print(f"[service] {sname}: id={s.id} R${sprice} {sdur}min")

    # Horários de funcionamento
    # Seg(1)–Sex(5): 09h–19h | Sáb(6): 09h–17h
    weekdays_full = [1, 2, 3, 4, 5]
    weekdays_short = [6]
    for wd in weekdays_full:
        existing_bh = session.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id == unit.id)
            .where(BusinessHours.weekday == wd)
        ).scalar_one_or_none()
        if existing_bh is None:
            session.add(
                BusinessHours(
                    unit_id=unit.id,
                    weekday=wd,
                    open_time=time(9, 0),
                    close_time=time(19, 0),
                )
            )
    for wd in weekdays_short:
        existing_bh = session.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id == unit.id)
            .where(BusinessHours.weekday == wd)
        ).scalar_one_or_none()
        if existing_bh is None:
            session.add(
                BusinessHours(
                    unit_id=unit.id,
                    weekday=wd,
                    open_time=time(9, 0),
                    close_time=time(17, 0),
                )
            )
    print(f"[hours] Seg-Sex 09-19h, Sáb 09-17h configurados para unit_id={unit.id}")

    return org.id, unit.id


def main() -> None:
    engine = create_engine(ADMIN_URL)
    with Session(engine) as session, session.begin():
        reaplicar_grants(session)
        plan = get_or_create_plan(session)
        org_id, unit_id = seed_org(session, plan)

    print("\n=== SEED CONCLUÍDO ===")
    print(f"  BOT_ORGANIZATION_ID={org_id}")
    print(f"  BOT_UNIT_ID={unit_id}")
    print(f"\nAdicione ao .env:")
    print(f"  BOT_ORGANIZATION_ID={org_id}")
    print(f"  BOT_UNIT_ID={unit_id}")
    print(f"  BOT_API_KEY=<chave-segura-gerada-por-voce>")
    print(f"\nLogin owner: proprietario@barbearia.test / {PASSWORD}")
    print(f"  organization_id={org_id}")


if __name__ == "__main__":
    main()
