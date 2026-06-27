# DECISIONS.md
> Decisões técnicas e de produto tomadas ao longo do projeto.
> Cada entrada tem: contexto, decisão, motivo e consequências.
> Nunca remover entradas — marcar como supersedida se mudar.

---

## Segurança e isolamento

### D-01 — Regra de Ouro: staging nunca toca produção
**Data:** 2026-06-16
**Decisão:** Staging usa banco separado (:5433), `EVOLUTION_API_URL` vazio e
`BOT_API_KEY` diferente. Nunca copiar `.env` de produção para staging.
**Motivo:** Em sessão anterior, `.env.staging` apontava para Evolution de prod —
risco real de disparo em massa de WhatsApp para clientes reais.
**Implementação:** Trava em `app/services/whatsapp.py:17` (dry-run nativo quando
`EVOLUTION_API_URL` vazio).

### D-02 — State JWT no fluxo OAuth (sem sessão server-side)
**Data:** 2026-06-21
**Decisão:** O parâmetro `state` do OAuth é um JWT assinado com `SECRET_KEY`, TTL
5 minutos, contendo `org_id`. Verificado no callback sem armazenamento em Redis/banco.
**Arquivo:** `app/api/integracoes.py:52-70` (`_build_state`, `_verify_state`).

### D-03 — Tokens OAuth cifrados em repouso (Fernet/AES-128)
**Data:** 2026-06-21
**Decisão:** `access_token` e `refresh_token` do Google são cifrados com Fernet
antes de persistir em `integration_accounts.token_encrypted`.
**Implementação:** `app/core/crypto.py`. Chave via `TOKEN_ENCRYPTION_KEY`.

---

## Arquitetura e escopo

### D-04 — Fase 2 sem contato com n8n/bot
**Data:** 2026-06-16
**Decisão:** A integração Google Calendar não toca o workflow n8n, Evolution nem bot WhatsApp.
**Motivo:** O bot em produção é o core do produto.

### D-05 — Sync Calendar como BackgroundTask (não fila/worker)
**Data:** 2026-06-21
**Arquivo:** `app/services/calendar_sync.py`.

### D-06 — Sem migration nova para a Fase 2 (Google Calendar)
**Data:** 2026-06-21
**Decisão:** Tabelas `integration_accounts` e `calendar_sync` já existiam desde `0001_initial`.

### D-07 — Callback OAuth redireciona para o frontend
**Data:** 2026-06-21
**Arquivo:** `config.py:53` (`google_frontend_success_url`).

---

## Frontend

### D-08 — Frontend é repositório git separado (sem remote funcional)
**Data:** descoberto em 2026-06-21; atualizado 2026-06-25
**Situação atual:** `barbearia-frontend/` tem seu próprio `.git` com remote
`https://github.com/DoctorDCombo/barbearia-frontend.git` — **este repo NÃO EXISTE**.
Commits locais existem mas não têm push remoto funcional.
**Deploy:** via scp + build Docker diretamente na VM.
Ver PROJECT_CONTEXT §2 para os comandos completos.
**Pendência:** considerar mover para `augustopegoraro-droid/barbeariapro` (subpasta) ou criar novo repo.

### D-09 — Agenda do barbeiro mobile-first
**Data:** 2026-06-21
**Arquivo:** `barbearia-frontend/app/barbeiro/agenda/page.tsx` (commit `205e43f`).

### D-10 — Botão "Conectar Calendar" usa endpoint `/authorize-url` (não redirect direto)
**Data:** 2026-06-21
**Motivo:** Axios/fetch seguem redirects automaticamente, mas Google bloqueia por CORS.
**Arquivo:** `app/api/integracoes.py:188-210` (`authorize_url_json`).

### D-31 — Admin shell: AdminSidebar + AdminHeader + AdminShell
**Data:** 2026-06-25
**Decisão:** Layout do admin separado em três componentes em `components/layout/`.
`AdminShell` compõe os dois e controla o estado `mobileOpen`.
`app/admin/layout.tsx` envolve todas as rotas `/admin/*` com `AdminShell`.
**Design tokens:** dark theme fixo (classe `dark` no `<html>`), amber `#f59e0b` como cor primária.

