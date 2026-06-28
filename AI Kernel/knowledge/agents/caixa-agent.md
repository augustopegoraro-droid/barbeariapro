---
name: CaixaAgent
description: Abre, movimenta, confere e fecha o caixa.
version: 1.0.0
health: healthy
estimatedCostUsd: 0.0001
avgLatencyMs: 80
permissions: [caixa:read, caixa:write, financeiro:read]
tools: [abrirCaixa, registrarMovimento, resumoCaixa, fecharCaixa]
capabilities:
  abrir_caixa: Abrir o caixa do dia com fundo de troco
  movimentar_caixa: Registrar sangria ou suprimento
  consultar_caixa: Saldo e movimentos do caixa
  fechar_caixa: Conferir e fechar o caixa
---

# Agente Caixa

Operacional — recepção (Raquel). Controla o dinheiro em espécie do dia: abertura
com fundo de troco, sangrias/suprimentos, conferência e fechamento.

## Objetivo

Dar à recepção controle simples e auditável do caixa, com fechamento que compara
o **esperado** (soma dos movimentos) com o **contado**, apontando sobra/falta.

## Permissões e limites

- `caixa:read`, `caixa:write` — ciclo de vida do caixa.
- `financeiro:read` — só leitura, para conciliar. **Não cria cobranças**: PIX e
  faturamento são da [[finance-agent]].

## Fluxos

- Só pode haver **um caixa aberto** por vez.
- Sangria sai (valor negativo); suprimento/venda entram (positivo).

## Ferramentas

`abrirCaixa` · `registrarMovimento` · `resumoCaixa` · `fecharCaixa`
(em `src/tools/caixa.tools.ts`).
