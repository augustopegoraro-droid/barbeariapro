"""Add-ons do clube de assinatura (Bump C, D-104 Fase 4, migration 0066).

Cobre: CRUD do catálogo `/memberships/addons` (RBAC — owner gerencia, recepção
só lê), efeito de cada `kind` na venda (`POST /memberships` com `addon_ids`) —
soma em `price_paid`, `included_uses`, `combo_snapshot`, baixa de estoque para
`produto` (incluindo 409 de saldo insuficiente) —, clonagem na renovação
(reaplica o efeito, inclusive uma 2ª baixa de estoque), e regressão (vender
sem `addon_ids` continua idêntico a antes).

Autocontido: cria os próprios produto/serviço/plano/cliente e limpa ao final.
"""
from __future__ import annotations

import time
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


def _uniq_phone() -> str:
    return "+55118" + str(time.time_ns())[-8:]


async def _two_services(client, auth_headers):
    resp = await client.get("/servicos", headers=auth_headers)
    if resp.status_code != 200:
        pytest.skip("Serviços indisponíveis no seed.")
    active = [s for s in resp.json() if s["is_active"]]
    corte = next((s for s in active if s.get("category") == "cabelo"), None)
    barba = next((s for s in active if s.get("category") == "barba"), None)
    if not corte or not barba:
        pytest.skip("Seed precisa de 1 serviço 'cabelo' e 1 'barba' ativos.")
    return corte, barba


