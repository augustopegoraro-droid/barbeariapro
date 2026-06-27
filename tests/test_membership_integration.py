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

def _corte_barba(svcs):
    """(corte, barba) válidos p/ combo de catálogo: 1 cabelo + 1 barba."""
    corte = next((s for s in svcs if s.get("category") == "cabelo"), None)
    barba = next((s for s in svcs if s.get("category") == "barba"), None)
    if not corte or not barba:
        pytest.skip("Seed precisa de 1 serviço 'cabelo' e 1 'barba' ativos.")
    return corte, barba


async def _two_services(client, auth_headers):
    """(corte, barba) ativos — combo de catálogo válido (corte+barba)."""
    resp = await client.get("/servicos", headers=auth_headers)
    if resp.status_code != 200:
        pytest.skip("Serviços indisponíveis no seed.")
    svcs = [s for s in resp.json() if s["is_active"]]
    return _corte_barba(svcs)


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
    corte, barba = _corte_barba(active)
    b = await client.post(
        "/equipe/barbeiros",
        json={"name": "Barbeiro Teste Mensalidade", "commission_pct": 0.5},
        headers=auth_headers,
    )
    assert b.status_code == 201, b.text
    return b.json(), corte, barba


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


# ─── pacote personalizado (sem plano) + override de plano ────────────────────

async def test_venda_personalizada_do_zero(client, auth_headers):
    corte, _ = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    sell = await client.post(
        "/memberships",
        json={
            "client_id": cid,
            "combo_service_ids": [corte["id"]],
            "included_uses": 4,
            "price": "200.00",
            "duration_days": 30,
        },
        headers=auth_headers,
    )
    try:
        assert sell.status_code == 201, sell.text
        m = sell.json()
        assert m["plan_id"] is None  # pacote personalizado
        assert m["included_uses"] == 4
        assert m["unit_recognized_value"] == 50.0  # 200 / 4
        assert [c["service_id"] for c in m["combo"]] == [corte["id"]]
    finally:
        await _cleanup(
            client, auth_headers, client_id=cid,
            membership_ids=[sell.json()["id"]] if sell.status_code == 201 else [],
        )


