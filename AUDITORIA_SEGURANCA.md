# AUDITORIA_SEGURANCA.md — BarbeariaPro

> **Fase 0** do plano `promptseguranca.md` — Auditoria e Descoberta. Documento **somente leitura**:
> nenhum código foi alterado. Objetivo: mapear a stack, o modelo de papéis, os pontos de entrada, o
> isolamento multi-tenant e produzir a lista priorizada de vulnerabilidades que guiará as Fases 1–9.
>
> **Método:** varredura de todos os 27 routers de API, do núcleo de auth/segurança/cripto, das migrations
> de RLS/SECURITY DEFINER, dos serviços de bot/webhook/cron e do frontend (tenant + superadmin). Achados
> referenciados por `arquivo:linha`. Provas de conceito são **descritivas** (sem exploit funcional).
>
> **Data:** 2026-07-06 · **Escopo:** `app/`, `models/`, `alembic/`, `barbearia-frontend/`, `barbearia-superadmin/`, `scripts/`.

---

## Sumário executivo

O desenho central de isolamento multi-tenant é **sólido**: RLS por `app.current_org_id` setado com escopo de
transação (não vaza no pool), papel de banco `barber_app` é `NOBYPASSRLS` e não é dono das tabelas, tokens de
tenant e de plataforma são isolados bilateralmente, e os fluxos cross-tenant (MRR, onboarding, billing, crons)
usam sessões helper isoladas. **Não** há vazamento cross-tenant explorável hoje pela via RLS.

As fraquezas reais concentram-se em **três eixos**:

1. **Autorização por papel aplicada manualmente, endpoint a endpoint** (não há guard no nível de router). Isso
   já produziu lacunas concretas: endpoints que "abrem por omissão" quando alguém esquece a linha do guard
   (`/clientes/{id}/bot-pause`, status/QR do WhatsApp), e uma inconsistência que expõe **financeiro à recepção**
   (Dashboard) enquanto o módulo Financeiro a bloqueia.
2. **Superfícies não-JWT frágeis:** webhook do WhatsApp **sem autenticação** no estado atual de produção
   (`WA_WEBHOOK_SECRET` vazio) e um `X-Bot-Token` global que é a **única** barreira para enumerar PII de
   qualquer cliente e manipular agendamentos.
3. **Ausência de fundações de hardening:** sem rate limiting/lockout em lugar nenhum, sem revogação/refresh de
   JWT, sem cabeçalhos de segurança, sem central de gestão de usuários/permissões/sessões/auditoria, sem
   mascaramento de campo (dado financeiro/PII trafega cru para o browser).

**Contagem por severidade:** 1 Crítica · 5 Altas · 15 Médias · 8 Baixas (29 achados após deduplicação).

**Top 5 a atacar primeiro** (detalhe na §5 e matriz na §6):

| # | Achado | Severidade | Esforço |
|---|--------|-----------|---------|
| V1 | Webhook `/bot/wa-webhook` sem autenticação (`WA_WEBHOOK_SECRET` vazio em prod) | **Crítica** | Baixo |
| V2 | Sem rate limiting / lockout em login, bot, webhooks e imports | **Alta** | Médio |
| V5 | Dashboard expõe receita/comissão à **recepção** (inconsistente com Financeiro) | **Alta** | Baixo |
| V4 | SSE `/crm/stream` sem RBAC + token na URL — barbeiro recebe toda a Inbox | **Alta** | Baixo |
| V6 | Status/QR do WhatsApp sem guard de papel + instância Evolution global | **Alta** | Baixo |

---

## 1. Mapeamento da stack atual

| Camada | Tecnologia | Observações de segurança |
|---|---|---|
| **Frontend tenant** | Next.js 16 App Router · TypeScript · next-auth v5 **beta** · axios · React Query | Auth via next-auth Credentials; token do backend entregue ao JS do cliente (`session.user.token`). |
| **Frontend superadmin** | Next.js 16, repo separado | Guard mínimo (só presença de token); autorização 100% no backend. |
| **Backend** | Python 3.9 · FastAPI · SQLAlchemy 2 async (psycopg3) · Pydantic v2 | Monólito modular, 27 routers. RBAC chamado **dentro** de cada função (não por dependência de router). |
| **Auth** | JWT **HS256** (python-jose), Bearer no header `Authorization` · bcrypt (cost 12) · Fernet (tokens OAuth) | Sem refresh token, sem revogação, sem logout server-side. `SECRET_KEY` obrigatório (sem default inseguro). |
| **Banco** | PostgreSQL 16 · **Row Level Security** por `app.current_org_id` · papel `barber_app` `NOBYPASSRLS` | Barreira multi-tenant única. Sem `FORCE ROW LEVEL SECURITY`. ~27 tabelas RLS + tabelas-filhas sem RLS. |
| **Infra** | Docker Compose · nginx no host da VM GCP · TLS coringa (Cloudflare DNS-01) · n8n + Evolution API (bot) | Portas 8000/3000 ainda acessíveis diretamente (débito). Segredos em `.env` (fora do git). |
| **Integrações** | OpenAI (Kernel IA + n8n), Google Calendar (OAuth+Fernet), Stripe (billing), Chatwoot (planejado) | Webhook Stripe verifica assinatura; Chatwoot fail-closed; **WhatsApp webhook opcional (V1)**. |
| **Background** | Crons via n8n → `/internal/*` (X-Bot-Token); reminders/reactivation por org | Sem fila/worker dedicado; debounce/dedup **em memória** (não escala, colisão cross-tenant — V20). |

**Autenticação — não há:** rate limiting, lockout, MFA/2FA, refresh token, revogação de sessão, reset/troca de
senha, cabeçalhos de segurança na app (HSTS/CSP/etc.), `TrustedHostMiddleware`, tratamento de `X-Forwarded-*`.

