"""Testes das ferramentas de CORREÇÃO/REVERSÃO da assinatura (Fase 6 da auditoria).

Cobre os caminhos que antes deixavam erros da recepcionista 'presos' no sistema:
- reativar (desfaz cancelamento acidental dentro da vigência);
- editar/excluir uma venda equivocada SEM uso;
- estornar o uso de um atendimento já CONCLUÍDO pago por assinatura
  (o trap do 'Usar agora' por engano);
- renovação fechando a anterior (sem múltiplas ativas);
- desambiguação quando o cliente tem mais de uma assinatura ativa;
- status efetivo 'vencida' derivado em leitura.

Autocontidos; cada teste cria seus próprios dados e limpa no final. Token = owner
(conftest); RBAC por role é exercitado em test_scenarios.py no nível do guard.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio

_NS = time.time_ns()
_RUN_DAY = 9000 + _NS % 5000
_RUN_MINUTE = _NS // 1000 % 50


def _uniq_phone() -> str:
    return "+55119" + str(time.time_ns())[-8:]


def _future(day_offset: int, hour: int) -> str:
    base = datetime.now(timezone.utc) + timedelta(days=_RUN_DAY + day_offset)
    return base.replace(hour=hour, minute=_RUN_MINUTE, second=0, microsecond=0).isoformat()


def _corte_barba(svcs):
    corte = next((s for s in svcs if s.get("category") == "cabelo"), None)
    barba = next((s for s in svcs if s.get("category") == "barba"), None)
    if not corte or not barba:
        pytest.skip("Seed precisa de 1 serviço 'cabelo' e 1 'barba' ativos.")
    return corte, barba


async def _two_services(client, auth_headers):
    resp = await client.get("/servicos", headers=auth_headers)
    if resp.status_code != 200:
        pytest.skip("Serviços indisponíveis no seed.")
    return _corte_barba([s for s in resp.json() if s["is_active"]])


async def _fresh_barber_and_two_services(client, auth_headers):
    svcs = await client.get("/servicos", headers=auth_headers)
    if svcs.status_code != 200:
        pytest.skip("Serviços indisponíveis no seed.")
    corte, barba = _corte_barba([s for s in svcs.json() if s["is_active"]])
    b = await client.post(
        "/equipe/barbeiros",
        json={"name": "Barbeiro Teste Correção", "commission_pct": 0.5},
        headers=auth_headers,
    )
    assert b.status_code == 201, b.text
    return b.json(), corte, barba


async def _make_client(client, auth_headers, phone):
    resp = await client.post(
        "/clientes", json={"name": "Cliente Correção", "phone": phone}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _sell_custom(client, auth_headers, cid, *, combo_ids, uses=3, price="150.00",
                       duration=30, start_at=None):
    body = {
        "client_id": cid,
        "combo_service_ids": combo_ids,
        "included_uses": uses,
        "price": price,
        "duration_days": duration,
    }
    if start_at is not None:
        body["start_at"] = start_at
    resp = await client.post("/memberships", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _ledger_balance(client, auth_headers, cid):
    """(saldo de pontos atual, linhas do ledger). Saldo = balance_after da entrada mais recente."""
    r = await client.get(f"/loyalty/clients/{cid}/ledger", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    return (rows[0]["balance_after"] if rows else 0), rows


async def _cleanup(client, auth_headers, *, client_id=None, barber_id=None,
                   membership_ids=(), appointment_ids=()):
    for appt_id in appointment_ids:
        await client.patch(f"/barbeiro/atendimento/{appt_id}/cancelar", headers=auth_headers)
    for mid in membership_ids:
        await client.post(f"/memberships/{mid}/cancelar", headers=auth_headers)
    if barber_id is not None:
        await client.patch(f"/equipe/barbeiros/{barber_id}/arquivar", headers=auth_headers)
    if client_id is not None:
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)


# ─── reativar ────────────────────────────────────────────────────────────────

async def test_reativar_desfaz_cancelamento(client, auth_headers):
    corte, _ = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    m = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]])
    mid = m["id"]
    try:
        canc = await client.post(f"/memberships/{mid}/cancelar", headers=auth_headers)
        assert canc.status_code == 200 and canc.json()["status"] == "cancelada"

        reat = await client.post(f"/memberships/{mid}/reativar", headers=auth_headers)
        assert reat.status_code == 200, reat.text
        assert reat.json()["status"] == "ativa"
        assert reat.json()["remaining_uses"] == 3  # saldo preservado

        # reativar uma assinatura que não está cancelada → 409
        again = await client.post(f"/memberships/{mid}/reativar", headers=auth_headers)
        assert again.status_code == 409, again.text
    finally:
        await _cleanup(client, auth_headers, client_id=cid, membership_ids=[mid])


async def test_reativar_bloqueia_com_outra_ativa(client, auth_headers):
    corte, _ = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    m1 = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]])
    mid1 = m1["id"]
    mid2 = None
    try:
        await client.post(f"/memberships/{mid1}/cancelar", headers=auth_headers)
        # vende outra (agora há 1 ativa)
        m2 = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]])
        mid2 = m2["id"]
        # reativar a cancelada deve falhar: já há outra ativa
        reat = await client.post(f"/memberships/{mid1}/reativar", headers=auth_headers)
        assert reat.status_code == 409, reat.text
    finally:
        await _cleanup(client, auth_headers, client_id=cid,
                       membership_ids=[x for x in [mid1, mid2] if x])


# ─── editar / excluir (sem uso) ──────────────────────────────────────────────

async def test_editar_assinatura_sem_uso_recompoe(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    cid2 = await _make_client(client, auth_headers, _uniq_phone())
    m = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]],
                           uses=2, price="100.00")  # unit = 50
    mid = m["id"]
    try:
        assert m["unit_recognized_value"] == 50.0
        # corrige preço e nº de usos → recomputa unit (200/4 = 50 ainda? use 240/4=60)
        patch = await client.patch(
            f"/memberships/{mid}",
            json={"price": "240.00", "included_uses": 4, "client_id": cid2,
                  "combo_service_ids": [corte["id"], barba["id"]]},
            headers=auth_headers,
        )
        assert patch.status_code == 200, patch.text
        out = patch.json()
        assert out["unit_recognized_value"] == 60.0  # 240/4
        assert out["included_uses"] == 4
        assert out["client_id"] == cid2  # reatribuído ao cliente certo
        assert {c["service_id"] for c in out["combo"]} == {corte["id"], barba["id"]}
    finally:
        await _cleanup(client, auth_headers, client_id=cid, membership_ids=[mid])
        await _cleanup(client, auth_headers, client_id=cid2)


async def test_excluir_venda_sem_uso(client, auth_headers):
    corte, _ = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    m = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]])
    mid = m["id"]
    try:
        dele = await client.delete(f"/memberships/{mid}", headers=auth_headers)
        assert dele.status_code == 204, dele.text
        # sumiu mesmo
        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.status_code == 404
    finally:
        await _cleanup(client, auth_headers, client_id=cid)


async def test_editar_e_excluir_bloqueados_apos_uso(client, auth_headers):
    barber, corte, _ = await _fresh_barber_and_two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    m = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]], uses=3)
    mid = m["id"]
    appt_ids = []
    try:
        u = await client.post(
            f"/memberships/{mid}/usos",
            json={"start_at": _future(0, 8),
                  "assignments": [{"service_id": corte["id"], "barber_id": barber["id"]}]},
            headers=auth_headers,
        )
        assert u.status_code == 201, u.text
        appt_ids.append(u.json()["appointment_id"])

        # com uso, editar e excluir devem ser bloqueados (409)
        patch = await client.patch(f"/memberships/{mid}", json={"price": "10.00"},
                                   headers=auth_headers)
        assert patch.status_code == 409, patch.text
        dele = await client.delete(f"/memberships/{mid}", headers=auth_headers)
        assert dele.status_code == 409, dele.text
    finally:
        await _cleanup(client, auth_headers, client_id=cid, barber_id=barber["id"],
                       membership_ids=[mid], appointment_ids=appt_ids)


# ─── estorno de uso em atendimento CONCLUÍDO (o trap do 'Usar agora') ─────────

async def test_estornar_uso_concluido_devolve_saldo(client, auth_headers):
    barber, corte, _ = await _fresh_barber_and_two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    m = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]], uses=3)
    mid = m["id"]
    appt_ids = []
    try:
        # simula 'Usar agora': consome (avulso) e conclui
        u = await client.post(
            f"/memberships/{mid}/usos",
            json={"assignments": [{"service_id": corte["id"], "barber_id": barber["id"]}]},
            headers=auth_headers,
        )
        assert u.status_code == 201, u.text
        appt = u.json()["appointment_id"]
        appt_ids.append(appt)
        conc = await client.patch(f"/barbeiro/atendimento/{appt}/concluir",
                                  json={}, headers=auth_headers)
        assert conc.status_code == 200, conc.text

        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 2  # 3 - 1 consumido
        # a conclusão creditou pontos de fidelidade (earn)
        bal_conc, _ = await _ledger_balance(client, auth_headers, cid)
        assert bal_conc > 0, "conclusão deveria creditar pontos"

        # ANTES: este uso era irreversível. AGORA: estorno devolve o saldo.
        est = await client.patch(f"/barbeiro/atendimento/{appt}/estornar-uso",
                                 headers=auth_headers)
        assert est.status_code == 200, est.text
        assert est.json()["status"] == "cancelado"

        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.json()["remaining_uses"] == 3  # saldo do pacote devolvido

        # e os PONTOS de fidelidade do atendimento também foram revertidos
        bal_est, rows = await _ledger_balance(client, auth_headers, cid)
        assert bal_est < bal_conc, "estorno deveria reverter os pontos creditados"
        assert any(
            r["type"] == "reversal" and r["ref_appointment_id"] == appt for r in rows
        ), "deveria existir um lançamento 'reversal' para o agendamento estornado"

        # estorno de novo (atendimento já cancelado) → 409
        again = await client.patch(f"/barbeiro/atendimento/{appt}/estornar-uso",
                                   headers=auth_headers)
        assert again.status_code == 409, again.text
    finally:
        await _cleanup(client, auth_headers, client_id=cid, barber_id=barber["id"],
                       membership_ids=[mid], appointment_ids=appt_ids)


async def test_estornar_recusa_atendimento_em_dinheiro(client, auth_headers):
    barber, corte, _ = await _fresh_barber_and_two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    appt_ids = []
    over = {"price_override": 80.0} if corte.get("has_variable_price") else {}
    try:
        a = await client.post(
            "/agenda",
            json={"client_id": cid, "barber_id": barber["id"], "service_id": corte["id"],
                  "start_at": _future(1, 9), **over},
            headers=auth_headers,
        )
        assert a.status_code == 201, a.text
        appt = a.json()["id"]
        appt_ids.append(appt)
        # conclui em dinheiro
        conc = await client.patch(
            f"/barbeiro/atendimento/{appt}/concluir",
            json={"method": "dinheiro", "amount": 80.0}, headers=auth_headers,
        )
        assert conc.status_code == 200, conc.text
        # estornar-uso num atendimento pago em dinheiro → 409 (nada a estornar)
        est = await client.patch(f"/barbeiro/atendimento/{appt}/estornar-uso",
                                 headers=auth_headers)
        assert est.status_code == 409, est.text
    finally:
        await _cleanup(client, auth_headers, client_id=cid, barber_id=barber["id"],
                       appointment_ids=appt_ids)


# ─── renovação fecha a anterior + múltiplas ativas ───────────────────────────

async def test_renovar_fecha_a_anterior(client, auth_headers):
    corte, _ = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    m = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]])
    mid = m["id"]
    new_id = None
    try:
        renov = await client.post(f"/memberships/{mid}/renovar", headers=auth_headers)
        assert renov.status_code == 201, renov.text
        new_id = renov.json()["id"]

        # só pode existir UMA ativa: a nova. A antiga vira 'vencida'.
        cli = await client.get(f"/memberships/clientes/{cid}", headers=auth_headers)
        data = cli.json()
        assert data["active"] is not None
        assert data["active"]["id"] == new_id
        antiga = next(m for m in data["memberships"] if m["id"] == mid)
        assert antiga["status"] == "vencida"
    finally:
        await _cleanup(client, auth_headers, client_id=cid,
                       membership_ids=[x for x in [mid, new_id] if x])


async def test_multiplas_ativas_autopick_409(client, auth_headers):
    barber, corte, _ = await _fresh_barber_and_two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    m1 = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]])
    m2 = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]])
    appt_ids = []
    over = {"price_override": 80.0} if corte.get("has_variable_price") else {}
    try:
        a = await client.post(
            "/agenda",
            json={"client_id": cid, "barber_id": barber["id"], "service_id": corte["id"],
                  "start_at": _future(2, 10), **over},
            headers=auth_headers,
        )
        assert a.status_code == 201, a.text
        appt = a.json()["id"]
        appt_ids.append(appt)
        # attach sem membership_id com 2 ativas → 409 (precisa desambiguar)
        att = await client.post("/memberships/usos/attach",
                                json={"appointment_id": appt}, headers=auth_headers)
        assert att.status_code == 409, att.text
        # informando o membership_id, resolve
        att2 = await client.post(
            "/memberships/usos/attach",
            json={"appointment_id": appt, "membership_id": m1["id"]}, headers=auth_headers,
        )
        assert att2.status_code == 201, att2.text
    finally:
        await _cleanup(client, auth_headers, client_id=cid, barber_id=barber["id"],
                       membership_ids=[m1["id"], m2["id"]], appointment_ids=appt_ids)


# ─── status efetivo derivado ─────────────────────────────────────────────────

async def test_status_derivado_vencida(client, auth_headers):
    corte, _ = await _two_services(client, auth_headers)
    cid = await _make_client(client, auth_headers, _uniq_phone())
    past = (datetime.now(timezone.utc) - timedelta(days=10)).replace(microsecond=0)
    m = await _sell_custom(client, auth_headers, cid, combo_ids=[corte["id"]],
                           duration=1, start_at=past.isoformat())  # end_at = ~9 dias atrás
    mid = m["id"]
    try:
        det = await client.get(f"/memberships/{mid}", headers=auth_headers)
        assert det.status_code == 200
        # mesmo que o cron não tenha rodado, a leitura mostra 'vencida'
        assert det.json()["status"] == "vencida"
    finally:
        await _cleanup(client, auth_headers, client_id=cid, membership_ids=[mid])
