# file: scripts/seed_platform_admin.py
"""Bootstrap do 1º superadmin da PLATAFORMA.

A aplicação (`barber_app`) NÃO escreve em `platform_admins` (defesa em
profundidade). Este script roda como dono (`ADMIN_DATABASE_URL`, role
`barber_owner`), igual ao `scripts/seed.py`, e faz upsert do superadmin.

Uso:
    PLATFORM_ADMIN_EMAIL=dono@taylorethedy.com \\
    PLATFORM_ADMIN_PASSWORD='senha-forte' \\
    python scripts/seed_platform_admin.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

# Carrega .env da raiz (se existir), como o seed.py.
_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from app.core.security import hash_password

ADMIN_URL = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://barber_owner:owner_pwd@localhost:5432/barbeariapro",
)
EMAIL = os.environ.get("PLATFORM_ADMIN_EMAIL", "").strip().lower()
PASSWORD = os.environ.get("PLATFORM_ADMIN_PASSWORD", "")


def main() -> None:
    if not EMAIL or not PASSWORD:
        raise SystemExit(
            "Defina PLATFORM_ADMIN_EMAIL e PLATFORM_ADMIN_PASSWORD no ambiente."
        )
    engine = create_engine(ADMIN_URL)
    pwd_hash = hash_password(PASSWORD)
    with Session(engine) as session, session.begin():
        # Upsert por email (idempotente): atualiza a senha se já existir.
        session.execute(
            text(
                """
                INSERT INTO platform_admins (email, password_hash)
                VALUES (:email, :pwd)
                ON CONFLICT (email)
                DO UPDATE SET password_hash = EXCLUDED.password_hash
                """
            ),
            {"email": EMAIL, "pwd": pwd_hash},
        )
    print(f"[platform_admin] upsert OK: {EMAIL}")


if __name__ == "__main__":
    main()