---

## 2. Inventário do modelo atual de usuários e papéis

### 2.1 Papéis
- **Papéis fixos no código** (não há permissões granulares nem papéis personalizados):
  `owner > manager > reception > barber` (tenant) + `client` (frontend) + `platform` (superadmin, tabela e token
  próprios, sem `org`). Definidos em `app/core/rbac.py` e `barbearia-frontend/types/index.ts:1`.
- **Vínculo usuário↔papel↔unidade:** via `user_units` (tabela-filha, **sem RLS** — isolada por JOIN a `units`,
  `app/deps.py:152-167`). Role efetiva resolvida em `resolve_current_role` (`app/deps.py:170`).
- **Fail-safe de menor privilégio:** sem `user_units`, a role cai para `"barber"` (`rbac.py:30-37`).

### 2.2 Guards RBAC (todos em `app/core/rbac.py`)
| Guard | Papéis que passam | Uso |
|---|---|---|
| `require_full_access` (l.55) | owner, manager, **reception** | agenda, clientes, CRM, conversas, dashboard, fidelidade |
| `require_manager_access` (l.64) | owner, manager (**recepção excluída**) | financeiro, gestor, equipe, serviços, débitos, imports, empresa |
| `check_appointment_ownership` (l.73) | ABAC de posse (barbeiro só o próprio) | agenda (barbeiro), `barbeiro.py`, criar remarcação |
| `require_platform_admin` (`platform.py:72`) | platform (revalida no DB via SECURITY DEFINER) | `/platform/*` |
| `_require_manager_phone` (`bot.py:1100`) | role resolvida pelo **telefone** passado como query param | `/bot/gestor/*` |

### 2.3 Onde as checagens acontecem — e onde faltam
- **Backend é a fonte real de autorização** (RLS + guards por função). Correto em princípio.
- **Frontend:** toda a autorização client-side vive num **único** middleware `barbearia-frontend/proxy.ts`
  (route gating por prefixo), *coarse-grained* e trivialmente contornável por chamada direta à API. A sidebar
  (`AdminSidebar.tsx:41-78`) **não** filtra por papel — mostra "Financeiro/Gestor/Usuários" para todos. Não há
  checagem de papel dentro de páginas (exceto ocultar o sino de notificações). O rodapé de usuário é
  **hardcoded** "Administrador" (`AdminSidebar.tsx:210-217`).
- **Não existe** endpoint `/me/permissions` — o frontend usa apenas o `role` estático do login, congelado por
  8h (`lib/auth.ts:60`). Rebaixar/desativar um usuário **não** reflete na sessão ativa.
- **Não existe** central de gestão: `/admin/usuarios` é placeholder "Em breve" (`usuarios/page.tsx:9`); não há
  telas de Papéis/Permissões, Dispositivos/Sessões, nem Auditoria no frontend de tenant.
- **Sem mascaramento de campo:** o padrão é buscar o objeto inteiro e renderizar. Dados financeiros
  (`use-financeiro.ts`, `use-gestor.ts`) e PII (`types/index.ts:77-161`) chegam **crus** ao browser — qualquer
  restrição "quem vê o quê" precisa ser feita no backend.

---

## 3. Mapeamento dos pontos de entrada

### 3.1 Públicos (sem autenticação)
| Rota | Arquivo:linha | Risco |
|---|---|---|
| `GET /` | `main.py:66` | baixo |
| `GET /health`, `GET /health/db` | `health.py:17,22` | baixo — expõe reachability do DB (V-Baixa) |
| `GET /auth/tenant?subdomain=` | `auth.py:27` | enumera orgs (id+nome) — **V23** |
| `POST /auth/login` | `auth.py:56` | brute-force sem trava — **V2**; enumeração por timing — **V13** |
| `GET /docs`, `/redoc`, `/openapi.json` | (FastAPI default) | superfície da API pública — **V12** |
| `POST /bot/wa-webhook` | `wa_webhook.py:136` | **secret opcional → sem auth em prod — V1** |
| `POST /chatwoot/webhook` | `chatwoot.py:133` | token obrigatório (fail-closed) — OK |
| `POST /billing/webhooks/{provider}` | `billing.py:210` | assinatura verificada — OK |
| `GET /integracoes/google/calendar/callback` | `integracoes.py:116` | state JWT assinado — OK (ressalva V25) |

**Confirmado: não existe site público de agendamento do cliente final no backend hoje.** Todo o caminho
cliente→agenda passa por `/bot/*` (X-Bot-Token). A Fase 6 (visibilidade do site público) e a Fase 7 (analytics)
partirão do zero.

### 3.2 Canal bot (X-Bot-Token global; org por header `X-Instance`)
23 endpoints em `bot.py` + `/internal/*` (reminders, gestor, loyalty, memberships, billing). O token é **único e
global**, compartilhado com o n8n; a org é escolhida por header controlado pelo chamador. Endpoints que devolvem
PII por telefone arbitrário: `GET /bot/clients/profile` (`bot.py:523`), `GET /bot/appointments` (`bot.py:963`),
`PATCH /bot/appointments/{id}/cancel` (`bot.py:1010`). Escrita financeira sem posse:
`PATCH /bot/appointments/{id}/complete` (`bot.py:1058` — **V8**). Detalhe em **V3**.

### 3.3 Canal tenant (JWT + RLS) — 200+ endpoints
Inventário completo produzido na auditoria (por router: auth, kernel_ia, debts, reschedule, agenda, barbeiro,
clientes, servicos, financeiro, empresa, equipe, gestor, dashboard, crm, conversations, integracoes, imports,
loyalty, memberships, billing). RBAC **correto** na grande maioria; as exceções viram achados **V4, V5, V6, V7,
V24**. Todos escopam por RLS (isolamento cross-tenant preservado); IDOR **intra-tenant** é por design para
owner/manager/reception, com ABAC de posse só para barbeiro.

