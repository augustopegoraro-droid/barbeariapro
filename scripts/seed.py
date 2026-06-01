# file: scripts/seed.py
"""Seed mínimo do P0.

Roda com a role DONA das tabelas (ADMIN_DATABASE_URL), que bypassa a RLS — é
o único jeito de inserir a `organizations` (a policy filtra por id, que só
existe após o INSERT). Cria 2 organizações, cada uma com 1 unidade e 1 usuário
'owner', e reaplica os GRANTs DML à role do app (que opera SOB RLS).

Uso:
    cp .env.example .env   # ajuste os segredos/URLs
    python scripts/seed.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

# Permite importar `app` e `models` a partir da raiz do projeto.
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from app.core.security import hash_password  # noqa: E402
from models import (  # noqa: E402
    Organization,
    Plan,
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
    """GRANTs DML para a role do app (necessários a cada recriação do schema)."""
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
        print(f"[grants] aplicados para a role '{APP_ROLE}'.")
    except Exception as exc:  # role pode não existir ainda
        print(f"[grants] AVISO: não foi possível aplicar ({exc}).")


def get_or_create_plan(session: Session) -> Plan:
    plan = session.execute(
        select(Plan).where(Plan.name == "MVP")
    ).scalar_one_or_none()
    if plan is None:
        plan = Plan(name="MVP", price_month=0, max_units=5, max_barbers=20)
        session.add(plan)
        session.flush()
        print(f"[plan] criado: id={plan.id}")
    return plan


def create_org(session: Session, plan: Plan, name: str, email: str) -> tuple[int, str]:
    existing = session.execute(
        select(Organization).where(Organization.name == name)
    ).scalar_one_or_none()
    if existing is not None:
        print(f"[org] '{name}' já existe (id={existing.id}); pulando.")
        return existing.id, email

    org = Organization(name=name)
    session.add(org)
    session.flush()

    session.add(
        Subscription(
            organization_id=org.id,
            plan_id=plan.id,
            current_period_start=NOW,
            current_period_end=NOW + timedelta(days=30),
        )
    )
    unit = Unit(organization_id=org.id, name=f"{name} - Unidade 1")
    session.add(unit)
    session.flush()

    user = User(
        organization_id=org.id,
        email=email,
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    session.flush()

    session.add(UserUnit(user_id=user.id, unit_id=unit.id, role=UnitRole.owner))
    print(f"[org] '{name}' criada: id={org.id} | login: {email}")
    return org.id, email


def main() -> None:
    engine = create_engine(ADMIN_URL)
    with Session(engine) as session, session.begin():
        reaplicar_grants(session)
        plan = get_or_create_plan(session)
        org_a = create_org(session, plan, "Barbearia A", "owner1@barbeariapro.test")
        org_b = create_org(session, plan, "Barbearia B", "owner2@barbeariapro.test")

    print("\n=== SEED CONCLUÍDO ===")
    for org_id, email in (org_a, org_b):
        print(f"  organization_id={org_id}  email={email}  senha={PASSWORD}")
    print(
        "\nLogin exige organization_id + email + senha. Faça login na org A e "
        "confira em /auth/me que organizations_visible == 1 (não enxerga a B)."
    )


if __name__ == "__main__":
    main()
