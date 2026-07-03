# API de Plataforma — contrato

> Superfície REST consumida pelo painel superadmin (`barbearia-superadmin`).
> Autenticação: `Authorization: Bearer <token typ=platform>` (emitido por `/platform/auth/login`).
> Endpoints de plataforma NUNCA setam `app.current_org_id` na sessão do request
> (leituras via SECURITY DEFINER; escritas escopadas em sessões helper — molde D-55).

## Existente (deployado, D-55)

| Rota | Método | Descrição |
|---|---|---|
| `/platform/auth/login` | POST | Login do superadmin → `{access_token}` |
| `/platform/orgs` | GET | Lista orgs (status derivado: suspended/sub_status/sem_assinatura) |
| `/platform/orgs` | POST | Onboarding atômico (org + subscription trial + unidade + owner + 15 serviços) |
| `/platform/orgs/{id}` | PATCH | Nome e/ou plano (valida FK antes) |
| `/platform/orgs/{id}/suspend` | POST | Seta `organizations.deleted_at` |
| `/platform/orgs/{id}/reactivate` | POST | Limpa `deleted_at` |
| `/platform/dashboard` | GET | Contagens + `saas_mrr` + `tenants_membership_mrr` + uso 30d por org |

## Implementado na missão (2026-07-03) — ✅ TUDO abaixo está implementado e testado

> A superfície planejada virou realidade com pequenos ajustes de rota:
> `/platform/orgs/overview` (M4) · detalhe 360° sem `/timeline` de billing
> separado (unificado) · billing de plataforma em `/platform/billing/*` ·
> impersonação com `minutes` 5–60 · reset de senha/soft-delete ficaram para o
> backlog (não eram bloqueantes; ver todo.md).

### M3 — Métricas executivas
- `GET /platform/metrics` — MRR, ARR, churn mensal, LTV, ticket médio, contagens; `?months=12` séries mensais (novas contas, MRR, cancelamentos, receita).

### M4/M5 — Barbearias
- `GET /platform/orgs` (evoluído) — `?q=&status=&plan_id=&page=&per_page=&order=` + campos ricos (último acesso, contagens, próximo vencimento, etapa onboarding, health).
- `GET /platform/orgs/{id}` — detalhe 360° (org, plano, assinatura, usuários, unidades, uso, indicadores).
- `GET /platform/orgs/{id}/timeline` — eventos unificados (billing + auditoria + notas).
- `POST /platform/orgs/{id}/notes` / `GET .../notes` — notas internas.
- `POST /platform/orgs/{id}/users/{uid}/reset-password` — reset com senha temporária.
- `DELETE /platform/orgs/{id}` — soft delete definitivo (distinto de suspend; exige confirmação).

### M6 — Onboarding
- `GET /platform/onboarding` — funil agregado + orgs paradas (`?stuck_days=7`).
- `GET/PUT /platform/orgs/{id}/onboarding` — checklist (etapas derivadas + overrides manuais).

### M7/M8 — Billing
- `POST /billing/webhooks/stripe` — webhook (sem auth; assinatura verificada no provider; idempotente por event id). 
- Tenant (`get_tenant_db`): `GET /billing/subscription` · `POST /billing/checkout` · `POST /billing/portal` · `GET /billing/invoices`.
- Plataforma: `GET/POST/PATCH /platform/billing/plans` · `POST /platform/billing/plans/{id}/sync` (espelha Product/Price) ·
  `GET /platform/billing/subscriptions` (lista com dunning: tentativas, dias em atraso) ·
  `POST /platform/billing/subscriptions/{id}/{cancel|reactivate|pause|resume|change-plan|grant-days|apply-coupon}` ·
  `GET/POST /platform/billing/coupons` · `POST /platform/billing/credits` (concessão) ·
  `GET /platform/billing/webhook-events` + `POST .../{id}/reprocess`.

### M9 — Central de Operações
- `GET /platform/alerts` — alertas derivados por regra (onboarding parado, trial vencendo, past_due, inatividade 30d, integração caída) com severidade.
- `GET /platform/audit-log` — auditoria da plataforma (filtros por categoria/ator/org).

### M10 — Impersonation
- `POST /platform/orgs/{id}/impersonate` — body `{reason, ticket?}` (motivo OBRIGATÓRIO) → token de tenant curto (30 min) com claims `imp_by`/`imp_reason` + registro em `platform_audit_log`.

## Convenções de resposta
- Erros: `{detail: string}` (FastAPI padrão) — o frontend usa `getErrorDetail`.
- Datas: ISO 8601 UTC. Dinheiro: `number` (BRL) — manter compat com `brl()` do frontend.
- Paginação: `{items, total, page, per_page}`.
