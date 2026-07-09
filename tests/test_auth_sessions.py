"""Sessão, dispositivos e hardening de autenticação (D-68, Fase 3).

Cobre: refresh token rotativo + detecção de reuso, logout, troca de senha,
reset administrativo, sessões self-service, lockout de login, anti-
enumeração (V13), ticket de SSE de uso único (V4/V10) e FORCE ROW LEVEL
SECURITY (V16). Segue o padrão de `tests/conftest.py` (AsyncClient+ASGITransport,
login real contra DB semeado, skip gracioso se indisponível).
"""

from __future__ import annotations

import os

import pytest

from app.core.config import settings
from app.db.redis import get_redis

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
# Mesmos defaults de tests/conftest.py (org/credenciais semeadas por scripts/seed.py).
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))
SEED_OWNER_EMAIL = os.environ.get("SEED_OWNER_EMAIL", "taylor@barbeariapro.com")
SEED_BARBER_EMAIL = os.environ.get("SEED_BARBER_EMAIL", "pablo@barbeariapro.com")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "senha123")


async def _login(client, email: str = SEED_OWNER_EMAIL, password: str = SEED_PASSWORD) -> dict:
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": password, "organization_id": SEED_ORG_ID},
    )
    if resp.status_code != 200:
        pytest.skip(f"DB semeado indisponível (login {resp.status_code}).")
    return resp.json()


# ─── Login cria sessão + refresh token ──────────────────────────────────────
@pytest.mark.asyncio
async def test_login_creates_session_and_refresh_token(client):
    body = await _login(client)
    assert body["refresh_token"]
    assert body["access_token"]
    assert body["must_change_password"] is False

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.get("/auth/me/sessions", headers=headers)
    assert r.status_code == 200, r.text
    sessions = r.json()
    assert len(sessions) >= 1
    assert any(s["is_current"] for s in sessions)


# ─── Refresh rotaciona; reuso do token antigo revoga a sessão ──────────────
# Detecção cobre UMA geração (prev_refresh_token_hash) — o cenário real de
# ataque: dono legítimo e quem roubou o token correndo pra usar o MESMO token
# válido. Ver comentário em app/api/auth.py::refresh.
@pytest.mark.asyncio
async def test_refresh_rotates_and_detects_reuse(client):
    body = await _login(client)
    old_refresh = body["refresh_token"]  # T0

    r1 = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r1.status_code == 200, r1.text
    new_body = r1.json()  # T1 (corrente); prev=T0
    assert new_body["refresh_token"] != old_refresh
    assert new_body["access_token"] != body["access_token"]

    # reusar T0 (já rotacionado) é reuso → 401 + revoga a sessão inteira.
    r_reuse = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r_reuse.status_code == 401

    # a sessão inteira foi revogada: nem T1 (o token "correto" no momento do
    # reuso) funciona mais depois disso.
    r_after_revoke = await client.post(
        "/auth/refresh", json={"refresh_token": new_body["refresh_token"]}
    )
    assert r_after_revoke.status_code == 401


@pytest.mark.asyncio
async def test_refresh_invalid_token_401(client):
    r = await client.post("/auth/refresh", json={"refresh_token": "token-que-nunca-existiu"})
    assert r.status_code == 401


# ─── Logout revoga a sessão (idempotente) ──────────────────────────────────
@pytest.mark.asyncio
async def test_logout_revokes_session(client):
    body = await _login(client)
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    r = await client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 204

    # idempotente: repetir não é erro.
    r2 = await client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
    assert r2.status_code == 204

    # refresh não funciona mais.
    r3 = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r3.status_code == 401

    # o access token DESSA sessão também morre no ato (denylist do jti) — não
    # fica valendo pelos ~15min restantes, é kill imediato (defesa em profundidade).
    r4 = await client.get("/auth/me/sessions", headers=headers)
    assert r4.status_code == 401


# ─── Sessões self-service: listar/revogar ──────────────────────────────────
@pytest.mark.asyncio
async def test_revoke_my_session(client):
    body = await _login(client)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    sessions = (await client.get("/auth/me/sessions", headers=headers)).json()
    current = next(s for s in sessions if s["is_current"])

    r = await client.post(f"/auth/me/sessions/{current['id']}/revoke", headers=headers)
    assert r.status_code == 204

    # o refresh dessa sessão morreu junto.
    r2 = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_revoke_all_keeps_current(client):
    first = await _login(client)
    second = await _login(client)  # 2º "dispositivo" (mesmo usuário)
    headers = {"Authorization": f"Bearer {second['access_token']}"}

    r = await client.post("/auth/me/sessions/revoke-all", headers=headers)
    assert r.status_code == 204

    # a sessão do 2º login (a que fez a chamada) sobrevive.
    r_ok = await client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r_ok.status_code == 200, r_ok.text

    # a sessão do 1º login foi revogada.
    r_dead = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r_dead.status_code == 401


