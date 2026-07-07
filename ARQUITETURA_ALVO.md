# ARQUITETURA_ALVO.md — Segurança, Permissões e Governança (BarbeariaPro)

> **Fase 1** do plano `promptseguranca.md` — Arquitetura Alvo (**design, sem código**). Ancorada na
> `AUDITORIA_SEGURANCA.md` (Fase 0) e no estado real de produção (§8 daquela auditoria). Cada decisão referencia
> os achados que resolve (V1–V29). **Nenhum código foi escrito.** Checkpoint obrigatório ao final.
>
> **Princípios herdados:** backend é a única fonte de verdade de autorização · isolamento multi-tenant absoluto e
> estrutural · não quebrar o que funciona (migração retrocompatível + rollback) · simplicidade para o operador,
> poder para o gestor · evoluir em vez de reescrever (reusar RLS, `user_units`, `client_consents`, o token atual).
>
> **Data:** 2026-07-06.

---

## 0. Sumário das decisões e trade-offs

| # | Decisão | Alternativa descartada | Por quê |
|---|---------|------------------------|---------|
| D1 | **RBAC baseado em permissões** (papéis = conjuntos de permissões nomeadas), com **ABAC** para posse e campos sensíveis | Manter os 4 papéis fixos com `if role in {...}` | Os 4 papéis fixos foram a causa-raiz de V4/V5/V6/V7 (checagem manual, "abre por omissão"). Permissões nomeadas + guard central fecham a classe inteira e habilitam papéis personalizados. |
| D2 | **Catálogo de permissões global** (seed único) + **papéis de sistema globais** (org_id NULL, imutáveis) + **papéis personalizados por org** | Semear papéis/permissões por org | Escala para milhares de tenants sem duplicar linhas; papel de sistema é template compartilhado. |
| D3 | **Guard central `can(user, ação, recurso, contexto)`** como **dependência de rota** + **filtragem de campo no DTO** | Continuar chamando `require_*` dentro de cada função | Enforcement por rota + teste de cobertura elimina o "esqueci a linha do guard". Campo sensível nunca depende do frontend. |
| D4 | **`/me/permissions`** alimenta o frontend (só UX); backend reforça tudo | Frontend decide por `role` estático (hoje) | Fecha a fragilidade do `proxy.ts` único; UI condicional passa a refletir permissões reais e revogação. |
| D5 | **Access token curto (15 min) + refresh rotativo** com detecção de reuso + **denylist por `jti` (Redis)** e tabela `sessions` | Manter JWT de 60 min sem revogação | Fecha V9 (revogação/logout/"sair de todos"), V10 (ticket p/ SSE), e habilita rebaixar/desativar usuário em tempo real. |
| D6 | **Isolamento estrutural em 2 camadas:** escopo automático de tenant no repositório **+ RLS com `FORCE`** como defesa em profundidade | Confiar só na RLS atual | Fecha V16/V17/V18 (tabelas-filhas e de plataforma) e blinda contra query futura que esqueça o JOIN. |
| D7 | **Auditoria append-only com escrita assíncrona** (fila/worker) e **encadeamento de hash** | Log síncrono no request | Não impacta latência; hash-chain dá evidência de adulteração para eventos financeiros/administrativos. |
| D8 | **Reusar `client_consents`** e evoluir para `consent_records` versionado (LGPD) | Criar do zero | Evolução, não reescrita — o opt-out de WhatsApp já vive ali (D-51). |

**Compatibilidade:** os 4 papéis atuais (`owner/manager/reception/barber`) viram 4 **papéis de sistema** cujo
conjunto de permissões reproduz **exatamente** o comportamento de hoje (ver §1.1 e matriz §1.2.4). A migração
semeia `user_roles` a partir de `user_units`. Nenhum endpoint muda de comportamento observável na virada — as
correções de autorização (V5/V6/V7 etc.) entram como **ajuste explícito de permissão default**, documentado.

---

## 1. Arquitetura Alvo

### 1.1 Modelo de papéis (Roles)

**Papéis de sistema (globais, imutáveis, `is_system=true`, `organization_id=NULL`):**

| Papel de sistema | Slug | Mapeia do papel atual | Resumo |
|---|---|---|---|
| Proprietário | `owner` | `owner` | Controle total do tenant, incluindo Segurança e Billing. |
| Sócio | `partner` | — (novo) | Como o Proprietário, exceto gestão de papéis/permissões e billing. |
| Gestor | `manager` | `manager` | Operação + financeiro + equipe + relatórios; **sem** gestão de papéis/billing. |
| Recepcionista | `reception` | `reception` | Agenda, clientes, CRM, conversas, fidelidade, venda de pacotes; **sem** financeiro. |
| Barbeiro | `barber` | `barber` | Só a própria agenda + solicitar remarcação; **sem** dado financeiro/PII ampla. |
| Estagiário | `intern` | — (novo) | Barbeiro com escopo reduzido (leitura), sem concluir/valorar. |
| Financeiro | `finance` | — (novo) | Financeiro/DRE/caixa/pagamentos + relatórios financeiros; **sem** operação. |
| Marketing | `marketing` | — (novo) | CRM, campanhas, fidelidade, analytics, visibilidade do site; **sem** financeiro. |
| Atendimento | `support` | — (novo) | Conversas/CRM/clientes (com PII); **sem** financeiro/equipe. |

