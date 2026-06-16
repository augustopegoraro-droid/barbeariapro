# BarbeariaPro — backend FastAPI (multi-stage)
#
# Build:   docker build -t barbeariapro-backend .
# Runtime: uvicorn em python:3.12-slim, usuário não-root, porta 8000.
# Conecta no Postgres da infra existente via DATABASE_URL (injetado pelo compose).

# ──────────────────────────────────────────────────────────────
# Stage 1 — build: instala dependências num prefixo isolado
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /build
COPY requirements.txt .
# Wheels prontos (psycopg[binary], bcrypt, cryptography) — sem necessidade de toolchain.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ──────────────────────────────────────────────────────────────
# Stage 2 — runtime: imagem enxuta, sem build deps, usuário não-root
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Usuário não-root
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

# Dependências instaladas no stage de build
COPY --from=build /install /usr/local

# Código da aplicação (app + models são os únicos pacotes top-level importados em runtime).
# --chown garante que o usuário não-root `app` consiga ler os arquivos
# (alguns fontes no host têm modo 600 / owner-only).
COPY --chown=app:app app/ ./app/
COPY --chown=app:app models/ ./models/

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