### D-32 — CRM view inicializada via `window.location.search`, não `useSearchParams`
**Data:** 2026-06-25
**Decisão:** `useState<"board"|"inbox">(() => new URLSearchParams(window.location.search).get("view") === "inbox" ? "inbox" : "board")`
**Motivo:** `useSearchParams()` do Next.js exige `<Suspense>` boundary; sem ele,
`next build` falha com "prerender error" na rota `/admin/crm`.
**Consequência:** `/admin/conversas` redireciona para `/admin/crm?view=inbox` (server redirect).

### D-33 — `/admin/conversas` é redirect, não página separada
**Data:** 2026-06-25
**Decisão:** `app/admin/conversas/page.tsx` chama `redirect("/admin/crm?view=inbox")` (server-side).
**Motivo:** Inbox já implementado no CRM page como toggle. Evita duplicação.

### D-36 — n8n REST API: PATCH para atualizar workflow (não PUT)
**Data:** 2026-06-25
**Decisão:** `PATCH /rest/workflows/{id}` funciona. `PUT` retorna 404.
**Campo de login:** `emailOrLdapLoginId` (não `email`) no `POST /rest/login`.
**Aprendido em:** auditoria 2026-06-25 ao tentar atualizar o system prompt via API.

### D-37 — `/admin/integracoes` como painel de operações WhatsApp
**Data:** 2026-06-25
**Decisão:** Página `/admin/integracoes` implementada com card WhatsApp:
- `GET /integracoes/whatsapp/status` — consulta connectionState da Evolution API
- `GET /integracoes/whatsapp/qr` — gera QR code base64 para reconexão
- Frontend: modal com QR auto-refresh 30s + poll de status a cada 3s (fecha ao conectar)
**Motivo:** WhatsApp cai toda vez que a VM reinicia. Operador precisa reconectar sem SSH.

---

## Produto e priorização

### D-11 — Lembrete 24h é feature de alto ROI
**Data:** 2026-06-21
**Decisão:** Após estabilização do CRM, próxima prioridade é lembrete 24h antes via WhatsApp.
**Atualização 2026-06-25:** `CronReminder24h01` confirmado saudável (5 execuções em 24/06, todas success).
Parou porque VM ficou TERMINATED. Volta a rodar automaticamente ao ligar a VM.

### D-12 — Google Calendar sync é ROI baixo (mas foi pedido)
**Data:** 2026-06-21
**Motivo:** Pedido direto do usuário.

---

## Infraestrutura e produção

### D-13 — Produção roda na VM via docker-compose, NÃO no Cloud Run
**Data:** 2026-06-23
**Decisão:** VM GCP `barbeariapro` (`34.95.199.134`), stack em containers.
**Consequência:** Sem backup automatizado dos volumes; VM ficou TERMINATED em 2026-06-25.
Verificar status da VM antes de cada sessão (ver PROJECT_CONTEXT §4).

### D-14 — n8n: SEMPRE via API REST, NUNCA editar o SQLite para workflows
**Data:** 2026-06-23; atualizado 2026-06-25
**Decisão:** Workflows e credenciais SEMPRE via API REST.
**Exceção aplicada em 2026-06-25:** Tabela `user` do SQLite editada para resetar senha
(quando login falha e não há outro caminho). Apenas a tabela `user` — nunca workflows.
```bash
# Login correto:
curl -s -c /tmp/n8n_cookies -X POST 'http://localhost:5678/rest/login' \
  -H 'Content-Type: application/json' \
  -d '{"emailOrLdapLoginId":"admin@barbearia.com","password":"Barbearia2026"}'

# Atualizar workflow (PATCH, não PUT):
curl -sb /tmp/n8n_cookies -X PATCH \
  'http://localhost:5678/rest/workflows/25QZQ664N6hrIg59' \
  -H 'Content-Type: application/json' -d @/tmp/wf_payload.json
```

### D-15 — Bot usa GPT-4o-mini + regra explícita de interpretação de slots
**Data:** 2026-06-23
**Alternativa se reincidir:** trocar node para `gpt-4o`.

### D-16 — `toolHttpRequest` do n8n não avalia `$env` em `fieldValue`
**Data:** 2026-06-23
**Decisão:** Nos nodes `toolHttpRequest`, o header `X-Bot-Token` recebe a
`BOT_API_KEY` **hardcoded** (não `={{ $env.BOT_API_KEY }}`).

