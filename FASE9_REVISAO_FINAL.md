# FASE9_REVISAO_FINAL.md — Revisão Final da Iniciativa de Segurança/Governança

> Checkpoint obrigatório da Fase 9 do `promptseguranca.md`. Verificação feita **no código atual** (não no que os
> documentos de planejamento diziam que seria feito) em 2026-07-13, cruzando os 29 achados de
> `AUDITORIA_SEGURANCA.md` (Fase 0, 2026-06-26) contra o estado real do repositório após D-67 a D-74.

## Sumário executivo

De 29 achados da auditoria original: **19 resolvidos, 5 parcialmente resolvidos, 2 adiados conscientemente, 3 em
aberto**.

O núcleo estrutural da iniciativa (RBAC por permissões, guard central, SSE com ticket de uso único, sessão/
refresh com revogação, hash-chain de auditoria, headers de segurança, anti-enumeração, rate limit de login) está
**resolvido e em produção** (D-67/D-68/D-69/D-70/D-71). O item Crítico (**V1**) também foi resolvido em produção
nesta sessão (2026-07-14). O que resta é majoritariamente:
- Itens de escala/latente (V3, V8, V21 parciais; V20 adiado — impacto baixo hoje, cresce se o bot virar
  multi-tenant de verdade, e V20 depende de mudança no n8n da VM, fora do backend).
- Isolamento estrutural residual de `coupons` (V18b — tentativa revertida por quebrar produção, precisa de
  redesenho `SECURITY DEFINER`).
- Itens de baixa severidade que dependem de decisão do dono por mexerem em superfície compartilhada (V22 CORS,
  V29 histórico git) e um de esforço médio-alto sem uso real em prod ainda (V27 Fernet).

