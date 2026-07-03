# Roadmap — Painel SuperAdmin + Billing

> Missão iniciada em 2026-07-03. Ordem de execução decidida (M1→MF).
> Progresso vivo em `progress.md`; pendências externas em `blockers.md`.

| # | Milestone | Escopo resumido | Status |
|---|-----------|-----------------|--------|
| M1 | Análise completa | Mapear arquitetura, banco, auth, billing existente, frontends; `architecture.md` | ✅ 2026-07-03 |
| M2 | Infraestrutura do painel | Shell, sidebar completa, tema, guards, componentes base, ⌘K | ✅ 2026-07-03 |
| M3 | Dashboard Executivo | `/platform/metrics`: MRR, ARR, churn, LTV, ticket médio, séries; UI com gráficos | ✅ 2026-07-03 |
| M4 | Gestão de Barbearias | Listagem rica (filtros/busca/paginação/health), suspensão, reativação, soft delete | ✅ 2026-07-03 |
| M5 | Detalhe da Barbearia | Visão 360°: usuários, profissionais, financeiro, assinatura, timeline, logs, notas | ✅ 2026-07-03 |
| M6 | Onboarding | Checklist por org (derivado + manual), funil agregado, fila de parados | ✅ 2026-07-03 |
| M7 | Billing (arquitetura) | Domínio completo + `BillingProvider` + `StripeBillingProvider` + webhooks idempotentes | ✅ 2026-07-03 |
| M8 | Assinaturas | Gestão de assinaturas/dunning no painel; contrato do tenant pronto (tela = SA-D09) | ✅ 2026-07-03 |
| M9 | Central de Operações | Alertas acionáveis por regra + `platform_audit_log` + telas Operações/Logs | ✅ 2026-07-03 |
| M10 | Impersonation | Token de tenant 5–60 min com motivo obrigatório, claim `imp_by`, auditoria | ✅ 2026-07-03 |
| M11 | Configurações | Planos (CRUD + sync gateway), cupons, regras & ambiente | ✅ 2026-07-03 |
| MF | Hardening | Suíte 448 pass · builds verdes · código morto removido · docs finais | ✅ 2026-07-03 |

## Princípios (herdados do monorepo — CLAUDE.md)

- Evoluir sem reescrever; nunca quebrar retrocompatibilidade.
- RLS é a única barreira multi-tenant; endpoints de plataforma nunca setam o GUC na própria sessão (molde D-55).
- Migrations aditivas, numeradas, com CHECKs espelhados no ORM.
- Toda decisão relevante vira entrada em `DECISIONS.md` (raiz) + `docs/superadmin/decisions.md`.
- Suíte de testes verde antes de considerar qualquer milestone concluída.

## Decisões de billing já tomadas (ver decisions.md)

- Assinaturas via **Stripe Billing** (Subscription + Checkout Session `mode: subscription`), nunca renovação manual com PaymentIntents.
- **Customer Portal** para autosserviço do tenant.
- Catálogo local (`plans`) é a fonte de verdade de features/limites; Stripe guarda só a cobrança (Products/Prices espelhados).
- Dunning/retry: usar Smart Retries da Stripe; nosso lado registra tentativas/eventos via webhook (não reimplementar régua quando o gateway já tem).
- Toda regra de negócio fala com `BillingProvider` (interface); `StripeBillingProvider` é o único lugar que importa SDK da Stripe. `MockBillingProvider` para testes/dev sem chave.
