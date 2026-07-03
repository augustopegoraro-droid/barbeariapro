# Bugs — Painel SuperAdmin + Billing

> Bugs encontrados durante a missão (nos módulos tocados) e seu destino.
> Débitos pré-existentes de outros módulos ficam no backlog do CLAUDE.md §7, não aqui.

## Abertos

_(nenhum)_

## Observações herdadas relevantes ao escopo (não são bugs novos)

- `tenants_membership_mrr` itera orgs em loop O(N) com sessão helper por org (`app/api/platform.py:285-297`) — débito de escala anotado no próprio código; aceitável no volume atual, revisitar no MF.
- Trial criado com 365 dias hardcoded na função SQL `app_platform_create_org` (migration 0021) e `current_period_end` nunca é consumido — endereçado pelo M7 (ciclo de vida real).
- `plans.features` (jsonb) nunca foi lido por código — congelado por retrocompat; substituído por `plan_features`/`plan_limits` normalizados (SA-D03).

## Resolvidos

_(nenhum ainda)_