- **Papéis personalizados por org:** o Proprietário/Gestor cria papéis com **nome, cor e ícone** e um conjunto de
  permissões escolhido do **catálogo** (§1.2). `is_system=false`, `organization_id` = a org. Não podem exceder o
  catálogo nem conceder permissões de plataforma.
- **Múltiplos papéis por usuário:** suportado via `user_roles` (ex.: Sócio **+** Barbeiro). As permissões efetivas
  são a **união** dos papéis (ver §1.4.3). Papéis são atribuídos **por unidade** (`unit_id`), preservando o
  modelo multi-unidade atual (`user_units`); um `unit_id` nulo = vale para toda a org.
- **Papel de plataforma** (`platform_admin`) permanece **fora** deste modelo (tabela e token próprios, D-55) — o
  superadmin não é um papel de tenant. Sem alteração.

**Trade-off:** introduzir 5 papéis novos aumenta a superfície de configuração. Mitigação: os novos papéis vêm
**pré-configurados** (defaults sensatos) e **ocultos por padrão** na UI simples; só aparecem quando o gestor
decide usá-los. O operador comum (Raquel/recepção, barbeiro) **não percebe complexidade nova**.

### 1.2 Taxonomia de permissões (RBAC + ABAC híbrido)

**Nomenclatura canônica:** `recurso.subrecurso.ação` (minúsculas, `.` como separador). Ações padrão:
`view`, `manage` (criar/editar/arquivar), `delete`, `export`, `approve`, `use`. Campos sensíveis usam um
sub-recurso próprio (ex.: `finance.margin.view`) para permitir **filtragem por campo** (§1.4.5).

#### 1.2.1 Catálogo (permissões-chave por módulo)

| Categoria | Permissão | Sensível? | Fecha achado |
|---|---|---|---|
| **Agenda** | `schedule.own.view`, `schedule.own.manage` | — | (ABAC barbeiro) |
| | `schedule.all.view`, `schedule.all.manage` | — | |
| | `schedule.reschedule.request` / `schedule.reschedule.approve` | — | |
| **Clientes** | `clients.view`, `clients.manage`, `clients.delete` | — | |
| | `clients.personal_data.view` (telefone/email/nascimento/notas) | **PII** | mascaramento V-frontend |
| | `clients.export` | **PII** | |
| | `clients.bot_pause` | — | **V7** |
| **CRM/Conversas** | `crm.leads.view`, `crm.leads.manage` | PII | |
| | `conversations.view`, `conversations.send` | PII | |
| | `conversations.stream` (SSE) | PII | **V4** |
| **Financeiro** | `finance.revenue.view` | **$** | **V5** |
| | `finance.margin.view`, `finance.cost.view` | **$ (campo)** | |
| | `finance.payroll.view` (folha/custo por pessoa) | **$ (campo)** | **V5** |
| | `finance.dre.view`, `finance.cash.view`, `finance.payments.view` | **$** | |
| | `finance.expenses.manage`, `finance.export` | **$** | |
| **Relatórios** | `reports.dashboard.view` (operacional, **sem dinheiro**) | — | **V5** |
| | `reports.dashboard.financial.view` (receita/ticket/comissão) | **$** | **V5** |
| | `reports.operational.view`, `reports.gestor.view` | misto | |
| **Equipe/Serviços** | `team.view`, `team.manage` | — | |
| | `team.cost.view` (modelo/custo/aluguel) | **$ (campo)** | |
| | `services.view`, `services.manage`, `services.cost.view` | **$ (campo)** | |
| **Fidelidade/Pacotes** | `loyalty.view`, `loyalty.manage` | — | |
| | `memberships.view`, `memberships.sell`, `memberships.manage` | **$** | |
| **Billing (assinatura da org)** | `billing.view`, `billing.manage` | **$** | **V24** |
| **Integrações** | `integrations.view` | — | |
| | `integrations.whatsapp.manage` (QR/conectar) | **sensível** | **V6** |
| | `integrations.calendar.manage` | — | |
| **Configurações** | `settings.company.manage` | — | |
| **Segurança (nova área)** | `security.roles.manage` (= `settings.permissions.manage`) | **admin** | |
| | `security.users.manage` (convites/papéis/reset) | **admin** | |
| | `security.sessions.view`, `security.sessions.revoke` | **admin** | |
| | `security.audit.view`, `security.audit.export` | **admin** | |
| | `security.site_visibility.manage` | — | (Fase 6) |
| | `analytics.view` | — | (Fase 7) |
| | `privacy.lgpd.manage` (consentimento, exportar/anonimizar titular) | **admin/PII** | (Fase 8) |
| **IA** | `ai.assistant.use` (navegação Kernel IA) | — | |
| | `ai.finance.query` (respostas financeiras no chat) | **$** | (mantém D-58) |

