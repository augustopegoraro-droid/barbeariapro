# file: scripts/seed.py
"""Seed completo do MVP BarbeariaPro.

Cria / atualiza:
  - Plano "MVP"
  - Organização "Barbearia Taylor e Thedy"
  - 1 Unidade
  - 5 Profissionais: Taylor, Thedy (proprietários), Marciana, Sandra, Pablo
  - 14 Serviços oficiais com preços e flag has_variable_price
  - Vínculos barber_services (N:N)
  - Horários de funcionamento Seg-Sex 09h-19h / Sáb 09h-17h

Uso:
    python scripts/seed.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

# Carrega .env do diretório raiz do projeto (se existir)
_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from app.core.security import hash_password
from models import (
    Barber,
    BarberService,
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

# ─── catálogo oficial ─────────────────────────────────────────────────────────
# (nome, categoria, duração_min, preço, has_variable_price)
SERVICES_CATALOG: list[tuple[str, ServiceCategory, int, str, bool]] = [
    ("Corte Feminino",           ServiceCategory.cabelo,   60,  "190.00", False),
    ("Corte Masculino",          ServiceCategory.cabelo,   45,   "90.00", False),
    ("Corte Infantil",           ServiceCategory.cabelo,   30,   "80.00", False),
    ("Barba",                    ServiceCategory.barba,    30,   "50.00", False),
    ("Escova",                   ServiceCategory.cabelo,   60,   "90.00", True),
    ("Manicure e Pedicure",      ServiceCategory.estetica, 90,   "75.00", False),
    ("Hidratação",               ServiceCategory.quimica,  60,   "90.00", True),
    ("Coloração",                ServiceCategory.quimica, 120,  "160.00", True),
    ("Selagem Masculina",        ServiceCategory.quimica, 120,  "180.00", False),
    ("Selagem Feminina",         ServiceCategory.quimica, 150,  "380.00", False),
    ("Sobrancelha",              ServiceCategory.estetica, 30,   "50.00", False),
    ("Sobrancelha com Henna",    ServiceCategory.estetica, 45,   "60.00", False),
    ("Mechas",                   ServiceCategory.quimica, 180,  "600.00", True),
    ("Depilação de Nariz e Orelha", ServiceCategory.estetica, 20, "35.00", False),
]

# ─── profissionais ────────────────────────────────────────────────────────────
# (nome, especialidade, comissão, role, email, serviços_que_executa)
PROFESSIONALS: list[tuple[str, str, str, UnitRole, str, list[str]]] = [
    (
        "Taylor",
        "Cabeleireira e Barbeira",
        "0.40",
        UnitRole.owner,
        "taylor@barbeariapro.com",
        ["Corte Feminino", "Corte Masculino", "Corte Infantil", "Barba",
         "Escova", "Mechas", "Coloração", "Selagem Masculina", "Selagem Feminina"],
    ),
    (
        "Thedy",
        "Cabeleireiro e Barbeiro",
        "0.40",
        UnitRole.owner,
        "thedy@barbeariapro.com",
        ["Corte Feminino", "Corte Masculino", "Corte Infantil", "Barba",
         "Escova", "Mechas", "Coloração", "Selagem Masculina", "Selagem Feminina"],
    ),
    (
        "Marciana",
        "Cabeleireira e Manicure",
        "0.40",
        UnitRole.barber,
        "marciana@barbeariapro.com",
        ["Escova", "Selagem Feminina", "Selagem Masculina",
         "Coloração", "Hidratação", "Manicure e Pedicure"],
    ),
    (
        "Sandra",
        "Cabeleireira e Designer de Sobrancelhas",
        "0.40",
        UnitRole.barber,
        "sandra@barbeariapro.com",
        ["Corte Feminino", "Corte Masculino", "Escova", "Selagem Feminina",
         "Selagem Masculina", "Sobrancelha", "Sobrancelha com Henna",
         "Hidratação", "Coloração"],
    ),
    (
        "Pablo",
        "Barbeiro",
        "0.40",
        UnitRole.barber,
        "pablo@barbeariapro.com",
        ["Corte Masculino", "Corte Infantil", "Barba", "Coloração",
         "Selagem Masculina", "Hidratação", "Depilação de Nariz e Orelha"],
    ),
]


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
    else:
        print(f"[plan] já existe: id={plan.id}")
    return plan


def get_or_create_org(session: Session, plan: Plan) -> tuple[Organization, Unit]:
    org_name = "Barbearia Taylor e Thedy"
    org = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()

    if org is None:
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
        print(f"[org] criada: id={org.id}")
    else:
        print(f"[org] já existe: id={org.id}")

    unit = session.execute(
        select(Unit).where(Unit.organization_id == org.id)
    ).scalar_one_or_none()
    if unit is None:
        unit = Unit(
            organization_id=org.id,
            name="Taylor e Thedy - Unidade Central",
            timezone="America/Sao_Paulo",
            address="Rua das Barbearias, 123",
        )
        session.add(unit)
        session.flush()
        print(f"[unit] criada: id={unit.id}")
    else:
        print(f"[unit] já existe: id={unit.id}")

    return org, unit


def seed_business_hours(session: Session, unit: Unit) -> None:
    for wd, open_t, close_t in [
        *[(d, time(9, 0), time(19, 0)) for d in range(1, 6)],  # Seg–Sex
        (6, time(9, 0), time(17, 0)),                           # Sáb
    ]:
        exists = session.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id == unit.id)
            .where(BusinessHours.weekday == wd)
        ).scalar_one_or_none()
        if exists is None:
            session.add(BusinessHours(unit_id=unit.id, weekday=wd,
                                      open_time=open_t, close_time=close_t))
    print("[hours] Seg-Sex 09-19h, Sáb 09-17h configurados.")


def archive_old_services(session: Session, org_id: int) -> None:
    """Arquiva os 4 serviços genéricos do seed original."""
    old_names = {"Corte de Cabelo", "Barba", "Corte + Barba", "Pigmentação de Barba"}
    old = session.execute(
        select(Service)
        .where(Service.organization_id == org_id)
        .where(Service.name.in_(old_names))
        .where(Service.is_active.is_(True))
    ).scalars().all()
    for s in old:
        s.is_active = False
        print(f"[service] arquivado: '{s.name}' (id={s.id})")


def seed_services(session: Session, org_id: int) -> dict[str, Service]:
    """Cria os 14 serviços oficiais. Retorna mapa nome→Service."""
    service_map: dict[str, Service] = {}
    for name, cat, dur, price, variable in SERVICES_CATALOG:
        svc = session.execute(
            select(Service)
            .where(Service.organization_id == org_id)
            .where(Service.name == name)
        ).scalar_one_or_none()
        if svc is None:
            svc = Service(
                organization_id=org_id,
                name=name,
                category=cat,
                default_duration_min=dur,
                price=price,
                has_variable_price=variable,
            )
            session.add(svc)
            session.flush()
            print(f"[service] criado: '{name}' R${price} {dur}min variável={variable}")
        else:
            # Atualiza preço e flag caso existam divergências
            svc.category = cat
            svc.default_duration_min = dur
            svc.price = price
            svc.has_variable_price = variable
            svc.is_active = True
            print(f"[service] atualizado: '{name}' (id={svc.id})")
        service_map[name] = svc
    return service_map


def seed_professionals(
    session: Session,
    org: Organization,
    unit: Unit,
    service_map: dict[str, Service],
) -> None:
    for bname, bspec, comm, role, email, svc_names in PROFESSIONALS:
        # ── barber record ──────────────────────────────────────────────────
        barber = session.execute(
            select(Barber)
            .where(Barber.organization_id == org.id)
            .where(Barber.name == bname)
        ).scalar_one_or_none()
        if barber is None:
            barber = Barber(
                organization_id=org.id,
                name=bname,
                specialty=bspec,
                commission_pct=comm,
            )
            session.add(barber)
            session.flush()
            print(f"[barber] criado: '{bname}' id={barber.id}")
        else:
            barber.specialty = bspec
            print(f"[barber] já existe: '{bname}' id={barber.id}")

        # ── barber_unit ────────────────────────────────────────────────────
        bu = session.execute(
            select(BarberUnit)
            .where(BarberUnit.barber_id == barber.id)
            .where(BarberUnit.unit_id == unit.id)
        ).scalar_one_or_none()
        if bu is None:
            session.add(BarberUnit(barber_id=barber.id, unit_id=unit.id))
            print(f"[barber_unit] vinculado: '{bname}' → unit {unit.id}")

        # ── user ───────────────────────────────────────────────────────────
        user = session.execute(
            select(User)
            .where(User.organization_id == org.id)
            .where(User.email == email)
        ).scalar_one_or_none()
        if user is None:
            user = User(
                organization_id=org.id,
                email=email,
                password_hash=hash_password(PASSWORD),
            )
            session.add(user)
            session.flush()
            print(f"[user] criado: {email} id={user.id}")
        else:
            print(f"[user] já existe: {email} id={user.id}")

        # ── user_unit: garantir role correta e barber_id vinculado ─────────
        uu = session.execute(
            select(UserUnit)
            .where(UserUnit.user_id == user.id)
            .where(UserUnit.unit_id == unit.id)
        ).scalar_one_or_none()
        if uu is None:
            session.add(UserUnit(
                user_id=user.id,
                unit_id=unit.id,
                role=role,
                barber_id=barber.id,
            ))
            print(f"[user_unit] criado: '{bname}' role={role.value} barber_id={barber.id}")
        else:
            if uu.role != role or uu.barber_id != barber.id:
                uu.role = role
                uu.barber_id = barber.id
                print(f"[user_unit] atualizado: '{bname}' role={role.value} barber_id={barber.id}")

        # ── barber_services ────────────────────────────────────────────────
        for svc_name in svc_names:
            svc = service_map.get(svc_name)
            if svc is None:
                print(f"[WARN] serviço não encontrado: '{svc_name}'")
                continue
            bs = session.execute(
                select(BarberService)
                .where(BarberService.barber_id == barber.id)
                .where(BarberService.service_id == svc.id)
            ).scalar_one_or_none()
            if bs is None:
                session.add(BarberService(barber_id=barber.id, service_id=svc.id))
        print(f"[barber_services] '{bname}' → {len(svc_names)} serviços vinculados")


def main() -> None:
    engine = create_engine(ADMIN_URL)
    with Session(engine) as session, session.begin():
        reaplicar_grants(session)
        plan = get_or_create_plan(session)
        org, unit = get_or_create_org(session, plan)
        org_id = org.id
        unit_id = unit.id
        seed_business_hours(session, unit)
        archive_old_services(session, org_id)
        service_map = seed_services(session, org_id)
        seed_professionals(session, org, unit, service_map)

    print("\n=== SEED CONCLUÍDO ===")
    print(f"  BOT_ORGANIZATION_ID={org_id}")
    print(f"  BOT_UNIT_ID={unit_id}")
    print(f"\nCredenciais (senha: {PASSWORD}):")
    for _, _, _, _, email, _ in PROFESSIONALS:
        print(f"  {email}")


if __name__ == "__main__":
    main()