### 3.4 Canal plataforma (JWT `typ=platform`; cross-tenant deliberado)
`/platform/*` e `/platform/billing/*` — **todos** com `require_platform_admin` consistente, sem lacunas. Ponto de
maior poder: `POST /platform/orgs/{id}/impersonate` (`platform.py:917`) emite token de **tenant** como owner
(motivo obrigatório + auditado). Impersonação não pode ser encerrada antes do `exp` (ver **V9**).

### 3.5 Background / cron
`/internal/reminders/run`, `/internal/gestor/*`, `/internal/loyalty/*`, `/internal/memberships/*`,
`/internal/billing/run-lifecycle` — todos `X-Bot-Token` (constant-time). Reminders/reactivation rodam **por org**
(resolvida por instância) e **respeitam opt-out/cooldown/batch-limit** (verificado). Billing lifecycle itera
todas as orgs em **sessões isoladas** por org. Sem laço "todas as orgs em série" no disparo de WhatsApp hoje.

---

## 4. Mapeamento do isolamento multi-tenant

**Barreira única = RLS** com GUC `app.current_org_id`, setado por `SELECT set_config('app.current_org_id', :org,
true)` — o `true` é `is_local` (escopo de transação; **não vaza no pool**). Confirmado correto em
`app/db/session.py:33-38` e em todos os pontos de escrita do GUC (`deps.py:53,88`, `auth.py:44,62`,
`wa_webhook.py:197`, e helpers cross-tenant em `platform.py`, `onboarding.py`, `billing/service.py`,
`calendar_sync.py` — todos dentro do próprio `AsyncSessionLocal()`).

**Confirmado positivo:**
- `barber_app` é `NOBYPASSRLS` (`scripts/setup_local.sh:27`) e não é dono das tabelas → a RLS incide sobre o app.
- Policies RLS `USING` sem `WITH CHECK` explícito reusam a expressão para INSERT/UPDATE → escrita com `org` de
  outra org fica bloqueada; com GUC ausente, o `= NULL` **falha fechado** (`0001_initial.py:387-395`).
- Isolamento bilateral de tokens (tenant sem `typ` × plataforma sem `org`) — não explorável.
- Funções SECURITY DEFINER são mínimas, com `SET search_path` anti-hijack.

**Fraquezas estruturais/latentes** (viram **V16, V17, V18, V21**):
- **Tabelas-filhas sem RLS** (`appointment_items` [contém `price_charged`], `user_units`, `time_off`,
  `business_hours`, `barber_units`, `barber_services`, `client_consents`, `calendar_sync`) — isolamento depende
  de **disciplina de JOIN** na aplicação, não imposto pelo banco. Hoje todos os acessos escopam por um pai sob
  RLS (verificado), mas qualquer query futura por id direto vaza cross-org silenciosamente.
- **Tabelas de plataforma sem RLS** (`platform_admins` com `password_hash`, `platform_audit_log`) protegidas só
  pela **ausência de GRANT** a `barber_app` — mas `scripts/seed.py:122` e `scripts/setup_local.sh:39` rodam
  `GRANT ... ON ALL TABLES ... TO barber_app` + `ALTER DEFAULT PRIVILEGES`, que **anulam** essa proteção se
  reexecutados após a criação das tabelas. Sem `REVOKE` explícito. **Estado em prod não determinado.**
- **Billing:** `webhook_events` e `coupons` sem RLS mas **com GRANT** a `barber_app` — uma futura rota de tenant
  que os lesse veria dados de todas as orgs.
- **Sem `FORCE ROW LEVEL SECURITY`** — se o app algum dia conectar como dono/superuser, a RLS some em silêncio.
- **Bot/webhook:** org resolvida por header client-controlado com **fallback single-tenant** (`bot_organization_id`);
  Chatwoot **hardcoda** a org. No multi-tenant real do bot, uma instância não mapeada gravaria sob a org de
  fallback — um tenant afetaria outro.

---

## 5. Lista de vulnerabilidades (priorizada)

> Categorias: **BAC** = Broken Access Control · **IDOR** · **AuthN** = falha de autenticação/sessão · **Priv** =
> escalada/exposição de privilégio · **Tenant** = vazamento cross-tenant · **LGPD** · **Config** = configuração
> insegura · **Info** = enumeração/vazamento de informação.

### 🔴 CRÍTICA

#### V1 — Webhook `/bot/wa-webhook` sem autenticação quando `WA_WEBHOOK_SECRET` está vazio
- **Categoria:** BAC / Missing Authentication · **Local:** `app/api/wa_webhook.py:59` (`_get_webhook_db`), default `""` em `app/core/config.py:65`.
- **PoC descritiva:** a validação só ocorre `if settings.wa_webhook_secret and not secrets_match(...)`. No estado
  atual de produção (secret vazio, confirmado pelo comentário no próprio código e pelo backlog do CLAUDE.md §7),
  um `POST` **não autenticado** é aceito. O atacante escolhe o tenant-alvo pelo campo `instance` do payload
  (`wa_webhook.py:184-185`) e pode: (a) injetar mensagens arbitrárias no CRM/Inbox de qualquer tenant (grava
  `Message`/`Conversation`, dispara SSE); (b) forçar o forward ao n8n → aciona o AI Agent (custo OpenAI ilimitado);
  (c) gravar **opt-out** para telefones alheios (`wa_webhook.py:219-223`), silenciando lembretes/reativação de
  clientes legítimos.
