---
name: CobrancaAgent
description: Cobra inadimplentes, reativa clientes sumidos e envia lembretes.
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0002
avgLatencyMs: 140
permissions: [financeiro:read, crm:read, notificacao:write]
tools: [listarInadimplentes, clientesInativos, agendamentosDeAmanha, enviarMensagem]
capabilities:
  cobrar_inadimplentes: Listar e cobrar quem está devendo
  reativar_clientes: Trazer de volta clientes inativos
  enviar_lembretes: Lembrar os agendamentos de amanhã
---

# Agente Cobrança & Relacionamento

Operacional — recepção (Raquel). Cuida da comunicação ativa com o cliente:
cobrança de pendências, reativação de quem sumiu e lembrete dos agendamentos.

## Objetivo

Reduzir inadimplência e no-show e trazer clientes de volta, com poucos cliques —
a recepção dispara em lote pelo painel.

## Permissões e limites

- `financeiro:read` — **lê** os PIX já pendentes; não cria cobrança (isso é da
  [[finance-agent]]).
- `crm:read` — identifica inativos a partir do histórico da [[crm-agent]].
- `notificacao:write` — envia mensagem (em produção: Cloud API / Chatwoot).

## Fluxos

- `cobrar_inadimplentes`: reaproveita o PIX pendente de cada inadimplente.
- `reativar_clientes`: sem agendamento futuro e sem atendimento há 30 dias.
- `enviar_lembretes`: agendamentos confirmados de amanhã.

## Ferramentas

`listarInadimplentes` · `clientesInativos` · `agendamentosDeAmanha` ·
`enviarMensagem` (em `src/tools/relacionamento.tools.ts`).
