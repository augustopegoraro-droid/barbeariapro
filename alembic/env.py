"""Ambiente de execução das migrations Alembic.

Liga `target_metadata` ao `Base.metadata` dos models aprovados, de modo que
futuros `--autogenerate` comparem contra os models. A URL vem de DATABASE_URL
(env) com fallback para o alembic.ini.

Observação sobre ENUMs: os models declaram os tipos ENUM com `create_type=False`
(não recriam o tipo). A migration inicial cria/derruba os tipos explicitamente.
Por isso desativamos a comparação automática de tipos para autogenerate não
tentar recriar enums já existentes.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Garante que o pacote `models` seja importável a partir da raiz do projeto.
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from models import Base  # noqa: E402

config = context.config

# Sobrescreve a URL com a variável de ambiente, se presente.
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Gera SQL sem conexão (modo --sql)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=False,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Executa as migrations contra um banco real."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=False,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