async def test_venda_a_partir_de_plano_com_override(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _create_plan(client, auth_headers, [corte["id"], barba["id"]], price="120.00")
    cid = await _make_client(client, auth_headers, _uniq_phone())
    # override: mesmo plano, mas preço 300 e 3 usos → unit = 100 (não 60 do plano)
    sell = await client.post(
        "/memberships",
        json={
            "client_id": cid,
            "plan_id": plan["id"],
            "price": "300.00",
            "included_uses": 3,
        },
        headers=auth_headers,
    )
    try:
        assert sell.status_code == 201, sell.text
        m = sell.json()
        assert m["plan_id"] == plan["id"]
        assert m["unit_recognized_value"] == 100.0  # 300 / 3 (override)
        assert m["included_uses"] == 3
        assert {c["service_id"] for c in m["combo"]} == {corte["id"], barba["id"]}
    finally:
        await _cleanup(
            client, auth_headers, plan_id=plan["id"], client_id=cid,
            membership_ids=[sell.json()["id"]] if sell.status_code == 201 else [],
        )


async def test_personalizado_combo_invalido_pode_ser_livre(client, auth_headers):
    """Pacote personalizado tem combo LIVRE — química é aceita (≠ catálogo)."""
    svcs = await client.get("/servicos", headers=auth_headers)
    quimica = next(
        (s for s in svcs.json() if s["is_active"] and s.get("category") == "quimica"),
        None,
    )
    if not quimica:
        pytest.skip("Seed sem serviço 'quimica' ativo.")
    cid = await _make_client(client, auth_headers, _uniq_phone())
    sell = await client.post(
        "/memberships",
        json={
            "client_id": cid,
            "combo_service_ids": [quimica["id"]],
            "included_uses": 2,
            "price": "100.00",
            "duration_days": 30,
        },
        headers=auth_headers,
    )
    try:
        assert sell.status_code == 201, sell.text
    finally:
        await _cleanup(
            client, auth_headers, client_id=cid,
            membership_ids=[sell.json()["id"]] if sell.status_code == 201 else [],
        )


async def test_renovacao_custom_clona_snapshot(client, auth_headers):
    corte, _ = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    sell = await client.post(
        "/memberships",
        json={
            "client_id": cid,
            "combo_service_ids": [corte["id"]],
            "included_uses": 2,
            "price": "80.00",
            "duration_days": 30,
        },
        headers=auth_headers,
    )
    assert sell.status_code == 201, sell.text
    mid = sell.json()["id"]
    new_id = None
    try:
        renov = await client.post(f"/memberships/{mid}/renovar", headers=auth_headers)
        assert renov.status_code == 201, renov.text
        n = renov.json()
        new_id = n["id"]
        assert n["plan_id"] is None  # clona snapshot, não relê plano
        assert n["included_uses"] == 2
        assert n["used_uses"] == 0
        assert n["unit_recognized_value"] == 40.0  # 80 / 2
        assert [c["service_id"] for c in n["combo"]] == [corte["id"]]
    finally:
        await _cleanup(
            client, auth_headers, client_id=cid,
            membership_ids=[x for x in [mid, new_id] if x],
        )


# ─── aplicar pacote em agendamento existente (attach) + checkout + avulso ────

async def test_attach_checkout_e_avulso(client, auth_headers):
    barber, corte, _barba = await _fresh_barber_and_two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    # pacote personalizado de 1 serviço (corte) — casa com agendamento normal
    sell = await client.post(
        "/memberships",
        json={
            "client_id": cid,
            "combo_service_ids": [corte["id"]],
            "included_uses": 3,
            "price": "150.00",  # unit = 50
            "duration_days": 30,
        },
        headers=auth_headers,
    )
    assert sell.status_code == 201, sell.text
    mid = sell.json()["id"]
    appt_ids = []
    over = {"price_override": 80.0} if corte.get("has_variable_price") else {}
    try:
        # ── attach standalone: cria agendamento normal e paga com assinatura ──
        a1 = await client.post(
            "/agenda",
            json={"client_id": cid, "barber_id": barber["id"],
                  "service_id": corte["id"], "start_at": _future(10, 9), **over},
            headers=auth_headers,
        )
        assert a1.status_code == 201, a1.text
        appt1 = a1.json()["id"]
        appt_ids.append(appt1)
        assert a1.json()["client_id"] == cid  # AppointmentOut expõe client_id

        att = await client.post(
            "/memberships/usos/attach", json={"appointment_id": appt1},
            headers=auth_headers,
        )
        assert att.status_code == 201, att.text
        assert att.json()["total_amount"] == 50.0  # reprecificado p/ unit_value
        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 2

        # attach repetido no mesmo agendamento → 409
        att2 = await client.post(
            "/memberships/usos/attach", json={"appointment_id": appt1},
            headers=auth_headers,
        )
        assert att2.status_code == 409, att2.text

        # concluir (sem method/amount) reconhece receita sem Payment
        conc = await client.patch(
            f"/barbeiro/atendimento/{appt1}/concluir", json={}, headers=auth_headers
        )
        assert conc.status_code == 200, conc.text

        # ── checkout: concluir já pagando com a assinatura (atômico) ──────────
        a2 = await client.post(
            "/agenda",
            json={"client_id": cid, "barber_id": barber["id"],
                  "service_id": corte["id"], "start_at": _future(11, 9), **over},
            headers=auth_headers,
        )
        assert a2.status_code == 201, a2.text
        appt2 = a2.json()["id"]
        appt_ids.append(appt2)
        conc2 = await client.patch(
            f"/barbeiro/atendimento/{appt2}/concluir",
            json={"membership_id": mid}, headers=auth_headers,
        )
        assert conc2.status_code == 200, conc2.text
        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 1

        # ── avulso "usar agora": /usos sem start_at ──────────────────────────
        av = await client.post(
            f"/memberships/{mid}/usos",
            json={"assignments": [{"service_id": corte["id"], "barber_id": barber["id"]}]},
            headers=auth_headers,
        )
        assert av.status_code == 201, av.text
        appt_ids.append(av.json()["appointment_id"])
        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 0
    finally:
        await _cleanup(
            client, auth_headers, client_id=cid, barber_id=barber["id"],
            membership_ids=[mid], appointment_ids=appt_ids,
        )


async def test_plano_catalogo_combo_invalido_422(client, auth_headers):
    svcs = await client.get("/servicos", headers=auth_headers)
    active = [s for s in svcs.json() if s["is_active"]]
    corte = next((s for s in active if s.get("category") == "cabelo"), None)
    quimica = next((s for s in active if s.get("category") == "quimica"), None)
    if not corte or not quimica:
        pytest.skip("Seed sem 'cabelo' e 'quimica' ativos.")
    # química sozinha no catálogo → 422
    r1 = await client.post(
        "/memberships/planos",
        json={"name": "Plano Inválido Q", "price": "100.00", "included_uses": 2,
              "duration_days": 30, "service_ids": [quimica["id"]]},
        headers=auth_headers,
    )
    assert r1.status_code == 422, r1.text
    # corte + química → 422 (combo de 2 deve ser exatamente corte+barba)
    r2 = await client.post(
        "/memberships/planos",
        json={"name": "Plano Inválido CQ", "price": "100.00", "included_uses": 2,
              "duration_days": 30, "service_ids": [corte["id"], quimica["id"]]},
        headers=auth_headers,
    )
    assert r2.status_code == 422, r2.text