> O catálogo completo (código, descrição pt-BR, categoria, `is_sensitive_field`) será versionado como **seed
> global** em código na Fase 2, e é a **fonte** que popula tanto o backend quanto o `/me/permissions`.

#### 1.2.2 Onde RBAC basta e onde ABAC é necessário

- **RBAC puro:** "quem vê o Financeiro", "quem gera QR do WhatsApp", "quem gerencia papéis". Resolve pela união
  de permissões do usuário.
- **ABAC (atributo/posse) — imprescindível:**
  - **Posse do barbeiro:** `schedule.own.*` só alcança agendamentos onde `appointment.barber_id == user.barber_id`.
    Regra de contexto, não de papel (hoje em `check_appointment_ownership`). O guard avalia `context.owner_id`.
  - **Escopo de unidade:** um Gestor de uma unidade não age sobre outra — `user_roles.unit_id` limita o alcance.
  - **Campo sensível dependente de registro:** ver `finance.margin.view`/`team.cost.view` — o **mesmo** registro
    (ex.: um serviço) é visível, mas o campo `cost`/`margin` é redigido se faltar a permissão (§1.4.5).
- **ABAC de propriedade do dado (LGPD):** endpoints de titular (exportar/anonimizar) exigem que o ator tenha
  `privacy.lgpd.manage` **e** que o alvo pertença à org (RLS).

#### 1.2.3 Exceções por usuário (permission overrides)

`permission_overrides(user_id, permission_code, effect ∈ {allow, deny}, unit_id?)`. **`deny` sempre vence** o
`allow` de papel (fail-safe). Usos: conceder `finance.revenue.view` a um recepcionista específico sem criar papel;
revogar `clients.export` de um gestor. Auditado (§1.7) como mudança administrativa.

#### 1.2.4 Matriz papel × permissão (defaults — subconjunto representativo)

`✓` = concedido · `—` = negado · `own` = só os próprios (ABAC) · `op` = dashboard **sem** dinheiro.

| Permissão | owner | partner | manager | reception | barber | intern | finance | marketing | support |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `schedule.all.manage` | ✓ | ✓ | ✓ | ✓ | — | — | — | — | — |
| `schedule.own.*` | ✓ | ✓ | ✓ | ✓ | own | own(view) | — | — | — |
| `clients.manage` | ✓ | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `clients.personal_data.view` | ✓ | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `clients.export` | ✓ | ✓ | ✓ | — | — | — | — | — | — |
| `clients.bot_pause` | ✓ | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `conversations.stream` | ✓ | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `finance.revenue.view` | ✓ | ✓ | ✓ | — | — | — | ✓ | — | — |
| `finance.payroll.view` | ✓ | ✓ | ✓ | — | — | — | ✓ | — | — |
| `finance.dre.view` / `cash` / `payments` | ✓ | ✓ | ✓ | — | — | — | ✓ | — | — |
| `reports.dashboard.view` (op) | ✓ | ✓ | ✓ | op | — | — | ✓ | ✓ | — |
| `reports.dashboard.financial.view` | ✓ | ✓ | ✓ | **—** | — | — | ✓ | — | — |
| `team.cost.view` | ✓ | ✓ | ✓ | — | — | — | ✓ | — | — |
| `integrations.whatsapp.manage` | ✓ | ✓ | ✓ | **—** | — | — | — | — | — |
| `billing.view` | ✓ | ✓ | ✓ | — | — | — | ✓ | — | — |
| `billing.manage` | ✓ | — | — | — | — | — | — | — | — |
| `security.roles.manage` | ✓ | — | — | — | — | — | — | — | — |
| `security.users.manage` | ✓ | ✓ | ✓* | — | — | — | — | — | — |
| `security.audit.view` | ✓ | ✓ | ✓ | — | — | — | — | — | — |
| `ai.finance.query` | ✓ | ✓ | ✓ | — | — | — | ✓ | — | — |

\* `manager` pode gerir usuários **abaixo** do próprio nível (não pode criar owner/partner). Regra de
**não-escalonamento**: um ator só concede papéis cujo conjunto de permissões seja **subconjunto** do seu.

> **As três células em negrito** (`reports.dashboard.financial.view`, `integrations.whatsapp.manage` negados à
> recepção) são exatamente as correções de **V5** e **V6** materializadas como default de permissão.

