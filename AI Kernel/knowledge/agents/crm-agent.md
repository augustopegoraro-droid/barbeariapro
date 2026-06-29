---
name: CrmAgent
description: Gerencia clientes, histórico e observações.
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0001
avgLatencyMs: 90
permissions: [crm:read, crm:write]
tools: [buscarCliente, registrarInteracao]
capabilities:
  consultar_cliente: Consulta e registro de cliente
---

# Agente CRM

Mantém a ficha do cliente: dados, preferências, observações e o histórico de
interações. É o agente de "memória estruturada" do negócio.

## Objetivo

Personalizar o atendimento (ex.: "prefere o Rafael", "máquina 2 nas laterais") e
deixar rastro de cada conversa para os próximos atendimentos — humanos ou IA.

## Fluxos

- Passo final do **agendamento completo**: depois de [[agenda-agent]] e
  [[finance-agent]], registra a interação na ficha do cliente.
- Fonte das `notes` que alimentam o contexto da requisição (curto prazo) e podem
  ser promovidas a conhecimento de longo prazo (vetorial).

## Permissões e limites

- `crm:read`, `crm:write` — não mexe em agenda nem em financeiro.

## Ferramentas

`buscarCliente` · `registrarInteracao` (em `src/tools/crm.tools.ts`).