# ─── Troca de senha revoga as OUTRAS sessões ───────────────────────────────
@pytest.mark.asyncio
async def test_change_password_revokes_other_sessions(client):
    first = await _login(client)
    second = await _login(client)
    headers_second = {"Authorization": f"Bearer {second['access_token']}"}

    r = await client.post(
        "/auth/change-password",
        headers=headers_second,
        json={"current_password": SEED_PASSWORD, "new_password": SEED_PASSWORD},
    )
    assert r.status_code == 204, r.text

    # sessão que TROCOU sobrevive.
    r_ok = await client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r_ok.status_code == 200, r_ok.text

    # a OUTRA sessão foi revogada.
    r_dead = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r_dead.status_code == 401


@pytest.mark.asyncio
async def test_change_password_wrong_current_401(client):
    body = await _login(client)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "senha-errada", "new_password": "nova-senha-12345"},
    )
    assert r.status_code == 401


# ─── Anti-enumeração (V13): mesma resposta p/ usuário inexistente/senha errada ─
@pytest.mark.asyncio
async def test_login_anti_enumeration_same_response(client):
    # Limpa os PRÓPRIOS contadores de lockout antes e depois — sem isto,
    # reexecutar a suíte repetidas vezes na mesma janela de 15min (mesmo IP
    # de teste) acumula tentativas até bater o lockout (429), quebrando a
    # asserção de 401 nesta função (não relacionado ao teste de lockout, que
    # já limpa as SUAS próprias chaves).
    redis = get_redis()
    ip_key = "login_fail:ip:127.0.0.1"
    fake_combo_key = "login_fail:combo:127.0.0.1:usuario-que-nao-existe-xyz@example.com"
    owner_combo_key = f"login_fail:combo:127.0.0.1:{SEED_OWNER_EMAIL.lower()}"
    await redis.delete(ip_key, fake_combo_key, owner_combo_key)
    try:
        r_no_user = await client.post(
            "/auth/login",
            json={
                "email": "usuario-que-nao-existe-xyz@example.com",
                "password": "qualquer-coisa",
                "organization_id": SEED_ORG_ID,
            },
        )
        r_wrong_pw = await client.post(
            "/auth/login",
            json={
                "email": SEED_OWNER_EMAIL,
                "password": "senha-errada-de-proposito",
                "organization_id": SEED_ORG_ID,
            },
        )
        assert r_no_user.status_code == r_wrong_pw.status_code == 401
        assert r_no_user.json() == r_wrong_pw.json() == {"detail": "Credenciais inválidas"}
    finally:
        await redis.delete(ip_key, fake_combo_key, owner_combo_key)


# ─── Lockout de login (V2) ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_login_lockout_after_repeated_failures(client):
    redis = get_redis()
    ip_key = "login_fail:ip:127.0.0.1"
    combo_key = f"login_fail:combo:127.0.0.1:{SEED_OWNER_EMAIL.lower()}"
    await redis.delete(ip_key, combo_key)
    try:
        last = None
        for _ in range(settings.login_max_attempts + 1):
            last = await client.post(
                "/auth/login",
                json={
                    "email": SEED_OWNER_EMAIL,
                    "password": "senha-errada-de-proposito",
                    "organization_id": SEED_ORG_ID,
                },
            )
        assert last.status_code == 429, last.text

        # mesmo a senha CORRETA é barrada enquanto o lockout durar.
        blocked = await client.post(
            "/auth/login",
            json={
                "email": SEED_OWNER_EMAIL,
                "password": SEED_PASSWORD,
                "organization_id": SEED_ORG_ID,
            },
        )
        assert blocked.status_code == 429
    finally:
        await redis.delete(ip_key, combo_key)