### 1.3 Modelo de dados

**Entidades novas** (todas com `organization_id` + RLS, exceto catálogo global):

- `permissions` *(global)* — `id, code (unique), description, category, is_sensitive_field, created_at`.
- `roles` — `id, organization_id (NULL=sistema), slug, name, color, icon, is_system, is_assignable, created_at`.
  Papéis de sistema têm `organization_id NULL`; personalizados têm a org.
- `role_permissions` — `role_id, permission_id, effect (allow)` (PK composta). Para papéis de sistema é seed global.
- `user_roles` — `id, organization_id, user_id, role_id, unit_id (NULL=org toda), granted_by, created_at`.
  Substitui/estende `user_units` (migração em §1.4.6). UNIQUE `(user_id, role_id, unit_id)`.
- `permission_overrides` — `id, organization_id, user_id, permission_id, effect (allow|deny), unit_id, reason,
  granted_by, created_at`.
- `sessions` — `id, organization_id, user_id, refresh_token_hash, jti_current, device_label, user_agent, os,
  browser, ip, ip_geo, created_at, last_seen_at, revoked_at, revoked_by, rotated_from` (§1.5/§1.6).
- `audit_logs` — `id, organization_id, actor_user_id, actor_kind (user|platform|bot|system), action, resource_type,
  resource_id, before (jsonb), after (jsonb), ip, user_agent, result (allow|deny), reason, prev_hash, hash,
  created_at` (§1.7).
- `consent_records` — `id, organization_id, subject_type (client|lead|user), subject_id, channel
  (whatsapp|email|cookies|analytics|marketing), status (opt_in|opt_out), policy_version, source, ip, created_at`
  (evolui `client_consents` — §1.11).
- `client_visibility_settings` — `organization_id (PK/1:1), services (jsonb), professionals (jsonb), hours (jsonb),
  show_reviews, show_promotions, banner (jsonb), public_info (jsonb), updated_by, updated_at` (§1.9).
- `analytics_events` — `id, organization_id, anon_session_id, event_name, page, referrer, utm (jsonb),
  properties (jsonb), consent_ok, created_at` (particionada por mês — §1.10).

**Propagação de `organization_id` e RLS:** toda tabela nova sensível recebe `organization_id NOT NULL`, policy RLS
`USING (organization_id = current_setting('app.current_org_id')::bigint)` **e `FORCE ROW LEVEL SECURITY`** (fecha o
gap "force=f em tudo" da §8 da auditoria). `permissions` é global (sem RLS). `roles` de sistema (org_id NULL) usa
policy `USING (organization_id IS NULL OR organization_id = current_org)`.

**Índices para escala (milhares de tenants):**
- `user_roles (organization_id, user_id)` e `(role_id)` — resolução de permissões por request.
- `role_permissions (role_id)` — join do catálogo.
- `permission_overrides (organization_id, user_id)`.
- `sessions (user_id, revoked_at)` e `(jti_current)` — validação/refresh.
- `audit_logs (organization_id, created_at DESC)`, `(organization_id, actor_user_id)`, `(organization_id,
  resource_type, resource_id)` — timeline filtrável.
- `analytics_events (organization_id, created_at)` + **partição mensal** para não degradar.
- Cache de permissões efetivas em Redis por `(user_id, org)` com invalidação em mudança de papel/override.

**ERD (mermaid):**

```mermaid
erDiagram
    organizations ||--o{ users : has
    organizations ||--o{ units : has
    organizations ||--o{ roles : "custom roles"
    roles ||--o{ role_permissions : grants
    permissions ||--o{ role_permissions : in
    users ||--o{ user_roles : assigned
    roles ||--o{ user_roles : to
    units ||--o{ user_roles : scoped_to
    users ||--o{ permission_overrides : has
    permissions ||--o{ permission_overrides : on
    users ||--o{ sessions : owns
    organizations ||--o{ audit_logs : records
    users ||--o{ audit_logs : "actor"
    organizations ||--o{ consent_records : records
    clients ||--o{ consent_records : "subject"
    organizations ||--|| client_visibility_settings : configures
    organizations ||--o{ analytics_events : emits

    permissions {
        bigint id PK
        text code UK
        text category
        bool is_sensitive_field
    }
    roles {
        bigint id PK
        bigint organization_id FK "NULL=system"
        text slug
        text name
        bool is_system
    }
    user_roles {
        bigint id PK
        bigint user_id FK
        bigint role_id FK
        bigint unit_id FK "NULL=org-wide"
    }
    permission_overrides {
        bigint id PK
        bigint user_id FK
        bigint permission_id FK
        text effect "allow|deny"
    }
    sessions {
        bigint id PK
        bigint user_id FK
        text refresh_token_hash
        text jti_current
        timestamptz revoked_at
    }
    audit_logs {
        bigint id PK
        bigint actor_user_id FK
        text action
        text result "allow|deny"
        text prev_hash
        text hash
    }
```