### D-34 — nginx como reverse proxy na porta 80 (host, não container)
**Data:** 2026-06-25
**Decisão:** nginx instalado diretamente no host da VM.
Config em `/etc/nginx/sites-available/barbeariapro`; `default_server` porta 80 → `localhost:3000`.
**SSL pendente:** domínio `taylorethedy.app` não registrado. Quando registrado:
```bash
sudo certbot --nginx -d taylorethedy.app -d api.taylorethedy.com --redirect
```

### D-35 — Evolution: ao recriar instância, SEMPRE reconectar webhook ao FastAPI
**Data:** 2026-06-25
**Decisão:** O webhook da instância Evolution DEVE apontar para `http://host.docker.internal:8000/bot/wa-webhook`.
**Motivo:** Quando a instância foi recriada em 2026-06-25, o webhook foi acidentalmente apontado
para o n8n (`http://host.docker.internal:5678/webhook/whatsapp`). Isso quebra o CRM inbox:
mensagens de cliente não são gravadas em `conversations.messages` nem publicadas via SSE.
**⚠️ Atenção adicional: `byEvents` DEVE ser `false`**
Com `byEvents: true`, a Evolution roteia cada evento para um sub-path (`/bot/wa-webhook/send-message`,
`/bot/wa-webhook/messages-upsert` etc.) que não existem no FastAPI → 404 em tudo → bot mudo.
O endpoint FastAPI aceita todos os eventos no path base (`/bot/wa-webhook`); o campo `event` no
payload JSON distingue o tipo. **Sempre usar `byEvents: false`.**

**Correção:**
```bash
curl -s -X POST http://localhost:8080/webhook/set/Barbearia \
  -H 'apikey: 6BCBCA57CE49-4E10-9C21-5B9FECAE40B2' \
  -H 'Content-Type: application/json' \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://host.docker.internal:8000/bot/wa-webhook",
      "byEvents": false, "base64": false,
      "events": ["MESSAGES_UPSERT","MESSAGES_UPDATE","SEND_MESSAGE","CONNECTION_UPDATE","QRCODE_UPDATED"]
    }
  }'
```

---

## Correções de premissas dos docs antigos

### D-17 — Produção é `organization_id = 1` (supersede a premissa de org 3)
**Data:** 2026-06-23
**Realidade:** VM re-semeada do zero; única org é `id=1`. `BOT_ORGANIZATION_ID=1`.

---

## n8n: comportamento e armadilhas

### D-18 — n8n v2.27.3: fanout paralelo não executa os nós secundários
**Data:** 2026-06-23 (parte 5)
**Decisão:** Qualquer nó de log/efeito-colateral DEVE ser conectado em SÉRIE.
**Motivo:** Com fanout paralelo, apenas o primeiro nó da lista é executado.
```
DEPOIS (série — funciona):
  HTTP Flush Buffer → Code Horário     (Log Inbound desabilitado — ver D-30)
  AI Agent → Send Response → Log Outbound
```

### D-19 — jsonBody de HTTP Request n8n: usar expressão de objeto, não JSON.stringify
**Data:** 2026-06-23 (parte 5)

### D-26 — Webhook direto Evolution→FastAPI para eliminar delay do n8n
**Data:** 2026-06-24 (2ª sessão)
**Decisão:** Evolution aponta para `POST /bot/wa-webhook` (FastAPI) em vez de n8n.
Payload registrado imediatamente; encaminhado ao n8n em background (retry 3×).
**Arquivo:** `app/api/wa_webhook.py`; `app/core/config.py` (`n8n_webhook_url`, `wa_webhook_secret`).

### D-27 — Expressões n8n com `$` ficam corrompidas ao passar por SSH double-quote
**Data:** 2026-06-24 (2ª sessão)
**Solução:** Escrever payload em arquivo Python no servidor remoto antes de enviar via curl.

### D-28 — Credenciais n8n após reset acidental (atualizado 2026-06-25)
**Data:** 2026-06-24 (2ª sessão); senha redefinida em 2026-06-25
**Credenciais atuais n8n:** `admin@barbearia.com` / `Barbearia2026`
**Histórico:**
- Acidente `user-management:reset` em 2026-06-24 → credenciais recriadas via `/rest/owner/setup`
- Em 2026-06-25, login estava falhando → senha resetada via bcrypt direto no SQLite (só tabela `user`)
- Senha atual: `Barbearia2026` (sem `@` ou `!`)
**Se precisar resetar senha novamente:**
```bash
# Na VM, dentro do container n8n ou copiando o sqlite:
docker cp n8n:/home/node/.n8n/database.sqlite /tmp/n8n_db.sqlite
python3 -c "import bcrypt; print(bcrypt.hashpw('NOVA_SENHA'.encode(), bcrypt.gensalt(10)).decode())"
sqlite3 /tmp/n8n_db.sqlite "UPDATE user SET password='HASH_ACIMA' WHERE email='admin@barbearia.com';"
docker cp /tmp/n8n_db.sqlite n8n:/home/node/.n8n/database.sqlite
docker restart n8n
```