- **Dado/ação exposta:** escrita não autenticada em dados de CRM de qualquer tenant + consumo de custo + poluição de consentimento.
- **✅ Confirmado em prod (2026-07-06):** `WA_WEBHOOK_SECRET` **ausente** no `.env` da VM → auth do webhook desligada; endpoint alcançável por `https://api.taylorethedy.com/bot/wa-webhook`.
- **Correção:** tornar o secret **obrigatório** (provisionar na Evolution/n8n + `.env` da VM); rejeitar quando ausente.

### 🟠 ALTA

#### V2 — Ausência total de rate limiting / lockout
- **Categoria:** AuthN · **Local:** `app/api/auth.py:56`, `app/api/platform.py:392`, bot/webhooks/imports; nenhum limiter no projeto (grep vazio).
- **PoC:** `POST /auth/login {organization_id, email, password}` pode ser tentado indefinidamente sem trava,
  captcha ou backoff. Combinado com senha `min_length=1` (**V11**) e `/auth/tenant` que enumera orgs (**V23**),
  o brute-force de credenciais é irrestrito. O `/bot/wa-webhook` aberto (**V1**) pode ser inundado para gerar custo.
- **Dado/ação exposta:** comprometimento de conta por força bruta; DoS/abuso de custo.
- **Correção:** rate limit por IP+identidade em rotas de auth/webhook/import; lockout progressivo; considerar captcha.

#### V4 — SSE `GET /crm/stream` autentica só por token na query string, sem RBAC nem revalidação de usuário
- **Categoria:** BAC + token em URL · **Local:** `app/api/conversations.py:460-471`.
- **PoC:** diferente de todos os outros endpoints de conversa (que exigem `get_current_user` + `require_full_access`),
  o stream apenas faz `decode_access_token(token)` e extrai `org`. Consequências: (a) **qualquer JWT válido da org,
  inclusive de um `barber`**, recebe o fluxo em tempo real de **todas as conversas de WhatsApp** (PII de todos os
  clientes) — enquanto na leitura paginada o barbeiro é barrado; (b) um token de usuário **desativado** continua
  aceito até expirar (não há checagem no DB); (c) o token trafega na **URL**, sujeito a logs de nginx/Referer.
- **Dado/ação exposta:** Inbox WhatsApp inteiro (PII) a papel/usuário não autorizado.
- **Correção:** exigir `get_current_user` + RBAC no handshake do SSE; mover o token para header/cookie ou ticket de curta duração.

#### V5 — Dashboard expõe receita/comissão à recepção (inconsistente com o módulo Financeiro)
- **Categoria:** Priv / BAC · **Local:** `app/api/dashboard.py:112` e `:424` (usam `require_full_access`, que inclui `reception`, `rbac.py:22`).
- **PoC:** `GET /dashboard` e `/dashboard/operacional` retornam **receita total, ticket médio, receita+comissão por
  barbeiro** (`dashboard.py:234-241`) e receita por serviço. Porém todo o resto do código financeiro
  (`financeiro.py`, `gestor.py`, `equipe.py`, `debts.py`) usa `require_manager_access`, que **exclui a recepção**.
  Resultado: a recepção não vê `/financeiro` mas vê os mesmos números no `/dashboard`. É exatamente o modelo de
  ameaça do projeto (proteger dado financeiro de funcionário sem permissão).
- **Dado/ação exposta:** faturamento/comissão a um papel explicitamente excluído em toda a demais superfície financeira.
- **Correção:** decidir a política e alinhar — exigir `require_manager_access` no dashboard financeiro **ou** omitir/mascarar os campos de dinheiro para recepção.

#### V6 — Status/QR do WhatsApp sem guard de papel + sobre instância Evolution global
- **Categoria:** BAC + Tenant · **Local:** `app/api/integracoes.py:225` (`calendar_status`), `:258` (`whatsapp_status`), `:284` (`whatsapp_qr`).
- **PoC:** os três exigem apenas `get_current_user`, **sem** o guard owner/manager que os endpoints irmãos de
  `authorize` aplicam inline (`:97-102`, `:211-216`). Assim, **qualquer papel autenticado (barbeiro/recepção)**
  pode ler o telefone conectado (`ownerJid`, PII) e — mais grave — **gerar um QR code de conexão**
  (`whatsapp_qr`), superfície de sequestro/reconexão da instância. Agravante: usam `settings.evolution_instance_name`
  **global**, respondendo sobre a **única instância compartilhada**, ignorando a org do chamador.
- **Dado/ação exposta:** número conectado + QR de reconexão; ação sobre instância de outro tenant.
- **Correção:** aplicar guard owner/manager; escopar por org; nunca servir QR a papéis operacionais.

#### V3 — `X-Bot-Token` global é a única barreira para enumerar PII e manipular agenda de qualquer cliente
- **Categoria:** BAC / IDOR · **Local:** `app/api/bot.py:523,963,1010,1058`; `app/deps.py:57`.
- **PoC:** todos os endpoints do bot ficam atrás de um **único** token estático (compartilhado com o n8n). Aceitam
  `phone`/`client_id`/`X-Instance` **arbitrários** e devolvem/alteram dados do cliente/org correspondentes:
  `GET /bot/clients/profile?phone=` devolve perfil de qualquer telefone; `GET /bot/appointments?phone=` e
  `PATCH .../cancel` listam/cancelam agendamentos de qualquer cliente cujo telefone se conheça (posse validada só
  pelo par `phone`+`id`, ambos fornecidos pelo chamador). Se o token vazar, há enumeração completa de PII +
  manipulação de agenda de todos os clientes de todas as orgs (via `X-Instance`).
- **Dado/ação exposta:** PII de clientes + escrita na agenda, sem segunda camada além do token.
- **Correção:** segregar segredo por tenant/instância; assinar payloads do n8n com o telefone real do remetente; reduzir superfície das tools de escrita.

### 🟡 MÉDIA