### 1.4 Camadas de autorização

Cadeia por request (do borda ao dado):

1. **Autenticação** (`authn`): valida o access token (assinatura, `exp`, `alg` fixo, `typ`), rejeita revogado
   (denylist `jti`). Substitui/estende `get_token_data`.
2. **Resolução de tenant:** seta `app.current_org_id` (RLS) a partir do `org` do token — inalterado, já correto.
3. **Guard central de autorização** — `require(permission, resource_loader=None)` como **dependência de rota**:
   `can(user, permission, resource, context) -> allow|deny`. Nega por padrão (fail-closed). Emite evento de
   auditoria **em toda negação** (§1.7). Substitui os `require_full_access`/`require_manager_access` espalhados.
4. **Policies ABAC:** avaliadas pelo guard quando a permissão é `*.own.*` ou depende de contexto (posse do
   barbeiro, escopo de unidade, propriedade do titular). Recebe o recurso já carregado sob RLS.
5. **Filtragem de campo no serializer/DTO** (§1.4.5): antes de responder, campos marcados `is_sensitive_field`
   são **removidos** se faltar a permissão — nunca ocultados só no frontend.
6. **`/me/permissions`** (§1.4.4): expõe ao frontend a lista de permissões efetivas — **apenas para UX**
   (esconder menus/botões). Não é barreira.

#### 1.4.1 Forma do guard (design, não código)
`Depends(require("finance.revenue.view"))` na rota. Para ABAC: `Depends(require("schedule.own.manage",
resource="appointment", owner_field="barber_id"))` — o guard carrega o recurso sob RLS e compara com o ator.
Um **teste de cobertura** afirma: "toda rota sob `/financeiro`, `/admin/gestor`, `/equipe` declara uma permissão
`finance.*`/`team.*`; toda rota sob `/crm/stream` declara `conversations.stream`". Isso torna **impossível**
repetir V4/V5/V6/V7 sem o teste falhar.

#### 1.4.2 Resolução de permissões efetivas
`efetivas(user, org, unit) = (⋃ role_permissions dos user_roles aplicáveis) ∪ (overrides allow) \ (overrides deny)`.
Cacheada em Redis; invalidada em qualquer escrita de `user_roles`/`role_permissions`/`permission_overrides`.
`unit` restringe papéis com `unit_id` definido.

#### 1.4.3 Múltiplos papéis
União das permissões; **deny de override** tem precedência final. Sem "papel mais forte" — é o conjunto que decide.

#### 1.4.4 `/me/permissions`
`GET /me/permissions` → `{ roles: [...], permissions: ["finance.revenue.view", ...], units: [...] }`. O frontend
usa para renderização condicional (sidebar filtra por permissão — fecha a sidebar estática do `AdminSidebar.tsx`)
e para exibir a identidade real do usuário (fecha o rodapé hardcoded). **Reconsultado a cada login e a cada
refresh** (não mais congelado 8h) — rebaixar um usuário reflete no próximo refresh (≤15 min).

#### 1.4.5 Filtragem de campo sensível (field-level)
Serializers declaram campos sensíveis e a permissão exigida (ex.: `Service.cost → services.cost.view`,
`BarberSummary.monthly_cost → team.cost.view`, `Client.phone → clients.personal_data.view`). Uma camada única de
serialização remove o campo quando falta a permissão. Fecha a lacuna do frontend (dado financeiro/PII chegava cru
ao browser) e permite, por exemplo, a recepção ver a agenda mas **não** o valor cobrado.

#### 1.4.6 Migração retrocompatível (papéis)
`user_units(user_id, unit_id, role)` → para cada linha, cria `user_roles(user_id, role_id=<papel de sistema
equivalente>, unit_id)`. Os 4 papéis de sistema recebem, no seed, o conjunto de permissões que **reproduz o
comportamento atual** (full_access/manager_access/ownership). Uma **flag de compatibilidade** mantém os guards
antigos ativos até a paridade ser validada por testes; depois desliga. Rollback: manter `user_units` intacta e um
switch que volta aos guards legados.

### 1.5 Segurança de sessão e autenticação