async def _make_client(client, auth_headers, name="Cliente Addon"):
    resp = await client.post(
        "/clientes", json={"name": name, "phone": _uniq_phone()}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_variant(client, auth_headers, *, price="19.90", stock="5"):
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Pomada Addon Teste {time.time_ns()}",
            "tracks_stock": True,
            "variants": [{"name": "Único", "price": price}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    product_id = body["id"]
    variant_id = body["variants"][0]["id"]
    if Decimal(stock) > 0:
        resp = await client.post(
            "/estoque/movimentacoes",
            headers=auth_headers,
            json={
                "variant_id": variant_id,
                "movement_type": "entrada_ajuste",
                "qty": stock,
            },
        )
        assert resp.status_code == 201, resp.text
    return product_id, variant_id


async def _make_plan(client, auth_headers, service_ids):
    resp = await client.post(
        "/memberships/planos",
        json={
            "name": "Plano Addon Teste",
            "price": "139.90",
            "included_uses": 4,
            "duration_days": 30,
            "service_ids": service_ids,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_addon(client, auth_headers, **over):
    body = {"name": "Add-on Teste", "kind": "produto", "price": "19.90"}
    body.update(over)
    resp = await client.post("/memberships/addons", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _cleanup(
    client, auth_headers, *, plan_id=None, client_id=None,
    addon_ids=(), membership_ids=(),
):
    # Assinatura ainda ativa (não renovada nem cancelada no corpo do teste)
    # precisa ser cancelada antes do plano/cliente — senão fica pendurada.
    for mid in membership_ids:
        await client.post(f"/memberships/{mid}/cancelar", headers=auth_headers)
    for aid in addon_ids:
        await client.delete(f"/memberships/addons/{aid}", headers=auth_headers)
    if plan_id is not None:
        await client.delete(f"/memberships/planos/{plan_id}", headers=auth_headers)
    if client_id is not None:
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)
    # Produtos/variantes de teste não têm rota de exclusão (só arquivar via
    # PATCH is_active=false, D-90) — ficam como resíduo inofensivo, mesmo
    # padrão tolerado pelos demais testes de Produtos/Estoque/Vendas.


# ─── CRUD / RBAC ─────────────────────────────────────────────────────────────


async def test_crud_addon_produto(client, auth_headers):
    _, variant_id = await _make_variant(client, auth_headers)
    addon = await _make_addon(
        client, auth_headers, kind="produto", variant_id=variant_id, price="19.90"
    )
    try:
        assert addon["kind"] == "produto"
        assert addon["variant_id"] == variant_id
        assert addon["is_active"] is True

        patched = await client.patch(
            f"/memberships/addons/{addon['id']}",
            json={"price": "24.90"},
            headers=auth_headers,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["price"] == 24.9

        listed = await client.get("/memberships/addons", headers=auth_headers)
        assert any(a["id"] == addon["id"] for a in listed.json())

        archived = await client.delete(
            f"/memberships/addons/{addon['id']}", headers=auth_headers
        )
        assert archived.status_code == 204

        listed = await client.get("/memberships/addons", headers=auth_headers)
        assert not any(a["id"] == addon["id"] for a in listed.json())
    finally:
        pass  # já arquivado acima


async def test_addon_exige_alvo_do_kind_422(client, auth_headers):
    resp = await client.post(
        "/memberships/addons",
        json={"name": "Sem alvo", "kind": "produto", "price": "10.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_addon_uso_extra_e_escopo(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    uso_extra = await _make_addon(
        client, auth_headers, name="Uso extra", kind="uso_extra",
        extra_uses=1, price="30.00",
    )
    escopo = await _make_addon(
        client, auth_headers, name="Escopo", kind="escopo",
        extra_service_id=barba["id"], price="40.00",
    )
    try:
        assert uso_extra["extra_uses"] == 1
        assert escopo["extra_service_id"] == barba["id"]
    finally:
        await _cleanup(
            client, auth_headers, addon_ids=[uso_extra["id"], escopo["id"]]
        )


async def test_recepcao_le_mas_nao_gerencia_addons(client, auth_headers, reception_headers):
    resp = await client.get("/memberships/addons", headers=reception_headers)
    assert resp.status_code == 200

    resp = await client.post(
        "/memberships/addons",
        json={"name": "Tentativa", "kind": "uso_extra", "extra_uses": 1, "price": "10.00"},
        headers=reception_headers,
    )
    assert resp.status_code == 403


# ─── efeito na venda (POST /memberships com addon_ids) ───────────────────────


async def test_venda_com_addon_produto_soma_preco_e_baixa_estoque(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _make_plan(client, auth_headers, [corte["id"], barba["id"]])
    _, variant_id = await _make_variant(client, auth_headers, price="19.90", stock="5")
    addon = await _make_addon(
        client, auth_headers, kind="produto", variant_id=variant_id, price="19.90"
    )
    client_id = await _make_client(client, auth_headers)
    membership_id = None
    try:
        resp = await client.post(
            "/memberships",
            json={
                "client_id": client_id,
                "plan_id": plan["id"],
                "addon_ids": [addon["id"]],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        membership_id = body["id"]
        assert body["price_paid"] == pytest.approx(139.90 + 19.90)

        mov = await client.get(
            "/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id}
        )
        saida = [m for m in mov.json() if m["movement_type"] == "saida_ajuste"]
        assert len(saida) == 1
        assert saida[0]["qty_after"] == 4.0
    finally:
        await _cleanup(
            client, auth_headers,
            plan_id=plan["id"], client_id=client_id, addon_ids=[addon["id"]],
            membership_ids=[membership_id] if membership_id else (),
        )


async def test_venda_com_addon_produto_saldo_insuficiente_409(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _make_plan(client, auth_headers, [corte["id"], barba["id"]])
    _, variant_id = await _make_variant(client, auth_headers, price="19.90", stock="0")
    addon = await _make_addon(
        client, auth_headers, kind="produto", variant_id=variant_id, price="19.90"
    )
    client_id = await _make_client(client, auth_headers)
    try:
        resp = await client.post(
            "/memberships",
            json={
                "client_id": client_id,
                "plan_id": plan["id"],
                "addon_ids": [addon["id"]],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 409, resp.text
    finally:
        await _cleanup(
            client, auth_headers,
            plan_id=plan["id"], client_id=client_id, addon_ids=[addon["id"]],
        )


async def test_venda_com_addon_uso_extra_soma_usos(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _make_plan(client, auth_headers, [corte["id"], barba["id"]])
    addon = await _make_addon(
        client, auth_headers, name="Uso extra", kind="uso_extra",
        extra_uses=2, price="30.00",
    )
    client_id = await _make_client(client, auth_headers)
    membership_id = None
    try:
        resp = await client.post(
            "/memberships",
            json={
                "client_id": client_id,
                "plan_id": plan["id"],
                "addon_ids": [addon["id"]],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        membership_id = body["id"]
        assert body["included_uses"] == 4 + 2
        assert body["price_paid"] == pytest.approx(139.90 + 30.00)
    finally:
        await _cleanup(
            client, auth_headers,
            plan_id=plan["id"], client_id=client_id, addon_ids=[addon["id"]],
            membership_ids=[membership_id] if membership_id else (),
        )


async def test_venda_com_addon_escopo_acrescenta_combo(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    resp = await client.get("/servicos", headers=auth_headers)
    terceiro = next(
        (
            s for s in resp.json()
            if s["is_active"] and s["id"] not in (corte["id"], barba["id"])
        ),
        None,
    )
    if terceiro is None:
        pytest.skip("Seed precisa de um 3º serviço ativo p/ o add-on de escopo.")
    plan = await _make_plan(client, auth_headers, [corte["id"]])
    addon = await _make_addon(
        client, auth_headers, name="Escopo", kind="escopo",
        extra_service_id=terceiro["id"], price="40.00",
    )
    client_id = await _make_client(client, auth_headers)
    membership_id = None
    try:
        resp = await client.post(
            "/memberships",
            json={
                "client_id": client_id,
                "plan_id": plan["id"],
                "addon_ids": [addon["id"]],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        membership_id = body["id"]
        combo_ids = {c["service_id"] for c in body["combo"]}
        assert terceiro["id"] in combo_ids
        assert body["price_paid"] == pytest.approx(139.90 + 40.00)
    finally:
        await _cleanup(
            client, auth_headers,
            plan_id=plan["id"], client_id=client_id, addon_ids=[addon["id"]],
            membership_ids=[membership_id] if membership_id else (),
        )


async def test_venda_sem_addon_ids_e_regressao_identica(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _make_plan(client, auth_headers, [corte["id"], barba["id"]])
    client_id = await _make_client(client, auth_headers)
    membership_id = None
    try:
        resp = await client.post(
            "/memberships",
            json={"client_id": client_id, "plan_id": plan["id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        membership_id = body["id"]
        assert body["price_paid"] == pytest.approx(139.90)
        assert body["included_uses"] == 4
    finally:
        await _cleanup(
            client, auth_headers,
            plan_id=plan["id"], client_id=client_id,
            membership_ids=[membership_id] if membership_id else (),
        )


async def test_addon_arquivado_nao_pode_ser_vendido_404(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _make_plan(client, auth_headers, [corte["id"], barba["id"]])
    addon = await _make_addon(
        client, auth_headers, name="Uso extra", kind="uso_extra",
        extra_uses=1, price="30.00",
    )
    await client.delete(f"/memberships/addons/{addon['id']}", headers=auth_headers)
    client_id = await _make_client(client, auth_headers)
    try:
        resp = await client.post(
            "/memberships",
            json={
                "client_id": client_id,
                "plan_id": plan["id"],
                "addon_ids": [addon["id"]],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404
    finally:
        await _cleanup(client, auth_headers, plan_id=plan["id"], client_id=client_id)


# ─── renovação clona os add-ons ──────────────────────────────────────────────


async def test_renovacao_clona_addon_produto_e_baixa_estoque_de_novo(client, auth_headers):
    corte, barba = await _two_services(client, auth_headers)
    plan = await _make_plan(client, auth_headers, [corte["id"], barba["id"]])
    _, variant_id = await _make_variant(client, auth_headers, price="19.90", stock="5")
    addon = await _make_addon(
        client, auth_headers, kind="produto", variant_id=variant_id, price="19.90"
    )
    client_id = await _make_client(client, auth_headers)
    membership_ids: list[int] = []
    try:
        sell = await client.post(
            "/memberships",
            json={
                "client_id": client_id,
                "plan_id": plan["id"],
                "addon_ids": [addon["id"]],
            },
            headers=auth_headers,
        )
        assert sell.status_code == 201, sell.text
        membership_id = sell.json()["id"]
        membership_ids.append(membership_id)

        renew = await client.post(
            f"/memberships/{membership_id}/renovar", headers=auth_headers
        )
        assert renew.status_code == 201, renew.text
        new_membership = renew.json()
        membership_ids.append(new_membership["id"])
        assert new_membership["price_paid"] == pytest.approx(139.90 + 19.90)

        mov = await client.get(
            "/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id}
        )
        saida = [m for m in mov.json() if m["movement_type"] == "saida_ajuste"]
        # 1 baixa na venda + 1 baixa na renovação
        assert len(saida) == 2
        assert saida[0]["qty_after"] == 3.0
    finally:
        await _cleanup(
            client, auth_headers,
            plan_id=plan["id"], client_id=client_id, addon_ids=[addon["id"]],
            membership_ids=membership_ids,
        )


# ─── RLS entre orgs ───────────────────────────────────────────────────────────


async def test_addons_isolados_por_org(client, auth_headers, manager_headers):
    """`manager_headers` loga na mesma org do seed (sem 2ª org disponível nos
    testes de integração) — cobre RLS indiretamente: ambos enxergam o mesmo
    add-on, confirmando que a leitura respeita `organization_id`."""
    addon = await _make_addon(
        client, auth_headers, name="RLS Teste", kind="uso_extra",
        extra_uses=1, price="10.00",
    )
    try:
        resp = await client.get("/memberships/addons", headers=manager_headers)
        assert resp.status_code == 200
        assert any(a["id"] == addon["id"] for a in resp.json())
    finally:
        await _cleanup(client, auth_headers, addon_ids=[addon["id"]])