#### V7 — `PATCH /clientes/{id}/bot-pause` sem qualquer checagem de papel
- **Categoria:** BAC · **Local:** `app/api/clientes.py:323` (único endpoint do router sem `require_full_access`; compare `:133,208,249,285,305`).
- **PoC:** depende só de `get_current_user`+`get_tenant_db`. Qualquer usuário autenticado do tenant — **inclusive um `barber`** — pausa/reativa o bot de qualquer cliente (e altera `Conversation.bot_active`). Provável esquecimento do guard.
- **Correção:** adicionar `require_full_access`.

#### V8 — `PATCH /bot/appointments/{id}/complete` não verifica posse (diferente do `/cancel`)
- **Categoria:** BAC · **Local:** `app/api/bot.py:1058`.
- **PoC:** o `cancel` valida telefone×agendamento; o `complete` recebe **só o id** e conclui **qualquer** agendamento
  `agendado` da org, disparando `_recalculate_loyalty` (efeito financeiro/fidelidade). Mitigado pelo token confiável, mas sem gating do ator.
- **Correção:** exigir posse (telefone) ou gating de gestor, alinhando ao `/cancel`.

#### V9 — JWT sem revogação / refresh / logout server-side
- **Categoria:** AuthN · **Local:** `app/core/security.py:40-96`, expiração 60 min em `config.py:18`.
- **PoC:** não há `jti`/blacklist/`token_version`. Token roubado é válido por até 60 min sem como matá-lo;
  impersonação (`create_impersonation_token`) não pode ser encerrada antes do `exp`; suspender/desativar
  usuário/org **não** invalida tokens já emitidos (o próprio `login` comenta isso).
- **Correção:** access curto + refresh rotativo com detecção de reuso; lista de revogação (Redis) para logout/"sair de todos os dispositivos".

#### V10 — JWT trafega na query string do SSE
- **Categoria:** AuthN / Info · **Local:** `app/api/conversations.py:463,467`.
- **PoC:** o token aparece na URL do stream → vaza em logs de nginx/proxy, histórico e `Referer`. (Relacionado a **V4**.)
- **Correção:** header `Authorization` ou ticket de uso único.

#### V11 — Política de senha fraca e ausência de reset/troca de senha
- **Categoria:** AuthN · **Local:** `app/schemas/auth.py:13` (login `min_length=1`), `app/api/platform.py:115` (onboarding `min_length=6`, sem complexidade).
- **PoC:** senhas triviais são aceitas; sem rate limit (**V2**) isso viabiliza brute-force. Não há endpoint de "esqueci a senha" nem "alterar senha" (`hash_password` só é chamado no onboarding) — credencial comprometida não pode ser rotacionada pelo usuário.
- **Correção:** política mínima (tamanho/entropia), fluxo de troca e reset seguros; provisionamento de usuários com senha.

#### V12 — Sem cabeçalhos de segurança na aplicação; `/docs` e `/redoc` públicos
- **Categoria:** Config · **Local:** `app/main.py:24-31` (só CORS registrado).
- **PoC:** ausentes HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy;
  sem `TrustedHostMiddleware`. Como `/docs`/Swagger servem HTML, a falta de X-Frame-Options/CSP é relevante. (Confirmar se o nginx adiciona algum — **não determinado**.)
- **Correção:** middleware de headers de segurança; restringir/proteger `/docs` em produção.

#### V13 — Enumeração de usuário por timing no login
- **Categoria:** Info / AuthN · **Local:** `app/api/auth.py:72-88`, `app/api/platform.py:395`.
- **PoC:** `user is None or not user.is_active or not verify_password(...)` faz curto-circuito — se o e-mail não existe, o bcrypt (caro) não roda → resposta mais rápida = oráculo de existência de e-mail. A checagem de org suspensa retorna **403 distinto** ("Organização suspensa"), revelando estado da org.
- **Correção:** sempre executar um bcrypt "dummy" quando o usuário não existe; uniformizar respostas.

#### V14 — PII (telefone) logada em nível INFO
- **Categoria:** LGPD · **Local:** `app/api/bot.py:281-285,319`, `app/api/wa_webhook.py:200`, `app/api/chatwoot.py:159-163`, `app/services/whatsapp.py:37`.
- **PoC:** telefone (dado pessoal) é gravado em logs INFO em todo o caminho bot/webhook/reminders, retendo PII sem necessidade.
- **Correção:** mascarar/hashear telefone nos logs ou rebaixar para DEBUG.

#### V15 — Dados financeiros + nomes de clientes enviados à OpenAI
- **Categoria:** LGPD · **Local:** `app/services/kernel_ia.py:238-262`, `app/services/kernel_ia_finance.py:165-178`.
- **PoC:** o bloco determinístico do insight (que para `inativos` contém **nomes de clientes**; para
  `financeiro`/`ranking`/`folha` contém receita/comissões/nomes de barbeiros) é enviado ao endpoint da OpenAI. É
  manager-gated, mas dados financeiros e PII deixam a infraestrutura para processador terceiro (mesmo no caminho bot→n8n→OpenAI).
- **Correção:** minimização (não enviar nomes), base legal/DPA, consentimento; avaliar anonimização antes do envio.

#### V16 — Tabelas de plataforma sem RLS + GRANTs em massa que furam o isolamento; sem `FORCE RLS`
- **Categoria:** Priv / Config / Tenant · **Local:** `alembic/.../0021_platform_superadmin.py:46-47`, `scripts/seed.py:122-131`, `scripts/setup_local.sh:39-42`.
- **PoC:** `platform_admins` (com `password_hash` de superadmin) e `platform_audit_log` são protegidas só pela
  ausência de GRANT a `barber_app`. Mas `seed.py`/`setup_local.sh` rodam `GRANT ... ON ALL TABLES ... TO barber_app`
  + `ALTER DEFAULT PRIVILEGES`. Se executados após a criação dessas tabelas (re-seed; no dev já ocorre), o app
  ganha SELECT em `platform_admins` — e como não há RLS nem `FORCE`, não há segunda barreira; combinado com um
  eventual SQLi em código de tenant, permitiria enumerar hashes de superadmin.