### D-29 — Não aplicar conversão 8→9 dígitos em `normalize_phone` sem migrar o DB
**Data:** 2026-06-24 (2ª sessão)
**Decisão:** NÃO aplicar conversão 8→9 em `normalize_phone`.
**Motivo:** `conv_id=1` tem `phone_e164 = '+556399368196'` (8 dígitos). Conversão quebraria lookup.
**Se quiser normalizar no futuro:** migrar DB primeiro.

### D-30 — `Log Inbound Message` desabilitado no n8n (não deletado)
**Data:** 2026-06-24 (2ª sessão)
**Decisão:** Nó desabilitado (não removido). `HTTP Flush Buffer` conecta direto em `Code Horário Comercial`.
**Motivo:** Com webhook direto, mensagens de cliente já gravadas antes do n8n. Duplicaria se Log Inbound rodasse.

---

## Bot WhatsApp (sessão 2026-06-25, 2ª)

### D-38 — System prompt do bot deve listar todos os barbeiros ativos
**Data:** 2026-06-25
**Problema:** Prompt hardcodava apenas Taylor e Thedy. Novos funcionários (Marciana, Sandra, Pablo)
foram cadastrados no DB mas nunca adicionados ao prompt → bot negava que trabalhavam na barbearia.
**Solução:** Seção `OS BARBEIROS` no system prompt atualizada com todos os 5 funcionários.
**Regra:** Ao cadastrar um novo barbeiro na plataforma, atualizar o system prompt via API:
```bash
# Exportar workflow, editar a seção OS BARBEIROS, re-importar com PATCH
curl -sb /tmp/n8n_cookies http://localhost:5678/rest/workflows/25QZQ664N6hrIg59 > /tmp/wf.json
# Editar /tmp/wf.json com python (substituir seção OS BARBEIROS)
curl -sb /tmp/n8n_cookies -X PATCH \
  'http://localhost:5678/rest/workflows/25QZQ664N6hrIg59' \
  -H 'Content-Type: application/json' -d @/tmp/wf.json
```
**Nota:** A tool `listar_barbeiros` existe no workflow mas o bot não a chama proativamente
quando perguntam "quem trabalha aqui?". Depende do knowledge no system prompt.

### D-39 — Tabela `barbers` usa `deleted_at` para soft-delete (não `is_active`)
**Data:** 2026-06-25
**Realidade:** A tabela `barbers` não tem coluna `is_active`. Barbeiro ativo = `deleted_at IS NULL`.
```sql
SELECT id, name FROM barbers WHERE organization_id=1 AND deleted_at IS NULL;
```

---

## CRM Conversacional (sessão 2026-06-24, 1ª)

### D-20 — `POST /bot/messages` grava sem cliente
**Estado atual:** `log_message` chama `record_message(client_id=None)`. Backfill quando AI cadastra cliente.

### D-21 — SSE usa query param para autenticação
**Data:** 2026-06-24 (Fase 5)
**Decisão:** `GET /crm/stream` aceita JWT como `?token=<jwt>`.
**Motivo:** Browser `EventSource` não suporta headers customizados.
**Arquivo:** `app/api/conversations.py` (`sse_stream`).

### D-22 — Idempotência de mensagem namespaced por conversa
`UNIQUE(conversation_id, wa_message_id, sender_type) WHERE wa_message_id IS NOT NULL`

### D-23 — `_publish` chamado após `flush()`, antes do `commit()`
**Motivo:** `flush()` garante `msg.id`; payload completo no evento elimina GET de follow-up.

### D-24 — `message_log` é intocado pelo CRM Conversacional
**Invariante:** `message_log` = reminders/reativação. `messages` = store canônico de conversa.

### D-25 — `Dockerfile.migrate.dockerignore` para builds de migration
**Motivo:** `.dockerignore` principal exclui `alembic/`; builds de migration precisam dele.

