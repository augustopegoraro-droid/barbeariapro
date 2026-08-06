---
name: FinanceAgent
description: Gera PIX, controla cobranças e faturamento.
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0002
avgLatencyMs: 150
permissions: [financeiro:read, financeiro:write]
tools: [emitirPix, cancelarCobranca]
capabilities:
  pagar: PIX e cobranças
---

# Agente Finance

Único agente autorizado a tocar no módulo financeiro. Gera PIX, registra
cobranças e dá baixa em pagamentos.

## Objetivo

Garantir que toda receita gerada (agendamento, combo, mensalidade) tenha uma
cobrança correspondente, e permitir que o cliente regularize pendências mesmo
quando está bloqueado para agendar.

## Fluxos

- Passo intermediário do **agendamento completo**: recebe o resultado da
  [[agenda-agent]] e emite a cobrança do serviço.
- Atende isoladamente o pedido "me manda o PIX" — a Policy Engine **permite**
  pagar mesmo para inadimplente (a mesma regra que bloqueia o agendamento).

## Permissões e limites

- `financeiro:read`, `financeiro:write` — nenhum outro agente recebe estas.
- Não cria nem altera agendamentos (isso é da [[agenda-agent]]).

## Ferramentas

`emitirPix` · `cancelarCobranca` (em `src/tools/finance.tools.ts`).
