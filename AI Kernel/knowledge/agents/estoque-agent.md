---
name: EstoqueAgent
description: 'Controla produtos: estoque baixo, consumo e reposição.'
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0001
avgLatencyMs: 80
permissions: [estoque:read, estoque:write]
tools: [listarProdutos, estoqueBaixo, registrarConsumo, reporEstoque]
capabilities:
  consultar_estoque: Listar produtos e itens em falta
  registrar_consumo: Dar baixa de produto usado no atendimento
  repor_estoque: Registrar entrada/reposição de produto
---

# Agente Estoque

Operacional — recepção (Raquel). Controla produtos: o que está acabando, a baixa
de consumo no atendimento e a reposição quando chega mercadoria.

## Objetivo

Evitar ruptura de estoque sem dar trabalho à recepção: alerta automático quando
um item atinge o mínimo, baixa rápida no balcão e reposição em um comando.

## Permissões e limites

- `estoque:read`, `estoque:write` — não toca em agenda, financeiro nem caixa.

## Fluxos

- `consultar_estoque`: lista itens no/abaixo do mínimo (gatilho de reposição).
- `registrar_consumo`: dá baixa e avisa se cruzou o mínimo.
- `repor_estoque`: soma a entrada ao saldo do produto.

## Ferramentas

`listarProdutos` · `estoqueBaixo` · `registrarConsumo` · `reporEstoque`
(em `src/tools/estoque.tools.ts`).