- **Dado/ação exposta:** hashes de senha de superadmin + trilha de auditoria da plataforma (latente).
- **⚠️ Revisado em prod (2026-07-06):** em produção o `barber_app` **NÃO** tem GRANT em `platform_admins`/`platform_audit_log` (0 linhas) e é `NOBYPASSRLS` → **o pior caso não está ativo**. O risco cai para **latente** (reaparece se `seed.py`/`setup_local.sh` reaplicarem o GRANT em massa). Confirmado também que **nenhuma** tabela tem `FORCE ROW LEVEL SECURITY`.
- **Correção:** `REVOKE ALL ON platform_* FROM barber_app` explícito nas migrations; grants por tabela (não `ON ALL TABLES`); adicionar `FORCE ROW LEVEL SECURITY` como defesa em profundidade.

#### V17 — Tabelas-filhas sem RLS (isolamento por disciplina de JOIN)
- **Categoria:** Tenant · **Local:** `appointment_items` (`0001:238`, contém `price_charged`), `user_units`, `time_off`, `business_hours`, `barber_units`, `barber_services`, `client_consents`, `calendar_sync`.
- **PoC:** o banco não impõe tenant nessas tabelas; uma query futura por id direto (sem JOIN ao pai sob RLS) vazaria cross-org silenciosamente. Hoje todos os acessos escopam corretamente (verificado), mas é convenção, não barreira.
- **Correção:** adicionar `organization_id`+RLS às filhas sensíveis (ao menos `appointment_items`) **ou** cobrir com testes automatizados de disciplina de JOIN.

#### V18 — `webhook_events` / `coupons` (billing) sem RLS mas com GRANT a `barber_app`
- **Categoria:** Tenant · **Local:** `alembic/.../0032_billing_domain.py:366,195`, `models/billing.py:424,253`.
- **PoC:** hoje lidos só em rotas de plataforma (sem tenant), mas por terem GRANT e nenhuma policy, uma futura rota de tenant veria eventos/cupons de todas as orgs.
- **Correção:** RLS (onde há `organization_id`) ou revogar GRANT de tenant; documentar a restrição com teste.

#### V19 — `_require_bot_token` não é constant-time
- **Categoria:** AuthN · **Local:** `app/api/bot.py:136` (usa `!=` direto) — afeta `/bot/debounce*`, `/bot/messages`, `/bot/clients/photo`, `/bot/clients/paused-status`.
- **PoC:** comparação Python direta do token (enquanto `get_bot_db` usa `secrets_match`) → side-channel de timing sobre o bot token. Falha fechado se a key não estiver setada.
- **Correção:** trocar por `secrets_match()`.

#### V20 — Buffers de debounce globais entre tenants (memória, sem org)
- **Categoria:** Tenant / DoS · **Local:** `app/api/bot.py:76-88` (`_debounce`, `_seen_ids`, `_seen_content`, `_last_flush`).
- **PoC:** dicts de módulo chaveados só por telefone (sem `org_id`) → dois tenants com o mesmo número colidem no buffer/dedup; in-memory sem limite rígido → crescimento de memória/DoS por quem tiver o token e mandar muitos `message_id`s distintos.
- **Correção:** chavear por `(org, phone)`; mover para store com TTL (Redis) quando escalar.

#### V21 — Resolução de org do bot/webhook por header + fallback single-tenant
- **Categoria:** Tenant · **Local:** `app/deps.py:78-82`, `app/api/wa_webhook.py:184-197`, `app/api/chatwoot.py:126-131`.
- **PoC:** sem mapeamento de instância, a org cai em `settings.bot_organization_id` (org 1); Chatwoot hardcoda a org. No multi-tenant real do bot, uma instância não mapeada gravaria mensagens/consentimentos sob a org de fallback — um tenant afetaria outro. Impacto nulo hoje (single-tenant), crítico antes de habilitar múltiplos tenants no bot.
- **Correção:** exigir mapeamento explícito instância→org (falhar fechado sem ele); assinar/validar `X-Instance`.

### 🟢 BAIXA

#### V22 — CORS `allow_credentials=True` + `*` methods/headers + regex curinga
- **Categoria:** Config · **Local:** `app/main.py:24-31`, `app/core/config.py:32`. Starlette usa `fullmatch` → sem bypass por sufixo. Como a auth é Bearer (não cookie), `allow_credentials=True` é desnecessário e só amplia superfície; qualquer XSS em `*.taylorethedy.com` habilitaria requisições cross-origin credenciadas. **Correção:** desligar credentials; restringir methods/headers ao necessário.

#### V23 — `/auth/tenant` enumera organizações
- **Categoria:** Info · **Local:** `app/api/auth.py:27-53`. Devolve `{id, name}` para qualquer subdomínio → discovery de tenants, facilitando alvo do brute-force (**V2**). **Correção:** aceitável por design; considerar rate limit e não vazar `name`.

#### V24 — `GET /billing/subscription` e `/billing/plans` sem guard de manager
- **Categoria:** BAC · **Local:** `app/api/billing.py:101,124`. Qualquer papel do tenant lê a assinatura, `level`/`limits`/`features` e o catálogo. Sensibilidade baixa-média (postura comercial). **Correção:** aplicar `require_manager_access` se a intenção for restringir.

