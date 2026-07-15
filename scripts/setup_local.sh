#!/usr/bin/env bash
# Setup local do BarbeariaPro (Mac M1 / Docker Desktop) — independente do GCP.
#
# Reproduz o ambiente da VM localmente: Postgres em container, role barber_app
# (RLS), migrations (alembic upgrade head → 0023) e privilégios. O app (backend+
# frontend) sobe depois via docker-compose.app.yml.
#
# Pré-requisitos: Docker Desktop rodando + .venv com deps (o mesmo dos testes).
# Uso:  bash scripts/setup_local.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PG_SUPER_PW="${POSTGRES_PASSWORD:-postgres}"
APP_PW="${APP_DB_PASSWORD:-senha123}"   # casa com DATABASE_URL do .env.docker
DB="${POSTGRES_DB:-barbeariapro}"
PGC="barbeariapro-postgres"

echo "== 1/5 Subindo Postgres (docker compose up -d postgres) =="
docker compose up -d postgres
echo "   aguardando Postgres..."
until docker exec "$PGC" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done

echo "== 2/5 Criando role barber_app (LOGIN, NOBYPASSRLS) =="
docker exec -e PGPASSWORD="$PG_SUPER_PW" -i "$PGC" psql -U postgres -d "$DB" -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='barber_app') THEN
    EXECUTE format('CREATE ROLE barber_app LOGIN PASSWORD %L NOBYPASSRLS', '${APP_PW}');
  END IF;
END \$\$;
GRANT USAGE ON SCHEMA public TO barber_app;
SQL

echo "== 3/5 Migrations (alembic upgrade head, como superuser postgres) =="
DATABASE_URL="postgresql+psycopg://postgres:${PG_SUPER_PW}@localhost:5432/${DB}" \
  .venv/bin/python -m alembic upgrade head

echo "== 4/5 Privilégios ao barber_app (tabelas/sequences atuais + futuras) =="
docker exec -e PGPASSWORD="$PG_SUPER_PW" -i "$PGC" psql -U postgres -d "$DB" -v ON_ERROR_STOP=1 <<SQL
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO barber_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO barber_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO barber_app;

-- V16: tabelas de PLATAFORMA (superadmin) não têm RLS de propósito — o
-- isolamento delas é "sem GRANT direto, só via função SECURITY DEFINER"
-- (molde platform_admin.py/D-55). O GRANT ON ALL TABLES acima concede a
-- todas por padrão; revoga explicitamente aqui pra este script local
-- reproduzir a mesma postura da prod, não só confiar em "esquecer de
-- conceder" em migrations futuras.
REVOKE ALL ON platform_admins, platform_alert_rules, platform_audit_log,
  platform_onboarding_overrides, platform_org_notes FROM barber_app;
SQL

echo "== 5/5 OK — banco local pronto (head 0023, role barber_app com RLS) =="
cat <<'NEXT'

Próximos passos:
  # Dados: (a) restaure um dump   psql ... < backup.sql
  #        (b) OU semeie exemplo:
  ADMIN_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/barbeariapro" \
    .venv/bin/python scripts/seed.py
  # OU re-importe da Trinks: scripts/import_trinks*.py (--org-id N --file ... --commit)

  # App (backend :8000 + frontend :3000):
  docker compose -f docker-compose.app.yml up -d --build backend frontend

Backend:  http://localhost:8000/health     Frontend: http://localhost:3000
NEXT
