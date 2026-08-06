---
name: AgendaAgent
description: Consulta, cria, cancela e remarca agendamentos.
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0002
avgLatencyMs: 120
permissions: [agenda:read, agenda:write]
tools: [consultarAgenda, criarAgendamento, cancelarAgendamento, reagendarEmMassa]
capabilities:
  consultar_horarios: Listar horários livres
  agendar: Criar agendamento
  remarcar: Remarcar agendamento
  cancelar: Cancelar agendamento
  reagendar_em_massa: Reagendar em lote a agenda de um profissional (ex.: falta)
---

# Agente Agenda

Responsável **apenas** por horários e agendamentos. Nunca acessa módulos
financeiros (regra do projeto — separação de poderes entre agentes).

## Objetivo

Dar à recepcionista (e ao cliente, via WhatsApp) a forma mais rápida de ver
horários livres, marcar, remarcar e cancelar, respeitando conflitos de agenda e
o vínculo barbeiro ↔ serviço.

## Fluxos

- No **agendamento completo**, é o primeiro passo do plano: encadeia com
  [[finance-agent]] (cobrança/PIX) e [[crm-agent]] (registro da interação).
- Em remarcação, cancela o agendamento atual e cria o novo no mesmo passo
  (compensável via saga, se um passo seguinte falhar).
- **Reagendamento em massa** (operacional/recepção): quando um profissional
  falta, realoca em lote os clientes dele para outro profissional livre no mesmo
  horário; quem não couber é sinalizado para a [[cobranca-agent]] avisar.

## Permissões e limites

- Lê e escreve só na agenda (`agenda:read`, `agenda:write`).
- **Não** emite cobrança nem consulta inadimplência — isso é da [[finance-agent]].
- Sem identidade do cliente resolvida, pausa o fluxo (`halt`) e pede o nome.

## Ferramentas

`consultarAgenda` · `criarAgendamento` · `cancelarAgendamento`
(implementadas em `src/tools/agenda.tools.ts`).