#### V25 — Confusão de tipo no `state` do OAuth do Google
- **Categoria:** Config · **Local:** `app/api/integracoes.py:75-78`. `_verify_state` lê `payload["sub"]` como `org_id` reusando a mesma chave HS256; um token de sessão de tenant (cujo `sub` é `user_id`) passado como `state` seria aceito. Baixo impacto. **Correção:** `aud`/`typ` dedicado ou chave separada.

#### V26 — Advisory locks com f-string
- **Categoria:** Config (hardening) · **Local:** `app/api/agenda.py:304`, `app/api/bot.py:903`, `app/services/membership.py:768`. Valor interpolado é inteiro do banco (não injetável hoje). **Correção:** usar `bindparam`.

#### V27 — Fernet com chave única estática (sem rotação)
- **Categoria:** Config/Info · **Local:** `app/core/crypto.py:35-42`. Sem `MultiFernet`; trocar a chave torna ilegíveis tokens OAuth já cifrados. Impacto atual baixo (Calendar não está em prod). **Correção:** planejar `MultiFernet`/rotação antes de escalar.

#### V28 — `except Exception` que respondem 200 em erro / mascaram violações
- **Categoria:** Config/Observabilidade · **Local:** `app/api/wa_webhook.py:225-228`, `app/api/chatwoot.py:209` (ack 200 mesmo em falha de gravação, com log), `app/api/platform_billing.py:461` (engole IntegrityError como "cupom duplicado"). Nenhum `except: pass` silencioso. **Correção:** distinguir erros; métricas de falha; não mascarar constraints inesperadas.

#### V29 — Segredo histórico no git (contexto de infra)
- **Categoria:** Config · **⚠️ Corrigido em prod (2026-07-06):** o firewall GCP **bloqueia** 8000/3000 (allowlist de ingresso = só 80/443/22) — as portas de app **não** são alcançáveis diretamente da internet, apenas via nginx/443. O componente "portas abertas" **cai**. Permanece: `credentials.json` no histórico git público (rotação/limpeza pendente — a chave OpenAI já foi revogada). **Correção:** `git filter-repo` + force-push coordenado; manter as portas de app fora da allowlist do firewall.

---

## 6. Matriz de priorização impacto × esforço

Impacto = dano se explorado. Esforço = trabalho para corrigir. **Onda** sugere a ordem de execução (quick wins de
alto impacto primeiro; fundações estruturais em seguida; itens latentes/escala por último).

| Achado | Severidade | Impacto | Esforço | Onda |
|---|---|---|---|---|
| **V1** webhook sem auth | Crítica | Alto | **Baixo** | **1 — imediato** |
| **V5** financeiro p/ recepção | Alta | Alto | **Baixo** | **1 — imediato** |
| **V7** bot-pause sem guard | Média | Médio | **Baixo** | **1 — imediato** |
| **V6** status/QR WhatsApp | Alta | Alto | Baixo | **1 — imediato** |
| **V4** SSE sem RBAC | Alta | Alto | Baixo-Médio | **1 — imediato** |
| **V19** bot token timing | Média | Baixo | Baixo | 1 — imediato |
| **V24** billing sem guard | Baixa | Baixo | Baixo | 1 — imediato |
| **V2** rate limiting/lockout | Alta | Alto | Médio | **2 — hardening auth** |
| **V9** revogação/refresh JWT | Média | Alto | Alto | 2 — hardening auth |
| **V11** política/reset de senha | Média | Médio | Médio | 2 — hardening auth |
| **V13** enumeração por timing | Média | Baixo | Baixo | 2 — hardening auth |
| **V12** cabeçalhos de segurança | Média | Médio | Baixo | 2 — hardening auth |
| **V10** token na URL (SSE) | Média | Médio | Baixo | 2 (junto de V4) |
| **V16** platform RLS/GRANT + FORCE | Média-Alta | Alto | Médio | **3 — isolamento estrutural** |
| **V17** filhas sem RLS | Média | Médio | Médio | 3 — isolamento estrutural |
| **V18** billing sem RLS | Média | Médio | Baixo | 3 — isolamento estrutural |
| **V3** bot token global = única barreira | Alta | Alto | Alto | 3 — isolamento estrutural |
| **V8** complete sem posse | Média | Médio | Baixo | 3 (junto do canal bot) |
| **V21** fallback single-tenant do bot | Média | Alto* | Médio | 3 (antes do bot multi-tenant) |
| **V20** debounce global | Média | Médio | Médio | 4 — escala |
| **V14** PII em logs | Média | Médio | Baixo | 4 — LGPD |
| **V15** dados à OpenAI | Média | Médio | Médio | 4 — LGPD |
| **V22** CORS credentials | Baixa | Baixo | Baixo | 4 |
| **V23** enumeração de org | Baixa | Baixo | Baixo | 4 |
| **V25** state OAuth | Baixa | Baixo | Baixo | 4 |
| **V26** advisory lock f-string | Baixa | Baixo | Baixo | 4 |
| **V27** Fernet sem rotação | Baixa | Baixo | Médio | 4 |
| **V28** except/200 em erro | Baixa | Baixo | Baixo | 4 |
| **V29** portas/segredo histórico | Baixa | Alto | Médio | infra (fora do código) |

\* V21 tem impacto **nulo hoje** (single-tenant) mas **alto** no momento em que o bot for habilitado para múltiplos tenants — deve ser resolvido **antes** desse marco.

### Causa-raiz transversal (endereçar na Fase 1/2)
As lacunas **V4, V5, V6, V7, V24** têm a mesma origem: **RBAC aplicado manualmente por função**, sem enforcement no
nível de router/dependência. Um guard central (`can(user, ação, recurso, contexto)`) como dependência de rota +
um teste que afirme "todo endpoint de recurso X exige permissão Y" **fecha a classe inteira de erro** e é
exatamente o núcleo pedido na Fase 2. Recomendação: tratar a taxonomia de permissões + guard central como o
primeiro entregável de código, e migrar os endpoints em bloco em vez de corrigir um a um.