| Medida | Design | Fecha |
|---|---|---|
| **Access token curto** | JWT HS256, `exp` 15 min, claims `{sub, org, jti, typ, roles_ver}` | V9 |
| **Refresh token** | opaco, aleatório 256-bit, **hash** no `sessions.refresh_token_hash`, cookie **httpOnly+Secure+SameSite=Strict** | V9 |
| **Rotação + detecção de reuso** | cada refresh gira o token; reuso de um já girado → **revoga a família inteira** (session) e audita | V9 |
| **Revogação / logout / "sair de todos"** | denylist de `jti` em Redis (TTL=exp) + `sessions.revoked_at`; logout individual e em massa | V9 |
| **CSRF** | double-submit token nas rotas que usam cookie (refresh/logout); API de dados segue Bearer no header | V22 |
| **Cabeçalhos de segurança** | middleware: HSTS, CSP, X-Frame-Options=DENY, X-Content-Type-Options=nosniff, Referrer-Policy, Permissions-Policy (app **e** nginx) | V12 |
| **Rate limit + lockout** | por IP+identidade em `/auth/login`, `/platform/auth/login`, refresh, webhooks, imports; backoff progressivo + bloqueio temporário | V2 |
| **Anti-enumeração** | resposta e **tempo** uniformes no login (bcrypt "dummy" quando o usuário não existe); mensagem genérica; org suspensa não vaza estado distinto | V13 |
| **Política de senha + reset** | tamanho/entropia mínimos; fluxo de troca e "esqueci a senha" com token de uso único e expiração | V11 |
| **SSE sem token na URL** | `POST /crm/stream/ticket` (autenticado + `conversations.stream`) emite **ticket de uso único** curto; `GET /crm/stream?ticket=` troca o ticket e **revalida usuário+permissão** no connect | V4, V10 |
| **Comparações constant-time** | padronizar `secrets_match()` em todos os tokens estáticos (inclui `_require_bot_token`) | V19 |
| **`/docs` protegido** | fechar/gate em produção | V12 |

**Decisão sobre o token exposto ao JS (achado de frontend):** o access token curto continua acessível ao cliente
(necessário para XHR), mas o **refresh** vive em cookie httpOnly (o JS nunca o vê) e o access expira em 15 min —
a janela de um XSS cai de 60 min sem revogação para 15 min **com** revogação. Evolução possível (fora do MVP):
proxy de API server-side no Next para manter também o access fora do JS.

### 1.6 Registro de dispositivos e sessões

Tabela `sessions` (§1.3) popula a tela "Dispositivos & Sessões": **IP**, **geolocalização aproximada por IP**
(serviço offline tipo base GeoLite, sem chamar terceiro com o IP do titular), **SO + navegador** (parse do
user-agent), **criado em** e **último acesso**. Ações: **revogar individual** (marca `revoked_at` + denylist do
`jti`) e **revogar em massa** ("sair de todos os dispositivos"). Sessão atual destacada e não auto-revogável por
engano. Toda revogação é auditada.

### 1.7 Auditoria

**Schema do evento:** ator (`actor_user_id` + `actor_kind`), tenant, ação, tipo+id do recurso, `before`/`after`
(jsonb, quando aplicável), IP, user-agent, `result` (allow/deny), motivo, timestamp — mais `prev_hash`/`hash`
para **encadeamento** (cada evento inclui o hash do anterior da mesma org → adulteração detectável).

**Eventos obrigatórios:** login/logout (sucesso e falha), criação/edição/exclusão de registros sensíveis,
**exportações** (CSV financeiro/clientes), **mudanças de permissão/papel/override**, alterações financeiras
(despesas, conclusão de atendimento, estorno, venda/cancelamento de assinatura), **tentativas negadas** (o guard
emite em toda negação), mudanças administrativas (convite/desativação de usuário, configurações), **impersonação**
(já auditada — integrar), conexão/QR de WhatsApp.

**Escrita assíncrona:** o request enfileira o evento (fila em Redis/tabela outbox) e um **worker** persiste — sem
impactar latência (D7). Retenção **configurável por org** (default 12 meses; financeiro/administrativo mais longo).
Reusar as trilhas parciais existentes (`LeadEvent`, `canceled_by`/`reverted_by`, `platform_audit_log`) como fontes
que passam a escrever no `audit_logs` unificado.

**UI "Auditoria":** timeline filtrável (ator, ação, recurso, período, allow/deny) e pesquisável; **exportação
também controlada** por `security.audit.export` e **ela própria auditada**.

### 1.8 Multi-tenant (isolamento reforçado)

- **Escopo automático no repositório** (defesa 1): uma camada de acesso a dados que **sempre** injeta o filtro de
  org, para que nenhuma query dependa de o desenvolvedor lembrar do JOIN.
- **RLS com `FORCE` (defesa 2):** aplicar `FORCE ROW LEVEL SECURITY` (hoje `force=f` em tudo — §8 da auditoria) e
  **adicionar RLS às tabelas-filhas sensíveis** (`appointment_items` — contém `price_charged`), fechando **V17**.
- **Tabelas de plataforma (V16):** `REVOKE ALL ON platform_* FROM barber_app` **explícito** nas migrations (não
  confiar na ausência de GRANT); trocar `GRANT ON ALL TABLES`/`ALTER DEFAULT PRIVILEGES` por grants por tabela.
