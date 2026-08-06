---
name: MarketingAgent
description: Cria campanhas e segmenta clientes.
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0003
avgLatencyMs: 200
permissions: [marketing:write]
tools: [criarCampanha, segmentarClientes]
capabilities:
  campanha: Campanhas e segmentação
---

# Agente Marketing

Cria campanhas de retorno/promoção e segmenta a base de clientes.

## Objetivo

Gerar receita ativa (reativação, promoções) a partir da base, sempre por um
canal autorizado — nunca a pedido de um cliente comum.

## Fluxos

- Disparado pelo **painel interno** (canal `api`, operador autorizado).
- A Policy Engine **nega** a intenção `campanha` vinda de um cliente comum
  (canal `whatsapp`) — autorização é determinística, não fica a cargo da IA.
- Pode usar a segmentação da [[crm-agent]] como insumo dos públicos-alvo.

## Permissões e limites

- Apenas `marketing:write` — não lê ficha de cliente nem toca em agenda/financeiro.

## Ferramentas

`criarCampanha` · `segmentarClientes` (em `src/tools/notify.tools.ts`).