# ─── Reset administrativo de senha (D-68, decisão: sem e-mail) ─────────────
@pytest.mark.asyncio
async def test_admin_reset_password_forces_change_and_revokes_sessions(client, auth_headers):
    """Usa um usuário DESCARTÁVEL (não o owner semeado) — um reset de senha
    no meio do teste que falhasse deixaria o seed compartilhado inutilizável
    para o resto da suíte (troca a senha real + liga must_change_password)."""
    if not ADMIN_URL:
        pytest.skip("ADMIN_DATABASE_URL ausente.")
    from sqlalchemy import create_engine, text

    from app.core.security import hash_password

    eng = create_engine(ADMIN_URL)
    target_email = "reset-target-d68@example.com"
    original_password = "senha-original-target-123"
    with eng.begin() as conn:
        conn.execute(
            text("DELETE FROM users WHERE organization_id=:o AND email=:e"),
            {"o": SEED_ORG_ID, "e": target_email},
        )
        conn.execute(
            text(
                "INSERT INTO users (organization_id, email, password_hash, is_active) "
                "VALUES (:o, :e, :h, true)"
            ),
            {"o": SEED_ORG_ID, "e": target_email, "h": hash_password(original_password)},
        )
        target_id = conn.execute(
            text("SELECT id FROM users WHERE organization_id=:o AND email=:e"),
            {"o": SEED_ORG_ID, "e": target_email},
        ).scalar_one()

    try:
        victim = await _login(client, target_email, original_password)

        r = await client.post(
            f"/admin/security/users/{target_id}/reset-password", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        temp_password = r.json()["temporary_password"]
        assert temp_password

        # a sessão pré-reset foi revogada.
        r_dead = await client.post(
            "/auth/refresh", json={"refresh_token": victim["refresh_token"]}
        )
        assert r_dead.status_code == 401

        # login com a senha temporária funciona e sinaliza troca obrigatória.
        r_login = await client.post(
            "/auth/login",
            json={
                "email": target_email,
                "password": temp_password,
                "organization_id": SEED_ORG_ID,
            },
        )
        assert r_login.status_code == 200, r_login.text
        assert r_login.json()["must_change_password"] is True
    finally:
        with eng.begin() as conn:
            conn.execute(
                text("DELETE FROM users WHERE organization_id=:o AND email=:e"),
                {"o": SEED_ORG_ID, "e": target_email},
            )


# ─── Painel do gestor: usuários e sessões de terceiros (D-68, UI de gestor) ─
@pytest.mark.asyncio
async def test_admin_list_users_includes_seeded_owner(client, auth_headers):
    r = await client.get("/admin/security/users", headers=auth_headers)
    assert r.status_code == 200, r.text
    emails = [u["email"] for u in r.json()]
    assert SEED_OWNER_EMAIL in emails
    owner = next(u for u in r.json() if u["email"] == SEED_OWNER_EMAIL)
    assert owner["role"] == "owner"
    assert owner["is_active"] is True


@pytest.mark.asyncio
async def test_admin_list_users_requires_permission(client, barber_headers):
    r = await client.get("/admin/security/users", headers=barber_headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_list_sessions_shows_owner_of_each_session(client, auth_headers):
    body = await _login(client)  # novo login do owner semeado — mais uma sessão dele
    try:
        r = await client.get("/admin/security/sessions", headers=auth_headers)
        assert r.status_code == 200, r.text
        sessions = r.json()
        assert sessions, "esperava ao menos a sessão recém-criada"
        assert all(s["user_id"] and s["user_email"] for s in sessions)
        assert any(s["user_email"] == SEED_OWNER_EMAIL for s in sessions)
    finally:
        await client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})


@pytest.mark.asyncio
async def test_admin_revoke_other_user_session(client, auth_headers):
    barber_login = await _login(client, SEED_BARBER_EMAIL)
    sessions = (await client.get("/admin/security/sessions", headers=auth_headers)).json()
    target = next(s for s in sessions if s["user_email"] == SEED_BARBER_EMAIL)

    r = await client.post(f"/admin/security/sessions/{target['id']}/revoke", headers=auth_headers)
    assert r.status_code == 204

    r_dead = await client.post(
        "/auth/refresh", json={"refresh_token": barber_login["refresh_token"]}
    )
    assert r_dead.status_code == 401


@pytest.mark.asyncio
async def test_admin_sessions_requires_permission(client, barber_headers):
    r = await client.get("/admin/security/sessions", headers=barber_headers)
    assert r.status_code == 403


# ─── Headers de segurança (V12) ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "Strict-Transport-Security" in r.headers or "strict-transport-security" in r.headers
    assert r.headers.get("content-security-policy")


@pytest.mark.asyncio
async def test_docs_disabled_by_default(client):
    # settings.docs_enabled=False por padrão — só ligar via env em dev/staging.
    if settings.docs_enabled:
        pytest.skip("DOCS_ENABLED=true neste ambiente — nada a validar aqui.")
    r = await client.get("/docs")
    assert r.status_code == 404


# ─── FORCE ROW LEVEL SECURITY (V16) ─────────────────────────────────────────
def test_force_row_level_security_on_sessions_table():
    if not ADMIN_URL:
        pytest.skip("ADMIN_DATABASE_URL ausente.")
    from sqlalchemy import create_engine, text

    eng = create_engine(ADMIN_URL)
    with eng.connect() as conn:
        row = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'sessions' AND relnamespace = 'public'::regnamespace"
            )
        ).one()
    assert row.relrowsecurity is True
    assert row.relforcerowsecurity is True