- **Billing (V18):** RLS em `webhook_events` (tem `organization_id`) ou revogar o GRANT de tenant sobre
  `webhook_events`/`coupons`.
- **Bot/webhook (V21):** exigir **mapeamento explícito instância→org**; falhar fechado sem ele (remover o fallback
  silencioso para org 1) antes de habilitar o bot multi-tenant; tornar `WA_WEBHOOK_SECRET` **obrigatório** (V1).
- **Testes automatizados de isolamento:** suíte que, autenticada como org A, **tenta ativamente** ler/escrever
  recursos da org B (por id direto, por `X-Instance`, por tabela-filha) e **espera falha** (0 linhas / 403). Roda
  como `barber_app` (não superuser) para provar a RLS. Cobre cada tabela sensível.

### 1.9 Controle de visibilidade do cliente final (base da Fase 6)

`client_visibility_settings` (1:1 por org) controla o que aparece no **site público de agendamento** (que **ainda
não existe** — confirmado na Fase 0): serviços exibidos, profissionais exibidos, faixas de horário disponíveis,
exibir avaliações, exibir promoções, banner (imagem/título/CTA) e informações públicas (endereço, telefone,
redes). Gerido por `security.site_visibility.manage`. Endpoint público de leitura **read-only**, escopado por
subdomínio (reusa `app_org_id_by_subdomain`, D-54), com cache e **sem** vazar dado não-público.

### 1.10 Analytics de frontend (LGPD-compliant) (base da Fase 7)

`analytics_events` (§1.3). **SDK de coleta** no frontend com **gate de consentimento** (só emite se
`consent_ok`); sessão **anônima** (`anon_session_id`, sem PII). **Endpoint de ingestão** com rate limit e validação
de origem. Métricas/funis: cliques, conversões, agendamentos iniciados/concluídos, horários abandonados, serviços
mais vistos, profissionais mais procurados, origem de tráfego (UTM), navegação, tempo de permanência, funil
completo. Agregação por **job** (não consulta a tabela crua na UI). Alinhado com o Dashboard executivo pendente
("leads fora do horário / faturamento gerado pela IA").

### 1.11 LGPD e consentimento (base da Fase 8)

- **Banner de cookies** + **central de preferências** por categoria (necessários / analytics / marketing).
- **`consent_records`** (evolui `client_consents`, reusando o opt-out de WhatsApp da D-51): registra **o quê,
  quando, versão da política, origem, IP**, por canal e por titular (cliente/lead/usuário).
- **Retenção configurável** por tipo de dado (analytics curto, financeiro longo, auditoria conforme §1.7).
- **Direitos do titular:** endpoints de **exportação** (dados do titular em formato portável) e de
  **exclusão/anonimização** (respeitando obrigações legais de retenção fiscal — anonimiza PII, preserva agregados
  financeiros). Gerido por `privacy.lgpd.manage` e **auditado**.
- **Consent Mode** quando houver analytics/marketing de terceiros.
- **Minimização (V14/V15):** mascarar telefone em logs; reduzir o que vai à OpenAI (não enviar nomes de clientes
  no insight); base legal/DPA documentados.

### 1.12 UX da nova área administrativa — "Segurança"

Novo item de navegação principal **"Segurança"** (visível a quem tem qualquer `security.*`), com sub-abas.
Inspiração explícita: **Google Workspace Admin, Microsoft Entra Admin Center, GitHub Organization Settings, Stripe
Dashboard, Linear, Notion** — clareza e poucos cliques acima de densidade (princípio "Raquel").

- **Papéis & Permissões:** lista de papéis (chips com cor/ícone), contagem de usuários por papel; editor de papel
  com o **catálogo agrupado por módulo** (checkboxes), papéis de sistema marcados como somente-leitura; criar papel
  personalizado; **matriz papel×permissão** filtrável (estilo GitHub).
- **Usuários & Convites:** tabela com busca/filtro (papel, unidade, status), convidar por e-mail, atribuir
  papéis/unidades, overrides por usuário, reset de senha, ativar/desativar — substitui o placeholder
  `/admin/usuarios`.
- **Dispositivos & Sessões:** cards de sessões ativas (dispositivo/SO/navegador, IP+local aproximado, último
  acesso), revogar individual e "sair de todos" (estilo GitHub sessions).
- **Auditoria:** timeline filtrável/pesquisável com diff before/after (estilo Stripe events / Linear activity),
  exportação controlada.
- **Privacidade & LGPD:** central de consentimento, políticas de retenção, ferramentas de exportação/anonimização
  do titular.
- **Visibilidade do Site:** configuração do site público com **pré-visualização** (Fase 6).
- **Analytics & Insights:** cards de métricas, funis e gráficos de conversão (Fase 7).

