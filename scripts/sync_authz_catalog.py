# file: scripts/sync_authz_catalog.py
"""Sincroniza o catálogo de permissões + papéis de sistema no banco (deploy).

Idempotente. Roda como DONO do banco (ADMIN_DATABASE_URL) para inserir os papéis
de sistema (organization_id NULL, ignorando RLS). Use após aplicar a migration
0037 e sempre que `app/core/permissions.py` mudar.

    python scripts/sync_authz_catalog.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

# Carrega .env da raiz (se existir), como o scripts/seed.py.
_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from app.services.authz_seed import sync_system_catalog  # noqa: E402

ADMIN_URL = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://barber_owner:owner_pwd@localhost:5432/barbeariapro",
)


def main() -> None:
    engine = create_engine(ADMIN_URL)
    with Session(engine) as session, session.begin():
        summary = sync_system_catalog(session)
    print(f"[authz] catálogo sincronizado: {summary}")


if __name__ == "__main__":
    main()