---

## 7. Controles positivos confirmados (não regredir nas próximas fases)

- `SECRET_KEY` obrigatório sem default inseguro (`config.py:16`); algoritmo JWT fixado em `[HS256]` (sem `alg:none`/confusion).
- Comparações de segredo em **tempo constante** (`secrets_match`/`hmac.compare_digest`) em quase todos os pontos (exceção V19).
- Webhook **Stripe** verifica assinatura + exige secret; provider `mock` recusa webhooks. Webhook **Chatwoot** fail-closed (503/401).
- **RLS** com GUC local à transação (não vaza no pool); `barber_app` `NOBYPASSRLS`; policies bloqueiam escrita cross-org; funções SECURITY DEFINER mínimas com `search_path` fixo.
- Isolamento **bilateral** de tokens tenant × plataforma; impersonação auditada com motivo obrigatório.
- Crons respeitam **opt-out/cooldown/batch-limit**; `send_text` não dispara sem `EVOLUTION_API_URL`/`INSTANCE_NAME` (protege staging).
- **Gating do Kernel IA financeiro é robusto** (dupla camada: tool só existe para manager + recheck no dispatch + `guard_insight` fail-closed).
- bcrypt cost 12; mensagens de erro de login genéricas por texto; sem `verify=False`/TLS desabilitado em httpx.
- `record_message` como porta única de escrita da Inbox + idempotência por `(conv, wa_message_id, sender_type)`.

---

## 8. Confirmações contra a VM de produção (checagem read-only — 2026-07-06)

Os 5 itens que estavam "não determinados" foram verificados diretamente na VM (sem imprimir valores de
segredos — apenas presença/tamanho). Resultado:

| Item | Verificação | Resultado | Efeito na auditoria |
|---|---|---|---|
| **1. `WA_WEBHOOK_SECRET`** | grep no `/opt/barbeariapro/.env` | **ABSENTE** (nem definido) → default `""` → auth do webhook **desligada** | ✅ **V1 CONFIRMADA (Crítica).** O endpoint é acessível via `https://api.taylorethedy.com/bot/wa-webhook` (nginx→:8000) sem autenticação. |
| **2. Postgres RLS/GRANT** | `pg_roles`, `pg_class`, `role_table_grants` | `barber_app` = `NOBYPASSRLS` ✓ e `NOSUPERUSER` ✓; **RLS em `clients`/`users`/`payment_transactions`**; `platform_admins`/`platform_audit_log` **sem grant a `barber_app` (0 linhas)** | ✅ **V16 DESARMADA em prod** (o pior caso — app ler hash de superadmin — **não** está ativo). Vira risco **latente** (se `seed.py`/`setup_local.sh` reaplicarem o GRANT em massa). **`relforcerowsecurity=f` em TODAS** → recomendação `FORCE RLS` permanece. |
| **2b. Tabelas sem RLS** | `pg_class.relrowsecurity` | `appointment_items` = **sem RLS**; `webhook_events`/`coupons` = **sem RLS mas com GRANT `SELECT/INSERT/UPDATE` a `barber_app`** | ✅ **V17 e V18 CONFIRMADAS.** |
| **3. Headers no nginx** | grep `add_header`/HSTS/CSP/X-Frame em `/etc/nginx/` | **NENHUM** header de segurança | ✅ **V12 CONFIRMADA** — nem a app nem o nginx enviam HSTS/CSP/X-Frame/X-Content-Type/Referrer-Policy. |
| **4. Portas 8000/3000** | `gcloud compute firewall-rules list` | Allowlist de ingresso = **só 80/443/22 (+3389/ICMP)**; **8000/3000 NÃO expostas** à internet | ⚠️ **V29 CORRIGIDA** — as portas de app **não** são alcançáveis diretamente da internet (só via nginx/443). O componente "portas abertas" da V29 **cai**; permanece só o `credentials.json` no histórico git. |
| **5. `AUTH_SECRET` (next-auth)** | grep em `.env.docker`/`.env.superadmin` | **definido, len=96 (tenant) / 44 (superadmin), não-placeholder**; `AUTH_TRUST_HOST=true` | ✅ **Resolvido** — o placeholder está só no `.env.local` versionado (dev); **prod usa segredo forte**. Sem achado. |

**Outros fatos confirmados (contexto):** `SECRET_KEY` len=64 (forte, ✓), `OPENAI_API_KEY` presente len=167,
`EVOLUTION_INSTANCE_NAME` e `EVOLUTION_API_URL` **definidos** (a integração WhatsApp está configurada no backend
→ **V6 é funcional em prod**, não apenas teórica), `BOT_ORGANIZATION_ID`/`BOT_UNIT_ID` = fallback single-tenant
ativo (base da **V21**). `CORS_ORIGIN_REGEX` = `https://([a-z0-9-]+\.)?taylorethedy\.com` (confirma a análise da **V22**).

**Saldo das confirmações:** a **V1 (Crítica)** e as **V6/V12/V17/V18** ficam **confirmadas**; a **V16** e a **V29**
**enfraquecem** com os fatos de prod (GRANTs de superadmin ausentes; portas de app fechadas no firewall GCP). Nada
novo de severidade Alta+ surgiu. A auditoria está **fechada e ancorada no estado real de produção**.

---

> **Próximo passo (checkpoint da Fase 0):** aguardando aprovação para iniciar a **Fase 1 — Arquitetura Alvo**
> (`ARQUITETURA_ALVO.md` + ERD), que desenhará o modelo de papéis/permissões RBAC+ABAC, o guard central de
> autorização, a segurança de sessão, a auditoria, a estratégia multi-tenant reforçada e a UX da nova área de
> Segurança — **sem escrever código de implementação**.
