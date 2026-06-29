---
name: MembershipAgent
description: Gerencia pacotes, assinaturas e fidelidade (pontos) do cliente.
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0001
avgLatencyMs: 90
permissions: [membership:read, membership:write, fidelidade:read, fidelidade:write]
tools: [pacoteAtivo, assinaturaAtiva, saldoDePontos, tierAtual, comprarPacote, renovarMembership, cancelarMembership, usarPacote, resgatarPontos]
capabilities:
  consultar_pacote: Saldo de usos do pacote e validade
  consultar_assinatura: Status e vencimento da assinatura
  consultar_pontos: Saldo de pontos de fidelidade
  consultar_nivel: Nível atual e quanto falta para o próximo
  quanto_economizei: Economia acumulada com pacotes
  renovar_assinatura: Renovar assinatura/pacote (clona snapshot)
  comprar_pacote: Vender um novo pacote ou assinatura
  cancelar_assinatura: Cancelar assinatura/pacote
  usar_pacote: Dar baixa de um uso do pacote
  resgatar_pontos: Resgatar pontos como crédito de desconto
---

# Agente Membership (Pacotes · Fidelidade · Assinaturas)

Cliente-facing. Responde sobre os **próprios** dados do cliente via WhatsApp e
executa renovação, compra, cancelamento, uso de pacote e resgate de pontos.

## Objetivo

Dar autonomia ao cliente ("quantos cortes tenho?", "quando vence?", "quanto
falta para Ouro?") e converter (renovar/comprar/resgatar), com o saldo sempre
correto e auditável.

## Fidelidade — points-driven

O **nível deriva do saldo de pontos** (não de regra fixa): o cliente fica no
maior tier cujo `minPoints` ele alcança. O saldo vem de um **ledger append-only**
— nunca é mutado direto; toda mudança é um lançamento (earn/redeem/expire/
adjust/reversal) com `balanceAfter` para auditoria. Saldo **nunca fica negativo**.

## Fluxos

- Consultas (`consultar_*`, `quanto_economizei`): passo único, leitura.
- `renovar_assinatura` / `comprar_pacote`: **saga** Membership → [[crm-agent]]
  (registrar). **Sem `Payment`** — receita é reconhecida no uso (fiel ao backend).
  Se o CRM falhar, `compensate()` desfaz a criação.
- `usar_pacote`: dá baixa de 1 uso e credita 40 pontos.

## Permissões e limites

- `membership:read/write`, `fidelidade:read/write` (least privilege — não lê
  financeiro; a checagem de inadimplência é da Policy).
- **Não emite cobrança** — PIX é da [[finance-agent]].
- Sem identidade do cliente, pausa e pede o nome (`halt`).

## Políticas (Policy Engine)

- Cliente consulta livremente os **próprios** dados.
- **Inadimplente** é bloqueado de `renovar_assinatura`/`comprar_pacote` (deve
  regularizar antes) — mas pode consultar e pagar.
- **Resgate é permitido para inadimplente** (são pontos do próprio cliente; o
  crédito/voucher só vale no checkout, onde a pendência é tratada).
- Resgate que **rebaixaria o nível** exige confirmação explícita antes de debitar
  (fluxo multi-turn: o Kernel guarda o resgate pendente e conclui com "sim").
- **Renovar** só clona+zera para assinatura ilimitada ou pacote esgotado/vencido;
  pacote com usos válidos **não** é renovado (não descarta o pré-pago).
- **Pontos por uso só em pacote finito** (consumo pré-pago). Uso self-service de
  assinatura ilimitada **não credita pontos** (anti-farming); pontos de assinatura
  virão de atendimento concluído (fase futura).
- Saldo de pontos e de usos **nunca fica negativo** (validação na tool e no agente).
- **Defense-in-depth:** as tools de mutação validam o dono (`ownerId`) — não
  mutam membership de outro cliente mesmo se chamadas com id externo.

## Eventos (emitidos via `input.emit` → Event Bus / trilha de auditoria)

`PackageSold` (comprar_pacote) · `PackageUsed` (usar_pacote) ·
`MembershipRenewed` (renovar_assinatura) · `MembershipCancelled`
(cancelar_assinatura) · `PointsAdded` (uso/bônus) · `PointsRedeemed`
(resgatar_pontos) · `LevelChanged` (quando o resgate cruza um tier para baixo).

## KPIs

- Saldo médio de pontos e distribuição por nível.
- Taxa de renovação e churn de assinaturas.
- Economia média gerada por cliente (valor percebido).
- % de pacotes expirados sem uso (perda).

## Ferramentas

`pacoteAtivo` · `assinaturaAtiva` · `saldoDePontos` · `tierAtual` ·
`comprarPacote` · `renovarMembership` · `cancelarMembership` · `usarPacote` ·
`resgatarPontos` (em `src/tools/membership.tools.ts`).
