# Progresso — Painel SuperAdmin + Billing

> Log append-only. Entradas mais recentes no topo.

## 2026-07-03

- **✅ B-02 fase TESTE validada ponta a ponta no sandbox Stripe real** (CLI pareado
  "Área restrita de BarbeariaPro"): sync criou Product/Price reais; checkout
  hospedado pago com 4242 (R$49,90); túnel `stripe listen` entregou 5 webhooks —
  todos `processed`; banco convergiu (fatura `paid`, `billing_payment succeeded`,
  assinatura `active` com `sub_…` da Stripe); pause/resume/cancel/reactivate 200
  com auditoria; estado local == Stripe mesmo com webhooks fora de ordem.
  **Dois bugs reais encontrados e corrigidos** (commit `b020c36`, deployado em
  prod): (1) SDK 15.x sem interface de dict nos StripeObject → `_to_dict` via
  `json.loads(str(obj))` em todo retorno do SDK; (2) webhooks out-of-order
  regravavam snapshot antigo → `_apply_subscription_state` rebusca o estado
  atual no gateway (fallback ao payload). Ambiente de teste 100% limpo (org/
  plano/admin purgados, assinatura cancelada na Stripe, credenciais efêmeras
  apagadas). Produção segue `BILLING_PROVIDER=mock` até HTTPS/domínio (B-01).
- **✅ COMMIT + DEPLOY EM PRODUÇÃO.** Commits: painel `2fec4b7`
  (barbearia-superadmin, +submódulo bumpado) e backend `b849b10` (barbeariapro,
  51 arquivos, +7.465 linhas) — pushed. VM: backup `~/predeploy_d61_20260703_165238.sql`
  (597K) → migrations **0028→0034 aplicadas em prod** (head `0034`) → backend
  rebuildado (dep `stripe`) e **healthy**. Smoke: `/health` ok; 5 rotas novas
  respondem 401 (existem + guard); tenant sem regressão (`/auth/tenant` 200,
  `/agenda` 401); log do container limpo. Billing operando em `BILLING_PROVIDER=mock`
  (default fail-safe) até as chaves Stripe (B-02); painel roda em localhost:3100
  contra prod até o domínio (B-01); cron do lifecycle agora acionável (B-03).
- **Auditoria arquitetural pré-commit (9 verificações, todas ✅).** SDK/segredos
  Stripe ausentes do frontend (único import: `stripe_provider.py`, nem testes);
  zero imports cruzados frontend→backend; painel fala SÓ com `/platform/*`
  (14 chamadas, zero rotas de tenant); guards de plataforma restritos a
  `platform.py`/`platform_billing.py`; rotas de plataforma sem `get_tenant_db`
  e sem GUC na sessão do request; rotas de tenant sem funções SD cross-tenant;
  lógica de billing 100% no backend. Nada movido. Selo: suíte 448 pass + build/
  lint verdes re-executados. Divisão barbeariapro × barbearia-superadmin
  confirmada correta (backend único D-55 + frontend de plataforma).
- **MISSÃO CONCLUÍDA (M1–MF).** Suíte final: **448 pass / 2 falhas ambientais
  pré-existentes / 0 regressões** (baseline era 408; +40 testes novos). Builds e
  lints do superadmin verdes. Migrations staging: head **`0034`** (prod segue
  `0027` — deploy = rodar alembic + env novos, ver blockers.md). Nada commitado
  (aguardando revisão do Augusto).
- **MF — Hardening.** Código morto removido (`coming-soon.tsx`); teardowns de
  teste ajustados à FK RESTRICT do audit; suíte completa re-executada 2×;
  segurança revisada por construção (RLS/SD em tudo, motivo+auditoria nas ações
  sensíveis, assinatura de webhook, segredos só via env, tokens curtos).
- **M11 concluído — Configurações.** Tela com 3 abas: catálogo de planos (CRUD +
  Sync gateway + situação de espelhamento), cupons (criar/desativar/uso) e
  regras & ambiente (regras da Central + envs de billing documentados).
- **M10 concluído — Impersonação.** `create_impersonation_token` (claim `imp_by`,
  5–60 min) + `POST /platform/orgs/{id}/impersonate` (motivo ≥5 chars obrigatório,
  owner ativo, 409 p/ suspensa, auditoria ANTES de emitir) + 3 testes (token
  funciona como tenant, rejeitado na plataforma, expiração conferida no JWT) +
  dialog no detalhe com cópia do token.
