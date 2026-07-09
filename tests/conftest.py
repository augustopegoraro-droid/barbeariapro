"""
Fixtures de integração — cliente ASGI httpx contra o app real + DB semeado (org 3).

Roda a aplicação em processo (ASGITransport) para que o pytest-cov capture a
cobertura dos endpoints. Autentica com o usuário owner semeado pelo scripts/seed.py.
"""
from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Organização e credenciais semeadas (scripts/seed.py, SEED_PASSWORD).
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))
SEED_OWNER_EMAIL = os.environ.get("SEED_OWNER_EMAIL", "taylor@barbeariapro.com")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "senha123")
SEED_BARBER_EMAIL = os.environ.get("SEED_BARBER_EMAIL", "pablo@barbeariapro.com")
SEED_MANAGER_EMAIL = os.environ.get("SEED_MANAGER_EMAIL", "gerente@barbeariapro.com")
SEED_RECEPTION_EMAIL = os.environ.get("SEED_RECEPTION_EMAIL", "recepcao@barbeariapro.com")


async def _login_headers(client, email: str):
    """Faz login e devolve o header Authorization; skip se o usuário não existir."""
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": SEED_PASSWORD, "organization_id": SEED_ORG_ID},
    )
    if resp.status_code != 200:
        import pytest as _pytest

        _pytest.skip(f"Usuário semeado indisponível ({email}, login {resp.status_code}).")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(autouse=True)
async def _flush_audit_tasks():
    """Sem isso, uma Task fire-and-forget de auditoria (`app/services/audit.py`)
    ainda em voo quando o event loop function-scoped do pytest-asyncio fecha
    fica órfã: a transação nunca comita, a conexão fica "idle in transaction"
    presa no pool e pode travar outro teste que dispute o mesmo lock/tabela
    (observado: `pg_advisory_xact_lock` de `audit_logs` bloqueando um DELETE
    de limpeza de `test_platform.py` por minutos). Produção não tem esse risco
    (um único event loop vive pela vida do processo, a Task sempre roda até o
    fim); é puramente um artefato do loop-por-teste do pytest-asyncio."""
    yield
    from app.services.audit import wait_for_pending

    await wait_for_pending()


@pytest_asyncio.fixture
async def client():
    """AsyncClient httpx falando direto com o app ASGI (mesmo processo)."""
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_headers(client):
    """Faz login como owner da org semeada e devolve o header Authorization."""
    resp = await client.post(
        "/auth/login",
        json={
            "email": SEED_OWNER_EMAIL,
            "password": SEED_PASSWORD,
            "organization_id": SEED_ORG_ID,
        },
    )
    if resp.status_code != 200:
        pytest.skip(
            f"DB semeado indisponível (login {resp.status_code}); "
            "rode scripts/seed.py para os testes de integração."
        )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def barber_headers(client):
    """Login como um barbeiro semeado (role=barber). Skip se DB não semeado."""
    resp = await client.post(
        "/auth/login",
        json={
            "email": SEED_BARBER_EMAIL,
            "password": SEED_PASSWORD,
            "organization_id": SEED_ORG_ID,
        },
    )
    if resp.status_code != 200:
        pytest.skip(f"Barbeiro semeado indisponível (login {resp.status_code}).")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def manager_headers(client):
    """Login como gerente semeado (role=manager)."""
    return await _login_headers(client, SEED_MANAGER_EMAIL)


@pytest_asyncio.fixture
async def reception_headers(client):
    """Login como recepcionista semeada (role=reception)."""
    return await _login_headers(client, SEED_RECEPTION_EMAIL)