### D-40 — Auditoria arquitetural + endurecimento de segurança (Fase 1)
**Data:** 2026-06-26
**Contexto:** Início do trabalho de evolução para plataforma SaaS multi-tenant. Auditoria completa
salva em `~/.claude/plans/partitioned-greeting-stearns.md`; memória técnica viva criada em `CLAUDE.md`.
**Decisões:**
1. **`CLAUDE.md`** passa a ser a memória técnica viva do repo (referencia, não duplica, este arquivo).
2. **IA continua no n8n** (expandir tools REST `/bot/*`); não construir camada de agentes no backend agora.
3. **Prioridade = Segurança primeiro.** Fase 1.1 aplicada (commit `13822a1`): `print` de debug do
   webhook trocado por `logger.debug`; comparação de `X-Bot-Token`/`X-Webhook-Secret` agora é
   tempo-constante via `app.core.security.secrets_match()`.
4. **`SECRET_KEY` de produção verificado: forte** (64 chars ~hex 256 bits). **NÃO rotacionar** — o
   placeholder `troque-isto...` existia só no `.env` local, nunca em produção.
5. **Firewall GCP endurecido:** removidas as regras `allow-n8n` (5678) e `allow-evolution` (8080).
   Postgres 5432 já estava fechado (sem regra de allow). Bot/WhatsApp **não afetados** (fluxo interno
   via `host.docker.internal`): Evolution `state=open`, n8n 200, backend 200 após a mudança.
**Consequências:** n8n editor e Evolution Manager **não são mais acessíveis direto pela internet**.
Acesso agora só por SSH tunnel:
```bash
# n8n editor → http://localhost:5678
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a -- -L 5678:localhost:5678
# Evolution Manager → http://localhost:8080/manager
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a -- -L 8080:localhost:8080
```
**Atualização (mesmo dia):** ✅ **chave OpenAI rotacionada e a antiga REVOGADA** (validado end-to-end; n8n
usa OpenAI na credencial `openAiApi` E em `$env.OPENAI_API_KEY`).
**Pendente:** limpar histórico git de `credentials.json` (`git filter-repo` + force-push — seguro, chave já
revogada); HTTPS/domínio; tornar webhook secret obrigatório (provisionar nos 2 lados); **deploy do Fase 1.1
na VM** (VM ainda em `3e138b5`).

### D-41 — Bot WhatsApp não entrega: número restrito → migrar para Cloud API oficial
**Data:** 2026-06-26
**Contexto:** Bot recebia mensagens mas NÃO entregava as respostas. Diagnóstico exaustivo isolou a causa.
**Descartado (tudo verificado OK):** OpenAI (rotacionada), CRM, n8n, webhook, firewall, sessão Signal
(instância recriada do zero), e **versão da Evolution** (upgrade testado até `2.4.0-rc2` com suporte a LID
+ licença ativada — mesmo erro `Closing session/pendingPreKey` → `status: ERROR`). Falha **global** (2
números distintos testados).
**Conclusão:** o número do bot **`5563920001734` está restrito pelo WhatsApp** (recebe, descarta a saída).
Nenhuma mudança de software resolve.
**Decisões:**
1. **Rollback da Evolution para 2.3.7** (estável; a 2.4.0-rc exige licença Evolution Foundation + heartbeat
   5min = dependência externa indesejada). Imagem fixada na digest `@sha256:966625532d90...`.
2. **Correção real escolhida: migrar para a WhatsApp Cloud API oficial (Meta)** — sem Baileys/ban/LID.
   Requer: Meta Business verificado + número DEDICADO limpo + templates aprovados (p/ lembrete/reativação,
   que são proativos >24h). Trabalho no nosso lado: reescrever `app/services/whatsapp.py` (Graph API),
   novo parser de webhook (formato Meta + verificação de assinatura), repontar envio no n8n, templates, mídia.
**Backups (rollback Evolution):** `/opt/barbeariapro/backups/evolution_db_20260626_1221.sql` +
`docker-compose.yml.bak-2.3.7`.

---

### D-42 — Frontend: Design System + React Query (rearquitetura F1–F3)

**Contexto:** o frontend tinha telas monolíticas (CRM 1389 ln, Agenda 720 ln), data fetching manual
(`useEffect+axios+useState`), zero React Query (apesar de instalado) e nenhum Design System.