- **M9 concluído — Central de Operações + auditoria.** Migration `0034`
  (`platform_audit_log` sem RLS/GRANT + funções SD add/list, append-only de fato) ·
  `GET /platform/alerts` (regras: atraso de cobrança e webhooks falhos = crítico;
  trial ≤7d, onboarding parado >7d, pagante inativa ≥30d = atenção) ·
  `GET /platform/audit-log` (filtros categoria/org) · auditoria ligada em
  suspend/reactivate e em TODAS as ações de billing · telas: Operações (triagem
  com refetch 60s) e Logs (auditoria + webhooks com reprocesso).
- **M8 concluído.** Telas: Assinaturas (KPIs, views por status, tabela dunning,
  dialog "Gerenciar" com 8 ações) e Financeiro (receita por plano + série).
  Tela do tenant = handoff documentado (SA-D09, branches em voo).
- **M8 backend concluído (telas em andamento).** Migration `0033`
  (`app_platform_billing_subscriptions` — assinatura+plano+dunning por org) ·
  router `/platform/billing/*`: planos (list/create/patch/sync com invalidação de
  `provider_price_id` quando o valor muda — Prices são imutáveis), assinaturas
  cross-org com dunning, ações administrativas (cancel/reactivate/pause/resume/
  change-plan/grant-days/apply-coupon/credits), cupons (create/validate/deactivate),
  webhook-events (list + **reprocess** — payload bruto agora persistido; provider
  ganhou `parse_payload`) · 4 testes novos (9 de billing no total). Suíte alvo verde.
- **M7 concluído — Arquitetura de Billing.** 
  - **Domínio (migration `0032`)**: enum +`paused`/`incomplete`; `plans` +slug/description/
    is_active/sort_order/stripe_product_id; `subscriptions` +provider/ids externos/
    cancel_at_period_end/trial_end/paused_at/updated_at; catálogos `plan_prices`,
    `feature_flags`, `plan_features`, `plan_limits`, `coupons`; por-org com RLS
    `billing_customers`, `invoices`, `billing_payments`, `payment_attempts`, `discounts`,
    `billing_credits` (ledger), `usage_metrics`, `billing_events` (append-only);
    `webhook_events` idempotente por `(provider, event_id)`; backfills (slug, limites
    legados, preço mensal); funções SD de resolução customer/assinatura→org.
  - **Camada de provider (`app/services/billing/`)**: contrato `BillingProvider` (ABC) +
    tipos normalizados; `StripeBillingProvider` (único import de stripe; Checkout
    `mode=subscription`, Portal, Products/Prices, Smart Retries só registrados,
    assinatura de webhook verificada, API `2026-06-24.dahlia`); `MockBillingProvider`
    (síncrono, determinístico — default sem chave); factory por `BILLING_PROVIDER`.
  - **Serviço**: checkout/portal, claim de assinatura pós-checkout (price→plano),
    upsert de faturas/pagamentos/tentativas via eventos, ações administrativas
    (cancelar/reativar/pausar/retomar/trocar plano/dias grátis/cupom/crédito) com
    `billing_events` em tudo; `run_lifecycle` (manual: trial→past_due→canceled com
    carência `BILLING_GRACE_DAYS_PAST_DUE`) exposto em `/internal/billing/run-lifecycle`
    (X-Bot-Token, cron n8n).
  - **Entitlements (`app/core/entitlements.py`)**: níveis full/restricted/blocked +
    `check_limit` com rollout `BILLING_ENFORCEMENT=off|log|hard` (default `log`);
    primeiro ponto ligado: criação de profissional (`equipe.criar_barbeiro`).
  - **API tenant** (`/billing/*`): planos públicos, minha assinatura (+entitlements),
    checkout, portal, faturas — owner/manager. Webhook `/billing/webhooks/stripe`
    (400 em assinatura inválida; replay deduplicado).
  - **Testes**: 5 integração (checkout mock ativa assinatura + fatura/pagamento/eventos;
    ações administrativas; lifecycle escopado; entitlements hard 402 + API tenant;
    webhook Stripe com HMAC real válido/inválido + idempotência de replay).
  - Pendências deliberadas → M8/M11: endpoints de plataforma (gestão de planos/
    assinaturas/cupons no painel), espelhamento de cupom na Stripe, telas.