Wireframe padrão de cada tela: **cabeçalho com título + ação primária**, **linha de cards/StatCards** quando há
métrica, **tabela com filtro/busca** ou **timeline**, painéis laterais para edição — reusando os primitivos já
existentes do design system (`SegmentedControl`, `StatCard`, `Panel`, `InitialAvatar`).

---

## 2. Mapa achado → solução (rastreabilidade Fase 0 → Fase 1)

| Achado (Fase 0) | Onde é resolvido nesta arquitetura |
|---|---|
| V1 webhook sem auth (Crítica) | §1.8 (secret obrigatório) — correção pontual imediata na Fase 2/3 |
| V2 sem rate limit | §1.5 (rate limit + lockout) |
| V3 bot token = única barreira | §1.8 (mapeamento instância→org, secret por tenant) + §1.7 (auditoria) |
| V4 SSE sem RBAC | §1.4.1 (guard por rota) + §1.5 (ticket de stream) |
| V5 financeiro p/ recepção | §1.2.4 (default nega `reports.dashboard.financial.view`) + §1.4.5 (field-level) |
| V6 QR WhatsApp sem guard | §1.2 (`integrations.whatsapp.manage`) + §1.2.4 (nega recepção) |
| V7 bot-pause sem guard | §1.2 (`clients.bot_pause`) + §1.4.1 (guard por rota) |
| V8 complete sem posse | §1.2 (ABAC posse) — permissão + `resource_loader` |
| V9/V10 sessão/JWT | §1.5 (refresh, revogação, ticket SSE) |
| V11 senha | §1.5 (política + reset) |
| V12 headers | §1.5 (middleware + nginx) |
| V13 enumeração | §1.5 (anti-enumeração) |
| V14/V15 LGPD (logs/OpenAI) | §1.11 (minimização) |
| V16 platform RLS/GRANT | §1.8 (REVOKE explícito + FORCE RLS) |
| V17 filhas sem RLS | §1.8 (RLS em `appointment_items` + FORCE) |
| V18 billing sem RLS | §1.8 (RLS/grant billing) |
| V19 bot token timing | §1.5 (constant-time) |
| V20 debounce global | §1.8 (chavear por org) / escala (Redis) |
| V21 fallback single-tenant | §1.8 (mapeamento obrigatório) |
| V22 CORS credentials | §1.5 (CSRF/headers, desligar credentials) |
| V23 enumeração de org | §1.5 (rate limit em `/auth/tenant`) |
| V24 billing sem guard | §1.2 (`billing.view`) + §1.4.1 |
| V25 state OAuth | §1.5 (aud/typ dedicado) |
| V26 advisory f-string | hardening (bindparam) na Fase 2 |
| V27 Fernet rotação | §1.5 (MultiFernet — quando escalar) |
| V28 except/200 | observabilidade (Fase 4) |
| V29 credenciais no git | infra (rotação/limpeza de histórico) |

---

## 3. Ordem de implementação proposta (Fases 2–8) e rollout

1. **Fase 2 (núcleo):** catálogo + papéis de sistema + guard central + `/me/permissions` + field-level + migração
   de `user_units`→`user_roles` + testes de permissão e de isolamento cross-tenant. **Já entrega V4/V5/V6/V7/V8/V24.**
   Corrigir **V1** (secret obrigatório) e **V19** aqui, por serem pontuais e de alto valor.
2. **Fase 3 (sessão):** refresh/rotação/revogação, `sessions`+dispositivos, cookies/CSRF/headers, rate
   limit/lockout, anti-enumeração, ticket de SSE, política/reset de senha. **V2/V9/V10/V11/V12/V13/V22.**
3. **Fase 4 (auditoria):** `audit_logs` + worker assíncrono + hash-chain + UI.
4. **Fase 5 (painel gestor):** dashboard de segurança (logins, negados, dispositivos, exportações, mudanças de
   permissão) + alertas de anomalia.
5. **Fase 6 (site público):** `client_visibility_settings` + telas + preview.
6. **Fase 7 (analytics):** SDK com consentimento + ingestão + agregação + funis.
7. **Fase 8 (LGPD):** banner + preferências + `consent_records` + retenção + exportar/anonimizar.

**Rollout (detalhado na Fase 9):** **feature flags** por tenant, virada gradual (owner das orgs-piloto primeiro),
**flag de compatibilidade** mantendo os guards legados até paridade validada por testes, monitoramento pós-deploy
(taxa de 403, latência do guard, erros de refresh) e **rollback** definido (voltar ao guard legado sem migração
destrutiva — `user_units` é preservada).

---

> **Checkpoint da Fase 1 — aguardando aprovação.** Aprovado o design, a **Fase 2 é a primeira fase de código**
> (backend): é o ponto de **trocar o modelo da sessão** antes de começar. Não escreverei implementação sem seu OK.