**Decisão:** rearquitetar em fases, **evoluindo sem reescrever**, com um Design System único e React Query.
Padrão de toda tela: **página enxuta** + `components/<domínio>/*` + `hooks/use-<domínio>.ts` + `AsyncState`
(os 5 estados de UI padronizados em `components/patterns`). Tokens em `app/globals.css`; **nada hardcoded**.
Primitivos reutilizáveis promovidos a `components/ui/`: `SegmentedControl`, `StatCard`, `Panel`/`SectionTitle`
(`section.tsx`), `InitialAvatar`. **Fonte de verdade do frontend: `barbearia-frontend/AGENTS.md`** (roadmap F1–F4).

- **F1** fundação (tokens, patterns, React Query: `providers.tsx`, `lib/queryClient.ts`, `hooks/use-authed-query.ts`).
- **F2** migra 6 telas para React Query (clientes, serviços, equipe, financeiro, dashboard, barbeiro/agenda).
- **F3** quebra os monólitos: **Inbox sai do CRM para `/admin/conversas`** (o SSE passa a atualizar o cache do
  React Query via `setQueryData`); CRM vira **só funil**; Agenda admin vira **grade do dia por profissional**.

**Estado:** branch `feat/design-system-react-query-f1-f3` (`3399587`), **não mergeado, não deployado**.
Validado no browser (extensão Chrome) contra o staging (org 1). `tsc`/`eslint`/`build` limpos (20 rotas).

**Como aplicar:** `cd barbearia-frontend && git checkout feat/design-system-react-query-f1-f3`. Ao mexer no
frontend, **ler `AGENTS.md` primeiro** e seguir o padrão (reuso de `ui/` + `patterns`, tokens, React Query).

---

### D-43 — Agenda: reagendar pode trocar de profissional (drag entre colunas)

**Contexto:** a Agenda do dia tem uma coluna por profissional com drag-and-drop. `PATCH /agenda/{id}/reagendar`
só mudava o horário (mantinha `AppointmentItem.barber_id`), impedindo arrastar o card para outro profissional.

**Decisão:** o endpoint passa a aceitar **`barber_id` opcional**. Quando muda: revalida o vínculo
**serviço↔profissional** (`BarberService`, reusando a lógica do `POST /agenda`) → `422` se o novo profissional
não executa o serviço; checa **conflito no NOVO barbeiro** (`barber_has_conflict`, excluindo o próprio);
atualiza `AppointmentItem.barber_id`. `AppointmentOut` passa a **expor `barber_id`** (o frontend precisa para o
drag). **Sem migração de DB** (só atualiza valor de coluna). Multi-item (combo entre barbeiros, raro): troca só
o item primário.

