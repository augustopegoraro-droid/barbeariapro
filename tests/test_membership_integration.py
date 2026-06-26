"""Testes de integração da mensalidade/assinatura do cliente final.

Rodam a aplicação ASGI em processo contra o Postgres semeado, sob RLS. Cada
teste é autocontido: cria o próprio cliente/plano, exercita o fluxo e limpa ao
final (cancela assinaturas, cancela agendamentos criados, arquiva o plano,
remove o cliente). Fixtures `client`/`auth_headers` vêm de conftest.

Cobre: CRUD de plano (RBAC manager), venda + snapshots, consumo (baixa de saldo,
limite, combo divergente), conclusão reconhecendo receita SEM Payment, e
reversão (cancelar/faltou restaura saldo).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio


def _uniq_phone() -> str:
    """Telefone E164 único por execução (soft-delete mantém o número ocupado)."""
    return "+55119" + str(time.time_ns())[-8:]


# Atendimentos de mensalidade concluídos não podem ser cancelados e ficam
# ocupando o horário permanentemente. Para que execuções não colidam, cada run
# recebe um dia-base aleatório E um deslocamento de minuto próprio — assim o par
# (dia, horário) é praticamente único por execução.
_NS = time.time_ns()
_RUN_DAY = 500 + _NS % 4000
_RUN_MINUTE = _NS // 1000 % 50


# ─── helpers de descoberta de dados semeados ─────────────────────────────────

async def _two_services(client, auth_headers):
    """Dois serviços ativos quaisquer (para testes que não consomem)."""
    resp = await client.get("/servicos", headers=auth_headers)
    if resp.status_code != 200:
        pytest.skip("Serviços indisponíveis no seed.")
    svcs = [s for s in resp.json() if s["is_active"]]
    if len(svcs) < 2:
        pytest.skip("Seed precisa de ao menos 2 serviços ativos.")
    return svcs[0], svcs[1]


async def _fresh_barber_and_two_services(client, auth_headers):
    """(barbeiro_novo, svc1, svc2). Cria um barbeiro descartável.

    Um barbeiro recém-criado é vinculado a todos os serviços ativos e NÃO tem
    histórico de agenda — assim o consumo nunca conflita com agendamentos
    deixados por outros testes/execuções (atendimentos de mensalidade concluídos
    não podem ser cancelados e ficariam ocupando o horário). É arquivado no
    cleanup.
    """
    svcs = await client.get("/servicos", headers=auth_headers)
    if svcs.status_code != 200:
        pytest.skip("Serviços indisponíveis no seed.")
    active = [s for s in svcs.json() if s["is_active"]]
    if len(active) < 2:
        pytest.skip("Seed precisa de ao menos 2 serviços ativos.")
    b = await client.post(
        "/equipe/barbeiros",
        json={"name": "Barbeiro Teste Mensalidade", "commission_pct": 0.5},
        headers=auth_headers,
    )
    assert b.status_code == 201, b.text
    return b.json(), active[0], active[1]


async def _make_client(client, auth_headers, phone):
    resp = await client.post(
        "/clientes",
        json={"name": "Cliente Mensalidade", "phone": phone},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _future(day_offset: int, hour: int):
    """Datetime tz-aware bem no futuro p/ evitar conflito com a agenda semeada."""
    base = datetime.now(timezone.utc) + timedelta(days=_RUN_DAY + day_offset)
    return base.replace(
        hour=hour, minute=_RUN_MINUTE, second=0, microsecond=0
    ).isoformat()


async def _create_plan(client, auth_headers, svc_ids, included_uses=2, price="120.00"):
    resp = await client.post(
        "/memberships/planos",
        json={
            "name": "Plano Teste Mensal",
            "price": price,
            "included_uses": included_uses,
            "duration_days": 30,
            "service_ids": svc_ids,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _cleanup(client, auth_headers, *, plan_id=None, client_id=None,
                   barber_id=None, membership_ids=(), appointment_ids=()):
    for appt_id in appointment_ids:
        await client.patch(
            f"/barbeiro/atendimento/{appt_id}/cancelar", headers=auth_headers
        )
    for mid in membership_ids:
        await client.post(f"/memberships/{mid}/cancelar", headers=auth_headers)
    if plan_id is not None:
        await client.delete(f"/memberships/planos/{plan_id}", headers=auth_headers)
    if client_id is not None:
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)
    if barber_id is not None:
        await client.patch(
            f"/equipe/barbeiros/{barber_id}/arquivar", headers=auth_headers
        )


# ─── AUTH ────────────────────────────────────────────────────────────────────

async def test_planos_sem_token_401(client):
    resp = await client.get("/memberships/planos")
    assert resp.status_code == 401


# ─── CRUD de plano ───────────────────────────────────────────────────────────

async def test_criar_plano_com_combo(client, auth_headers):
    s1, s2 = await _two_services(client, auth_headers)
    plan = await _create_plan(client, auth_headers, [s1["id"], s2["id"]])
    try:
        assert plan["included_uses"] == 2
        assert plan["duration_days"] == 30
        assert [i["service_id"] for i in plan["items"]] == [s1["id"], s2["id"]]
        # aparece na listagem
        lst = await client.get("/memberships/planos", headers=auth_headers)
        assert any(p["id"] == plan["id"] for p in lst.json())
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"])


async def test_plano_ilimitado_sem_valor_rejeitado(client, auth_headers):
    s1, _ = await _two_services(client, auth_headers)
    resp = await client.post(
        "/memberships/planos",
        json={
            "name": "Ilimitado Inválido",
            "price": "200.00",
            "duration_days": 30,
            "service_ids": [s1["id"]],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ─── venda + snapshots ───────────────────────────────────────────────────────

async def test_vender_grava_snapshot_e_saldo(client, auth_headers):
    s1, s2 = await _two_services(client, auth_headers)
    plan = await _create_plan(client, auth_headers, [s1["id"], s2["id"]], price="120.00")
    cid = await _make_client(client, auth_headers, _uniq_phone())
    sell = await client.post(
        "/memberships",
        json={"client_id": cid, "plan_id": plan["id"]},
        headers=auth_headers,
    )
    try:
        assert sell.status_code == 201, sell.text
        m = sell.json()
        assert m["status"] == "ativa"
        assert m["included_uses"] == 2
        assert m["remaining_uses"] == 2
        assert m["unit_recognized_value"] == 60.0  # 120 / 2
        assert m["price_paid"] == 120.0
        assert m["days_remaining"] >= 28

        # snapshot imutável: editar o plano depois NÃO muda a assinatura
        await client.patch(
            f"/memberships/planos/{plan['id']}",
            json={"price": "999.00"},
            headers=auth_headers,
        )
        det = await client.get(f"/memberships/{m['id']}", headers=auth_headers)
        assert det.json()["unit_recognized_value"] == 60.0
        assert det.json()["price_paid"] == 120.0
    finally:
        await _cleanup(
            client, auth_headers, plan_id=plan["id"], client_id=cid,
            membership_ids=[sell.json()["id"]] if sell.status_code == 201 else [],
        )


# ─── consumo + conclusão (receita sem Payment) + limite + reversão ──────────

async def test_consumo_conclusao_limite_e_reversao(client, auth_headers):
    barber, s1, s2 = await _fresh_barber_and_two_services(client, auth_headers)
    plan = await _create_plan(client, auth_headers, [s1["id"], s2["id"]], price="120.00")
    cid = await _make_client(client, auth_headers, _uniq_phone())
    sell = await client.post(
        "/memberships",
        json={"client_id": cid, "plan_id": plan["id"]},
        headers=auth_headers,
    )
    assert sell.status_code == 201, sell.text
    mid = sell.json()["id"]
    appt_ids = []
    try:
        assignments = [
            {"service_id": s1["id"], "barber_id": barber["id"]},
            {"service_id": s2["id"], "barber_id": barber["id"]},
        ]

        # combo divergente (só 1 serviço) → 422
        bad = await client.post(
            f"/memberships/{mid}/usos",
            json={"start_at": _future(0, 8),
                  "assignments": [assignments[0]]},
            headers=auth_headers,
        )
        assert bad.status_code == 422, bad.text

        # consumo 1 → cria agendamento, saldo 2→1
        u1 = await client.post(
            f"/memberships/{mid}/usos",
            json={"start_at": _future(1, 8), "assignments": assignments},
            headers=auth_headers,
        )
        assert u1.status_code == 201, u1.text
        appt1 = u1.json()["appointment_id"]
        appt_ids.append(appt1)
        assert u1.json()["total_amount"] == 60.0

        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 1
        assert det.json()["used_uses"] == 1

        # concluir o atendimento de mensalidade SEM method/amount → 200,
        # e NÃO deve criar Payment (receita via price_charged rateado)
        fin_before = await client.get(
            "/financeiro", params={"date": _future(1, 8)[:10]}, headers=auth_headers
        )
        conc = await client.patch(
            f"/barbeiro/atendimento/{appt1}/concluir", json={}, headers=auth_headers
        )
        assert conc.status_code == 200, conc.text

        # financeiro do dia inclui a receita rateada (60) e nenhum método de
        # pagamento (sem Payment) para esse atendimento de mensalidade
        fin = await client.get(
            "/financeiro", params={"date": _future(1, 8)[:10]}, headers=auth_headers
        )
        assert fin.status_code == 200
        # a receita do dia subiu em 60 vs. antes
        rev_before = fin_before.json().get("total_revenue", 0) if fin_before.status_code == 200 else 0
        assert fin.json()["total_revenue"] >= rev_before + 60.0

        # consumo 2 → saldo 1→0
        u2 = await client.post(
            f"/memberships/{mid}/usos",
            json={"start_at": _future(2, 8), "assignments": assignments},
            headers=auth_headers,
        )
        assert u2.status_code == 201, u2.text
        appt2 = u2.json()["appointment_id"]
        appt_ids.append(appt2)

        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 0

        # consumo 3 → 409 (sem saldo)
        u3 = await client.post(
            f"/memberships/{mid}/usos",
            json={"start_at": _future(3, 8), "assignments": assignments},
            headers=auth_headers,
        )
        assert u3.status_code == 409, u3.text

        # cancelar o 2º atendimento (ainda agendado) restaura o saldo → 1
        canc = await client.patch(
            f"/barbeiro/atendimento/{appt2}/cancelar", headers=auth_headers
        )
        assert canc.status_code == 200, canc.text
        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 1

        # agora há saldo de novo: consumo volta a funcionar
        u4 = await client.post(
            f"/memberships/{mid}/usos",
            json={"start_at": _future(4, 8), "assignments": assignments},
            headers=auth_headers,
        )
        assert u4.status_code == 201, u4.text
        appt_ids.append(u4.json()["appointment_id"])
    finally:
        await _cleanup(
            client, auth_headers, plan_id=plan["id"], client_id=cid,
            barber_id=barber["id"], membership_ids=[mid], appointment_ids=appt_ids,
        )