**Nenhum item Crítico ou Alto ficou sem dono/plano** — todos estão listados abaixo com a ação recomendada. Os
poucos que restam exigem uma decisão do dono antes de eu tocar no código (ver seção "Itens que precisam da sua
decisão").

## 1. Checklist item a item (V1–V29)

| # | Achado | Severidade | Status | Evidência |
|---|---|---|---|---|
| V1 | Webhook `/bot/wa-webhook` sem auth quando secret vazio | **Crítica** | ✅ **Resolvido em prod (2026-07-14)** | Secret gerado + configurado nos dois lados (VM `.env` + header `X-Webhook-Secret` na Evolution); testado ao vivo: sem/errado → 401, correto → 200 |
| V2 | Sem rate limiting/lockout | Alta | ✅ Resolvido | `app/core/rate_limit.py` + `app/api/auth.py:63-94,167` |
| V3 | `X-Bot-Token` global = única barreira | Alta | 🟡 Parcial | `app/deps.py::get_bot_db` resolve por instância, mas ainda tem fallback + endpoints do bot aceitam `phone`/`client_id` sem provar posse |
| V4 | SSE sem RBAC/token na query | Alta | ✅ Resolvido | `app/api/conversations.py:463-532` — ticket de uso único + guard de permissão |
| V5 | Dashboard financeiro para recepção | Alta | ✅ Resolvido | `app/api/dashboard.py:327` — zera campos sem `reports.dashboard.financial.view` |
| V6 | Status/QR do WhatsApp sem guard | Alta | ✅ Resolvido | `app/api/integracoes.py:235,269,297` |
| V7 | `bot-pause` sem guard | Média | ✅ Resolvido | `app/api/clientes.py:359-364` |
| V8 | `complete` não verifica posse | Média | 🟡 Parcial | Resolvido no painel (`app/api/barbeiro.py:88-98`); **aberto** no canal bot (`app/api/bot.py:1060-1079`) |
| V9 | JWT sem revogação/refresh | Média | ✅ Resolvido | D-68 — `sessions` + refresh rotativo + denylist |
| V10 | JWT na query string do SSE | Média | ✅ Resolvido | junto do V4 |
| V11 | Senha fraca / sem reset | Média | ✅ Resolvido | `app/api/auth.py:372-386` + `app/api/security.py:138-176` |
| V12 | Sem headers de segurança / `/docs` público | Média | ✅ Resolvido | `app/core/security_headers.py` + `docs_enabled=False` |
| V13 | Enumeração por timing no login | Média | ✅ Resolvido | `app/api/auth.py:196-202` |
| V14 | PII (telefone) logada em INFO | Média | ✅ **Resolvido** | `app/core/phone.py::mask_phone` aplicado em `wa_webhook.py`, `chatwoot.py`, `bot.py`, `whatsapp.py` (todos os `_logger.*(...phone...)`) |
| V15 | Dados financeiros/nomes à OpenAI | Média | ✅ **Resolvido** | `kernel_ia_finance.py::redact_for_llm` — nome de cliente sai do prompt, `guard_insight` só valida número (não quebra) |
| V16 | Tabelas de plataforma sem RLS/FORCE | Média-Alta | ✅ **Resolvido** | Design intencional (SECURITY DEFINER) confirmado; `FORCE RLS` aplicado (D-68); `scripts/setup_local.sh` agora revoga explicitamente `platform_*` do `barber_app` após o `GRANT ON ALL TABLES` |
| V17 | Tabelas-filhas sem RLS (`appointment_items`) | Média | ✅ **Resolvido** | Migration `0043`: `organization_id` denormalizado (backfill de `appointments`) + RLS + `FORCE`, todos os 4 pontos de criação atualizados |
| V18 | `webhook_events`/`coupons` sem RLS | Média | 🟡 **Parcial** | `webhook_events`: RLS "global OU tenant" (migration `0043`, achado colateral: `NULLIF` necessário — ver nota abaixo). `coupons`: **tentativa revertida** — é catálogo global de verdade, sem `organization_id`; revogar escrita quebrou o resgate real de cupom (mesma conexão `barber_app` de qualquer rota). Corrigir de verdade exige mover pra `SECURITY DEFINER` (fora de escopo desta sessão) |
| V19 | Bot token não é constant-time | Média | ✅ Resolvido | `app/api/bot.py:132-139` (`secrets_match`) |
| V20 | Debounce global entre tenants | Média | 🟢 **Adiado conscientemente** | Exige o n8n (VM) enviar `X-Instance` aos nós HTTP Debounce/Flush — hoje não envia (`grep` em `workflows.json` = 0). Corrigir só no backend sem isso não muda nada; fica pra junto do bot multi-tenant (mesmo gatilho do V21) |
| V21 | Fallback single-tenant do bot | Média (alto se bot virar multi-tenant) | 🟡 Parcial | Fail-closed sem `bot_organization_id`; ainda cai nele silenciosamente quando configurado (caso de prod hoje) |
| V22 | CORS `allow_credentials=True` + `*` | Baixa | 🔴 ABERTO | `app/main.py:47-49` — decisão do dono pendente (mexe em middleware que toda requisição passa) |
| V23 | `/auth/tenant` enumera orgs | Baixa | ✅ Resolvido | rate limit `20/minute` |
| V24 | Billing sem guard de manager | Baixa | 🟢 **Aceito conscientemente** | `DECISIONS.md:1503` — "adiado de propósito" |
| V25 | Confusão de tipo no `state` OAuth | Baixa | ✅ **Resolvido** | `app/api/integracoes.py::_build_state/_verify_state` — `typ=oauth_state` dedicado |
| V26 | Advisory lock com f-string | Baixa (não injetável hoje) | ✅ **Resolvido** | `agenda.py`, `bot.py`, `membership.py` — bind parameter `:unit_id` |
| V27 | Fernet sem rotação | Baixa | 🔴 ABERTO | `app/core/crypto.py:26-42` — Google Calendar ainda não está em uso real em prod, baixa urgência |
| V28 | `except Exception`/200 mascarando erro | Baixa | 🟡 **Parcial** | `platform_billing.py::create_coupon` — só `IntegrityError` vira 409 agora (achado real desta sessão: um `GRANT` revogado por engano apareceu como "já existe" até o log do Postgres revelar "permission denied"). `wa_webhook.py`/`chatwoot.py` mantidos como estão — já logam corretamente, o ack-200 é design deliberado anti-retry-storm, não mascaramento silencioso |
| V29 | Segredo histórico no git | Baixa (Alto impacto teórico) | 🔴 ABERTO (infra) | Chave já revogada; histórico não limpo — decisão do dono pendente (reescreve histórico público) |

## 2. Itens que precisam da sua decisão (não vou tocar sem confirmar)

**V1 resolvido** — secret confirmado e configurado nos dois lados em 2026-07-14, testado ao vivo. Restam 3 itens
que dependem de uma decisão sua:

- **V29 (git history):** limpar segredo do histórico exige `git filter-repo` + force-push coordenado — reescreve
  o histórico público do repo. Ação destrutiva e irreversível sobre um repositório compartilhado; só faço com
  autorização explícita e depois de confirmar que a credencial exposta já foi revogada (já foi, segundo
  `DECISIONS.md`) e que não há mais ninguém com um clone antigo que dependa do histórico atual.
- **V22 (CORS):** desligar `allow_credentials`/restringir `methods`/`headers` é seguro em teoria (autenticação é
  Bearer, não cookie) mas mexe num middleware que toda requisição do frontend passa — vale eu fazer e você testar
  no ar antes de considerar fechado, não só confiar na suíte de testes.
- **V18b (`coupons`):** a tentativa de RLS/REVOKE nesta sessão quebrou o resgate real de cupom em produção e foi
  revertida (ver nota na migration `0043`). Corrigir de verdade exige mover a escrita de cupom para uma função
  `SECURITY DEFINER` (molde D-55) — é uma mudança de arquitetura, não um ajuste pontual; prefiro planejar
  separadamente antes de tocar.

## 3. Itens corrigidos nesta sessão (2026-07-14)

**V1** (secret do webhook, em prod), **V14** (mascarar telefone em log), **V15** (redigir nome antes do OpenAI),
**V16** (excluir `platform_*` do `GRANT ON ALL TABLES`), **V17** (RLS em `appointment_items`, migration `0043`),
**V18a** (RLS "global ou tenant" em `webhook_events`, mesma migration — achado colateral: precisou de `NULLIF`
por causa de conexões pooled reaproveitadas), **V25** (`typ` dedicado no state OAuth), **V26** (bind parameter
nos 3 advisory locks), **V28** (`create_coupon` só trata `IntegrityError` como 409, não qualquer exceção).

**Ainda abertos, com motivo:** V18b (coupons, precisa de redesenho — ver seção 2), V20 (depende do n8n na VM
enviar `X-Instance`, fora do backend), V22/V27/V29 (decisão do dono ou esforço não urgente, ver seção 2).

## 4. Matriz papel × permissão (fonte: `app/core/permissions.py`, 59 permissões × 9 papéis)

| Permissão | owner | partner | manager | reception | barber | intern | finance | marketing | support |
|---|---|---|---|---|---|---|---|---|---|
| schedule.own.view | ✅ | ✅ | ✅ |  | ✅ | ✅ |  |  |  |
| schedule.own.manage | ✅ | ✅ | ✅ |  | ✅ |  |  |  |  |
| schedule.all.view | ✅ | ✅ | ✅ | ✅ |  |  |  |  |  |
| schedule.all.manage | ✅ | ✅ | ✅ | ✅ |  |  |  |  |  |
| schedule.reschedule.request | ✅ | ✅ | ✅ |  | ✅ | ✅ |  |  |  |
| schedule.reschedule.approve | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| clients.view | ✅ | ✅ | ✅ | ✅ |  |  | ✅ | ✅ | ✅ |
| clients.manage | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| clients.delete | ✅ | ✅ | ✅ | ✅ |  |  |  |  |  |
| clients.personal_data.view | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| clients.export | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ |  |
| clients.bot_pause | ✅ | ✅ | ✅ | ✅ |  |  |  |  | ✅ |
| crm.leads.view | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| crm.leads.manage | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| conversations.view | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| conversations.send | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| conversations.stream | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| finance.revenue.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.margin.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.cost.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.payroll.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.dre.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.cash.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.payments.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.expenses.manage | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| finance.export | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| reports.dashboard.view | ✅ | ✅ | ✅ | ✅ |  |  | ✅ | ✅ | ✅ |
| reports.dashboard.financial.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| reports.operational.view | ✅ | ✅ | ✅ | ✅ |  |  | ✅ | ✅ |  |
| reports.gestor.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| team.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| team.manage | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| team.cost.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| services.view | ✅ | ✅ | ✅ | ✅ |  |  |  |  |  |
| services.manage | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| services.cost.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| loyalty.view | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| loyalty.manage | ✅ | ✅ | ✅ |  |  |  |  | ✅ |  |
| memberships.view | ✅ | ✅ | ✅ | ✅ |  |  |  | ✅ | ✅ |
| memberships.sell | ✅ | ✅ | ✅ | ✅ |  |  |  |  |  |
| memberships.manage | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| billing.view | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| billing.manage | ✅ |  |  |  |  |  |  |  |  |
| integrations.view | ✅ | ✅ | ✅ | ✅ |  |  |  |  |  |
| integrations.whatsapp.manage | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| integrations.calendar.manage | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| settings.company.manage | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| data.import | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |
| security.roles.manage | ✅ |  |  |  |  |  |  |  |  |
| security.users.manage | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| security.sessions.view | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| security.sessions.revoke | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| security.audit.view | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| security.audit.export | ✅ | ✅ | ✅ |  |  |  |  |  |  |
| security.site_visibility.manage | ✅ | ✅ | ✅ |  |  |  |  | ✅ |  |
| analytics.view | ✅ | ✅ | ✅ |  |  |  |  | ✅ |  |
| privacy.lgpd.manage | ✅ | ✅ |  |  |  |  |  |  |  |
| ai.assistant.use | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ai.finance.query | ✅ | ✅ | ✅ |  |  |  | ✅ |  |  |

Nota: `privacy.lgpd.manage` é **owner + partner** (não só owner — o `partner` só perde `billing.manage` e
`security.roles.manage`, ver `app/core/permissions.py::ROLE_DEFAULTS`). Em produção hoje só existem os papéis
`owner`/`barber` (0 reception/manager/partner) — o resto da matriz é fundação para quando a base de tenants
crescer.

## 5. Runbook — criar um novo papel ou permissão

1. **Nova permissão:** adicione um `Permission(...)` em `CATALOG` (`app/core/permissions.py`) — código
   `recurso.subrecurso.ação`, categoria, e `sensitive_field=True` se for campo que deve ser redigido no DTO sem
   a permissão.
2. **Atribuir a papéis:** adicione o código aos blocos (`_OPERATIONS`, `_FINANCE`, etc.) ou diretamente em
   `ROLE_DEFAULTS[slug]`.
3. **Sincronizar com o banco:** rode `scripts/sync_authz_catalog.py` (staging e prod) — faz upsert de
   `permissions`/`roles`/`role_permissions` a partir do catálogo em código (idempotente).
4. **Proteger a rota:** `Depends(require("seu.codigo"))` (rota nova) ou
   `await require_permission(db, current_user, "seu.codigo")` (imperativo, dentro do handler).
5. **Teste de cobertura:** `tests/test_authz_coverage.py` falha se uma rota nova não tiver ponto de autenticação
   conhecido — se for uma rota `/internal/*` com `X-Bot-Token` no handler (não por dependência), adicione o path
   a `PUBLIC_PATHS` no próprio teste (mesmo molde de `/internal/audit/purge`, `/internal/billing/run-lifecycle`).
6. **Papel personalizado (por org):** já é possível via `roles`/`role_permissions` com `organization_id`
   preenchido — mas a UI de "Papéis & Permissões" do `ARQUITETURA_ALVO.md §1.12` (criar papel customizado pela
   tela) **não tem backend ainda** — é o principal débito herdado da Fase 2 (F2.5 fechou a migração dos guards
   legados, mas não a UI de administração de papéis em si).

## 6. ADRs — decisões técnicas mais importantes (D-67 a D-74)

Cada decisão tem o detalhe completo em `DECISIONS.md` — aqui só o resumo em formato ADR (contexto → decisão →
consequência), para não duplicar.

| ADR | Decisão | Consequência principal |
|---|---|---|
| D-67 | RBAC por permissões nomeadas (catálogo em código, guard central) substitui guards por papel hardcoded | Fecha V4/V5/V6/V7/V8/V19/V24 de uma vez; retrocompatível (4 papéis mapeiam 1:1) |
| D-68 | Sessão/refresh rotativo com detecção de reuso + `FORCE ROW LEVEL SECURITY` dinâmico | Fecha V9/V10 parcial/V12/V13; hardening latente contra dono/superuser perder RLS |
| D-70 | `audit_logs` com hash-chain + guard central auditando toda negação automaticamente | Cobre as ~90 rotas do D-67 sem tocar em nenhuma; achado colateral: deadlock de teste sob concorrência real (fire-and-forget + DELETE síncrono) |
| D-71 | Painel de segurança (cards + série + alerta de anomalia) construído 100% sobre `audit_logs`, sem migration nova | Reaproveita `security.audit.view` em vez de nova permissão |
| D-73 | `client_visibility_settings` — configuração do site público **antes** do site existir | Escopo deliberadamente recortado (sem endpoint público de leitura ainda) |
| D-74 | `consent_records` (histórico) evolui `client_consents` (estado) sem substituir; direitos do titular (export/anonimizar) gestor-assistidos | Não há portal do cliente final ainda (`promptsitepublico.md`); `privacy.lgpd.manage` é owner+partner por decisão deliberada |
| D-75 | Revisão final da Fase 9 (`FASE9_REVISAO_FINAL.md`) — checklist V1-V29 verificado contra o código real | Base para o D-76 (fechamento em lote dos achados de baixo risco) |
| D-76 | Fechamento de V1/V14/V15/V16/V17/V18a/V25/V26/V28 num único lote (migration `0043` + fixes de código) | V18b (`coupons`) tentado e revertido — precisa de redesenho `SECURITY DEFINER`, fora de escopo; achado colateral do V18a: `NULLIF` necessário em RLS acessada por sessão sem tenant, por causa de GUC residual em conexão pooled |

## 7. Plano de rollout

**✅ Tudo em produção (2026-07-15):** D-67, D-68, D-69 (fora desta iniciativa, mas no mesmo trem de deploy), D-70,
D-71, D-72, D-73, D-74, D-76 — deploy único combinando D-73 (migration `0041`) + D-74 (migration `0042`) + D-76
(migration `0043` + fixes de código V14/V15/V16/V17/V18a/V25/V26/V28), molde D-59/D-63/D-65/D-67/D-68: backup
(`~/predeploy_d76_20260715_024101.sql`) → `git pull` (sem `submodule update` — frontend não mudou neste lote) →
migrations `0041`→`0042`→`0043` em sequência → rebuild backend → smoke test (`/health` 200, rotas novas 401 sem
token, `appointment_items` com backfill 100%, RLS+FORCE ativos, `coupons` com GRANTs intocados). V1 (Crítica)
também já estava em produção desde antes, via config de infra (secret configurado nos dois lados).

Com isso, a iniciativa `promptseguranca.md` está **formalmente fechada**. O que resta é débito consciente,
listado na seção 2 (V18b coupons, V22 CORS, V29 histórico git) e V20/V27 (baixa urgência, sem dependência
crítica hoje).

**Sem feature flag dedicado:** toda a iniciativa foi construída retrocompatível por natureza (permissões novas
não quebram nada que já funcionava; tabelas novas são aditivas) — não há necessidade de liberação gradual por
tenant, já que produção hoje é essencialmente 1 tenant real (`taylor`) mais tenants de teste/onboarding.

**Monitoramento pós-deploy sugerido:** taxa de `403` em `/admin/security/*` (confirma que o RBAC não regrediu
acesso de ninguém que devia ter), volume de linhas em `audit_logs` por dia (detecta se o fire-and-forget está
realmente escrevendo em prod), e o alerta de anomalia do painel de segurança (`/admin/seguranca`) nas primeiras
semanas — é a primeira vez que ele roda contra dado real, os limiares (`≥5, 3× a média`) são heurística inicial.

**Cron pendente (não é deploy, é agendamento):** `POST /internal/audit/purge` no n8n — sem ele, a retenção de
`audit_retention_months` (D-70) não tem efeito prático.