**Estado:** **mergeado em `main`** (PR #2, commit `b2087ab`, merge `469f784`). **Não deployado na VM.**
Testes em `tests/test_e2e_flow.py` (descobrem fixtures via API; suíte 211 pass / 3 fail ambientais).
No frontend, arrastar para um profissional que não executa o serviço → 422 → o bloco **reverte silencioso**
(falta toast — dívida anotada); o diálogo "Reagendar" mostra o erro corretamente.

---

### D-44 — Mensalidade/assinatura do CLIENTE FINAL com pacotes (combo fixo)

**Contexto:** faltava no produto a venda de **mensalidades para o cliente final** (combo de serviços com N usos
na vigência). `Plan`/`Subscription` em `models/organization.py` são billing do **tenant SaaS** — não servem aqui
e **não podem colidir**. Greenfield em namespace próprio `membership_*`, aditivo e retrocompatível.

**Decisões de produto (confirmadas com o usuário):**
1. **Pacote = combo fixo do plano**: cada plano define UM combo (lista de serviços); 1 uso = realizar o combo;
   o plano dá N usos (1/2/4/`NULL`=ilimitado). Períodos 30/90/180/365 dias.
2. **Receita rateada no uso** (deferred revenue): a **venda NÃO vira receita de serviço**; cada uso reconhece
   `preço_pago / usos_incluídos` distribuído nos `AppointmentItem.price_charged` → o financeiro e a comissão
   por profissional funcionam **sem alteração**. Consequência conhecida: `total_revenue` (de `price_charged`)
   passa a divergir de `sum(by_method)` (de `Payment`) pelo valor das mensalidades — correto contabilmente.
3. **Catálogo = entidade nova**: `membership_plans` (+ `membership_plan_items` → `services`),
   `client_memberships` (snapshots imutáveis: `price_paid`, `included_uses`, `unit_recognized_value`,
   `combo_snapshot` JSONB, `duration_days`), `membership_usages` (histórico + `appointment_id UNIQUE`).

**Decisões de design:**
- **Vínculo canônico** assinatura↔atendimento = `membership_usages.appointment_id UNIQUE` → **`appointments`
  não é alterada** (retrocompat total com agenda/financeiro/loyalty/Google Calendar).
- **Double-spend**: baixa atômica `UPDATE client_memberships SET used_uses=used_uses+1 WHERE status='ativa'
  AND end_at>now() AND (included_uses IS NULL OR used_uses<included_uses) RETURNING` — sem advisory lock; tudo
  na transação única do `get_tenant_db` (falha posterior → rollback devolve o saldo). `display_number` mantém
  `pg_advisory_xact_lock(unit.id)`.
- **Expiração**: guard lazy no uso (`end_at>now()` na baixa) + sweep `POST /internal/memberships/expirar` (cron
  n8n, X-Bot-Token). Pacotes não usados expiram sem rollover.
- **Conclusão por mensalidade** (`app/api/barbeiro.py`): NÃO cria `Payment`, NÃO sobrescreve `price_charged`
  (mantém o rateio); `method`/`amount` viram opcionais. Cancelar/faltou chamam `revert_usage` (idempotente).
- Regra de negócio isolada em `app/services/membership.py` (reutilizável por painel, cron e futuras tools do bot).

**Arquivos:** `models/membership.py` + `models/enums.py` (`MembershipStatus`) + migrations `0012_memberships`,
`0013_grant_membership_tables`; `app/services/membership.py`; `app/api/memberships.py` (router +
`internal_router`); alterações mínimas em `app/api/barbeiro.py` e `app/main.py`. Frontend:
`app/admin/assinaturas/` + `hooks/use-assinaturas.ts` + `components/assinaturas/*` + item de sidebar.

**Estado:** implementado e testado no **staging (org 1)**. Migrations aplicadas no staging (`alembic upgrade head`
com `ADMIN_DATABASE_URL`). Suíte backend **226 pass / 3 fail ambientais / 1 skip**; novos testes
`tests/test_membership_unit.py` (10) + `tests/test_membership_integration.py` (5). Frontend `tsc`/`eslint`/`build`
limpos (rota `/admin/assinaturas`). **Não mergeado em `main`, não deployado na VM** (migrations 0012/0013
pendentes em produção — rodar como `postgres`/`ADMIN_DATABASE_URL`, app não tem privilégio de DDL).

---

### D-45 — Tela `/admin/empresa`: configuração do negócio (cadastro, funcionamento, plano)

**Contexto:** `/admin/empresa` era placeholder "Em breve". A `Organization` só tinha `name` — faltava o
cadastro do negócio (razão social, CNPJ, contato, logo), base para o white-label "Taylor & Thedy" e para o
SaaS multi-empresa. Endereço/timezone e horário de funcionamento já existiam em `Unit`/`BusinessHours` mas
sem endpoints. Implementados os eixos 1 (cadastrais), 2 (endereço/horário) e 4 (plano) — eixo 3 (integrações)
ficou de fora por já existir em `/admin/integracoes`.

**Decisões de design:**
- **Aditivo/retrocompat:** migration `0014_organization_profile` adiciona 7 colunas nullable em `organizations`
  (`legal_name, cnpj, phone, email, website, instagram, logo_url`). GRANT defensivo idempotente (`SELECT, UPDATE`)
  — o seed já concede CRUD ao `barber_app`, mas alinha com a postura de 0011/0013. Migration roda como
  `ADMIN_DATABASE_URL` (app não é owner da tabela → "must be owner of table organizations").
- **Router único `app/api/empresa.py`** (owner/manager via `require_manager_access`): `GET /empresa` agrega
  org + unidade principal + horários + assinatura + uso (`usage`); `PATCH /empresa` (cadastrais, string vazia→NULL);
  `PATCH /empresa/unidade` (endereço/timezone); `PUT /empresa/horarios` (**replace-all** da grade semanal).
- **Unidade principal** = primeira `Unit` não-deletada da org (`_primary_unit`). Premissa: 1 unidade ativa por
  org hoje. Multi-unidade fica para depois.
- **Plano é read-only** — sem billing/escrita de `Subscription`. `selectinload(Subscription.plan)` evita
  `MissingGreenlet` (lazy-load de relacionamento fora do contexto async).
- **Horário MVP:** 1 faixa por dia (estrutura aceita N faixas — `bh_unique_slot` permite intervalo de almoço
  no futuro). Validação `close>open` no Pydantic e no router (além do CheckConstraint do banco).

**Frontend:** página enxuta (`app/admin/empresa/page.tsx`) compõe `AsyncState` + `Panel`s; hook
`hooks/use-empresa.ts` (React Query: query + 3 mutations com `invalidateQueries(["empresa"])`); componentes de
domínio em `components/empresa/` (cadastro-form, unidade-form, horarios-editor, plano-card); tipos em
`types/index.ts`. Forms inline na página (não dialogs), com estado "dirty" e feedback "salvo ✓".

**Estado:** implementado e testado no **staging**. Migration aplicada (`alembic upgrade head` via
`ADMIN_DATABASE_URL`). Suíte backend **230 pass / 3 fail ambientais / 3 skip**; novo
`tests/test_empresa_integration.py` (6: estrutura, round-trip cadastral, replace de horários, 422, RBAC barber).
Frontend `tsc`/`eslint` limpos (`next build` só falha no fetch da fonte Inter — ambiental/sandbox sem rede).
**Falta:** verificação no browser + deploy na VM (migration 0014 pendente em produção).

---

## Dívida técnica conhecida (não resolver sem discussão)

| Item | Arquivo | Severidade | Observação |
|---|---|---|---|
| Sem backup dos volumes Docker da VM | infra VM | ⚠️ Alto | VM ficou TERMINATED em 2026-06-25 |
| ~~Debug print temporário no webhook~~ | `app/api/wa_webhook.py` | ✅ Resolvido | D-40: trocado por `logger.debug` (commit `13822a1`) |
| Bot responses não confirmadas no CRM | fluxo n8n + Evolution | ⚠️ Alto | Pendente confirmação end-to-end |
| Frontend sem remote git funcional | `barbearia-frontend/.git` | ⚠️ Médio | DoctorDCombo/barbearia-frontend não existe |
| HTTPS / domínio não configurado | infra VM | Médio | nginx pronto; falta registrar taylorethedy.app |
| Portas abertas ao mundo na VM | firewall GCP | Médio (reduzido) | D-40: 5678/8080 fechadas; 5432 já fechada. Restam 8000/3000 (uso direto do browser) — mover p/ nginx+HTTPS |
| Estado do bot em memória (debounce) | `app/api/bot.py` | Médio | Restart perde estado. Aguarda Redis. |
| SSE single-process | `app/services/sse_broker.py` | Baixo | Não funciona com múltiplos workers |
| Token JWT visível em query string do SSE | `GET /crm/stream?token=` | Baixo | Aceitável para MVP interno |
| `workflows.json` local diverge da VM | `workflows.json` | ⚠️ Alto | Exportar da VM antes de qualquer edição local |
| Formato de telefone 8 vs 9 dígitos | DB + `normalize_phone` | Médio | conv_id=1 tem 8 dígitos. Ver D-29. |
| 3 testes ambientais falham | `tests/` | Baixo | n8n bypass_hours, RLS isolation, par `1/6` hardcoded — **não são bugs** |
| Drag da Agenda reverte silencioso em erro | `barbearia-frontend/components/agenda` | Baixo | Reagendar inválido (serviço/conflito) → 422 → bloco volta sem toast (D-43). Diálogo Reagendar mostra o erro. |
| Frontend F1–F3 não mergeado/deployado | `barbearia-frontend` branch | ⚠️ Médio | Branch `feat/design-system-react-query-f1-f3`; mergear + deployar (D-42). Inbox exige migrations 0010/0011 (prod já ok). |
| System prompt do bot hardcoda barbeiros | n8n AI Agent node | Médio | Ao cadastrar novo barbeiro, atualizar manualmente (D-38) |
| VM sem política de reinício automático | GCP VM | ⚠️ Alto | WhatsApp cai toda vez que VM reinicia; usar /admin/integracoes |
| Migrations 0012–0014 + telas novas não deployadas | VM / `barbearia-frontend` | ⚠️ Médio | `/admin/assinaturas` (D-44) e `/admin/empresa` (D-45) só no staging; aplicar 0012/0013/0014 em prod via `ADMIN_DATABASE_URL` |