- **M6 concluído — Onboarding.** Migration `0031` (tabela `platform_onboarding_overrides`
  sem RLS/GRANT + funções SD de sinais/override) · derivação das 11 etapas em Python
  (`app/services/onboarding_progress.py`, limiares documentados: 10 clientes p/ importação,
  5 agend./30d p/ ativo; `primeiro_acesso` só manual — não há evento de login) ·
  endpoints `GET /platform/onboarding` (funil + fila por dias parada) e
  `GET/PUT/DELETE /platform/orgs/{id}/onboarding[/etapa]` · 10 testes novos (6 unit +
  4 integração). Frontend: página de funil com fila "mais paradas primeiro" + aba
  Onboarding no detalhe com checklist, marcação manual e "voltar ao automático".
- **M5 concluído — Detalhe 360°.** Migration `0030` (`platform_org_notes` sem RLS/GRANT +
  funções SD: perfil, usuários c/ papéis, profissionais, histórico de assinaturas, notas) ·
  endpoints `/platform/orgs/{id}` (+ /users /barbers /subscriptions /notes /timeline) ·
  6 testes de integração. Frontend: página 360° com header de ações
  (editar/suspender/reativar), KPIs, 7 abas; `OrgEditDialog` extraído p/ reuso.
- **M4 concluído — Gestão de Barbearias.** Migration `0029` (função SD `app_platform_org_overview`)
  + `GET /platform/orgs/overview` (busca/filtros/paginação/ordenação + counts por status;
  `/platform/orgs` intocado por retrocompat) + 5 testes. Frontend: tabela rica com views
  salvas (contadores), busca deferida, ordenação por cabeçalho, paginação, vencimento com
  alerta visual, dialog de edição nos primitivos novos.
- **M3 concluído — Dashboard Executivo.** Backend: migration `0028_platform_metrics`
  (função SECURITY DEFINER `app_platform_metrics_monthly`, molde 0021) + endpoint
  `GET /platform/metrics` (MRR, ARR, ARPU, churn mensal do último mês fechado, LTV,
  contagens por status, série mensal) + 4 testes de integração novos. Suíte completa:
  **412 pass / 2 falhas ambientais pré-existentes / 0 regressões**. Migration aplicada
  no staging (head `0028`; prod pendente de deploy). Frontend: dashboard v2 com
  `AsyncState`+Skeleton, KPIs em seções (Receita do SaaS / Base de clientes / Clientes
  finais), gráficos SVG próprios (`components/charts.tsx`: linha MRR + barras
  novas×cancelamentos com legenda) — build+lint verdes.
- **M2 concluído — Infraestrutura do painel.** Tokens completados (chart-1..5, motion,
  sidebar-primary/ring, shadow-overlay, radius-2xl) + fonte Inter; primitivos base-ui
  portados do tenant (dialog, input, select, tooltip, avatar, section/Panel,
  segmented-control) + `components/patterns` (AsyncState/Skeleton/Empty/Error/Spinner);
  Shell v2 com navegação agrupada (Visão geral/Gestão/Operação) e **paleta ⌘K**
  (busca de barbearias + navegação, teclado completo); rotas novas com "Em breve"
  (convenção do produto); `AGENTS.md` do painel criado; eslint corrigido (flat config
  do eslint-config-next 16 — FlatCompat antigo quebrava). Build + lint verdes.
- **M1 iniciado.** Time de análise em execução paralela (backend core, billing existente, frontends/design system).
- Verificado ambiente de desenvolvimento: repo backend limpo em `main` sincronizado; staging Postgres up (`barbeariapro-staging-postgres`); `.venv` + `.env.staging` presentes → suíte pytest executável localmente.
- Verificada conta Stripe conectada via MCP: **BarbeariaPro** (`acct_1Tp6TeGuBoJkIyFc`) → integração nasce contra conta real em test mode; chaves de ambiente pendentes (B-02).
- Melhores práticas Stripe absorvidas (billing + security): Checkout `mode: subscription`, Customer Portal, Prices (nunca o objeto `plan` deprecado), nunca `payment_method_types`, verificação de assinatura de webhook obrigatória, Smart Retries para dunning, restricted keys.
- Superadmin frontend (repo `barbearia-superadmin`) lido por completo: scaffold D-56 com login/dashboard/tenants/new, tokens dark+amber, React Query, next-auth v5 (token `typ=platform`).
- Convenções do monorepo internalizadas (CLAUDE.md): RLS como única barreira, molde SECURITY DEFINER da plataforma (D-55), migrations `0001`–`0027`, testes 408 pass baseline.
- Documentação da missão criada: `roadmap.md`, `blockers.md`, este arquivo.
