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

### D-08 — Frontend é repositório git separado (remote RESTAURADO 2026-06-29)
**Data:** descoberto em 2026-06-21; remote restaurado 2026-06-29
**Situação atual:** `barbearia-frontend/` tem seu próprio `.git` (histórico disjunto do
backend). O remote antigo `DoctorDCombo/barbearia-frontend` **não existia**; foi
substituído por `https://github.com/augustopegoraro-droid/barbearia-frontend.git`
(privado) e **registrado como submódulo** (`.gitmodules`). `main` + branches com push OK.
**Ponteiro do submódulo:** o gitlink no backend ainda aponta para `f5397a8` (válido, está
no `main` do remote novo); **bumpar para o `main` atual após o merge** da branch de frontend.
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

### D-46 — Deploy de `/admin/empresa` (D-45) + `/admin/assinaturas` em produção

**Data:** 2026-06-27 (5ª sessão)
**Contexto:** sessão de "deploy das pendências". A auditoria pré-deploy revelou que **os docs estavam
defasados quanto ao estado de produção**:
- Prod já estava em migration **`0013`** (não `0011`): `0012`/`0013` (memberships) **já aplicadas**.
- Backend mensalidade (D-44) **já estava live** (`/memberships` no openapi). Faltava só a **tela
  `/admin/assinaturas`** no frontend (a VM rodava apenas F1–F3).
- VM backend em **`4b87e2f`** (merge PR #3), não `469f784`.

**Decisões/execução:**
1. **D-45 commitada e mergeada** (não ficou mais só uncommitted): backend **PR #4 → `9b945c7`**; frontend
   commit **`1e39857`**. Os `.md` de análise CRM antigos (`ARQUITETURA_CRM_*`, `CRM_*`, `N8N_ACCESS_RECOVERY`)
   ficaram **untracked de propósito** (são históricos/superados) — limpeza fica para depois.
2. **Backup do DB de prod antes da migration** (`backups/barbeariapro_predeploy_0014_*.sql`).
3. **Migration `0014`** aplicada via imagem `Dockerfile.migrate` com `DATABASE_URL` = admin
   (`postgres`/`POSTGRES_PASSWORD`), pois `ADMIN_DATABASE_URL` **não existe no `.env` da VM** (só nos
   `.example`). **Lição:** o `deploy/update.sh` assume `ADMIN_DATABASE_URL` no `.env` — provisionar ou o
   passo de migration falha (`set -u`).
4. **Frontend** deployado por `git archive HEAD`→tar→scp→extração (não há remote git vivo), depois
   `docker compose up -d --build` (reconstrói backend+frontend a partir do source em disco).

**Verificação (API/infra):** openapi com `/empresa`(3)+`/memberships`; `/empresa` sem auth → 401 (sem 500);
rotas `assinaturas`/`empresa` compiladas no container; containers healthy; head `0014` + 7 colunas + GRANT.
**Smoke test no browser (prod, org 1):** ✅ `/admin/empresa` e `/admin/assinaturas` renderizam com dados reais
(org/unidade/horários/plano+uso); **write round-trip** validado (PATCH `legal_name` persistiu e foi revertido p/
NULL — confirma o mapeamento "string vazia→NULL" e que `name` não é afetado).
**Nota de harness:** `form_input` (extensão Chrome) seta o DOM mas **não dispara o `onChange` do React**, então o
campo não fica "dirty" e o PATCH não inclui o valor — usar **digitação por teclado** (`type`) para exercitar saves.

---

### D-47 — Consumo de pacote (usar mensalidade) na UI: card + Agenda

**Data:** 2026-06-27 (5ª sessão)
**Contexto:** o backend de mensalidade (D-44) já tinha `consume_membership` + endpoint
`POST /memberships/{id}/usos` (1 uso = combo inteiro: 1 horário + 1 profissional por serviço), mas **não
havia opção na UI** para utilizar o pacote. Pendência registrada em D-44/CURRENT_SPRINT.

**Decisão:** expor o consumo em **dois lugares** (escolha do usuário), **reusando um único diálogo**:
1. **Card da assinatura** (`/admin/assinaturas`): botão **"Usar pacote"** no `MembershipCard` → `UsePackageDialog`
   (data/hora + um profissional por serviço do combo) → `useConsumirPacote` (`POST /usos`). Desabilitado quando
   inativa / sem saldo / sem combo.
2. **Agenda** (novo agendamento): ao selecionar um cliente com **assinatura ativa e saldo**
   (`useClienteAssinaturas`), aparece um banner **"Usar pacote"** que abre o **mesmo** `UsePackageDialog`
   (pré-preenchido com a data/hora do formulário); ao consumir, fecha o diálogo de novo agendamento.

**Design:** sem backend novo — só frontend. `useConsumirPacote` invalida `["membership-cliente"]` **e**
`["agenda"]` (o consumo cria o agendamento do combo). Barbeiros: lista todos os ativos por serviço e confia na
validação do backend (422 se o profissional não executa o serviço) — não há endpoint "barbeiros por serviço".
`UsePackageDialog` ganhou props `initialStart`/`onConsumed` para o reuso na Agenda.

**Arquivos (frontend):** `hooks/use-assinaturas.ts` (`useConsumirPacote`), `components/assinaturas/use-package-dialog.tsx`
(novo), `components/assinaturas/membership-card.tsx`, `components/agenda/novo-agendamento-dialog.tsx`.
Commits frontend `877a957` (card) + `884d6cf` (agenda).

**Verificação:** `tsc`/`eslint`/`build` limpos (21 rotas). **Contrato validado end-to-end** contra o DB de staging
(login→criar plano→vender→`POST /usos` com o payload exato do frontend → 201, agendamento criado, saldo 2→1).
**Deploy:** ✅ ambas as etapas em prod 2026-06-27 (frontend-only, sem migration). **Pendente:** demo visual no
browser (prod não tem assinaturas vendidas ainda — recurso fica dormente até o cliente cadastrar planos/vender).

---

### D-48 — Assinatura: pacotes personalizáveis por cliente + usar sem agendar + combo do catálogo restrito

**Data:** 2026-06-27 (6ª sessão)
**Contexto:** três pedidos da operação sobre a mensalidade (D-44/D-47): (1) o consumo obrigava marcar
data/hora futura + profissional por serviço e sempre criava um agendamento novo; (2) faltava montar
pacotes **sob medida por cliente**; (3) "cada uso deve dar direito a 1 serviço: corte, barba ou
corte+barba".

**Decisão e implementação:**
1. **Pacotes personalizáveis por cliente.** `client_memberships.plan_id` agora **nullable** (migration
   `0015`, ORM Optional). Venda generalizada em `create_membership(spec)` que monta o snapshot a partir
   de uma spec (combo/usos/preço/duração) **com ou sem plano de base** — catálogo (com override) e
   personalizado do zero convergem. `unit_recognized_value` **sempre recomputado** da spec final.
   `sell_membership` virou wrapper. **Renovação** (`renew_membership`) passou a **clonar o snapshot da
   própria assinatura** (preserva personalização, funciona sem plano).
2. **Usar pacote sem agendar.** Helper compartilhado `apply_membership_to_appointment` (baixa 1 uso +
   reprecifica os itens + grava `MembershipUsage`), com dois pontos de entrada: **(a)** `POST
   /memberships/usos/attach` (anexa a um agendamento existente, fica `agendado`); **(b)** no **checkout**
   — `ConcluirRequest.membership_id`/`usar_assinatura` aplica o uso e conclui na **mesma transação**
   (atômico). **Avulso "usar agora":** `ConsumeIn.start_at` opcional (default agora) + a UI encadeia a
   conclusão. Reusa o caminho canônico (`usage_for_appointment`→conclusão sem `Payment`→`revert_usage`).
3. **Combo do catálogo restrito** (`validate_combo_shape`): plano só pode ser corte (`cabelo`), barba,
   `combo`, ou exatamente corte+barba — sem química/estética/combos arbitrários. Aplica **só** em
   `criar_plano`/`atualizar_plano`; **pacote personalizado tem combo livre**. `AppointmentOut` ganhou
   `client_id` (gate da opção "usar assinatura" no checkout; oculto p/ não-próprios).

**Design:** sem mudança em consumo/estorno/expiração/financeiro/fidelidade/bot (tudo lê o snapshot, não
o plano). Helpers DRY extraídos: `_decrement_balance`, `_combo_matches`. UI de venda reescrita como
**formulário único adaptativo** (escolher plano só preenche; combo livre; "valor por uso" ao vivo).
Checkout: diálogo Concluir ganhou alternância **Pagamento / Usar assinatura** (gate por assinatura ativa;
combo validado no backend). Decisão: **não** adicionar botão de attach avulso em `appointment-actions`
(redundante com o checkout; endpoint `/usos/attach` fica para uso futuro/n8n).

**Arquivos:** `alembic/versions/0015_*`, `models/membership.py`, `app/services/membership.py`,
`app/api/memberships.py`, `app/api/barbeiro.py`, `app/api/agenda.py`; frontend `types/index.ts`,
`hooks/use-assinaturas.ts`, `hooks/use-agenda.ts`, `components/assinaturas/{sell-membership-dialog,
plan-form-dialog,use-package-dialog}.tsx`, `components/agenda/concluir-dialog.tsx`.

**Verificação:** backend **252 pass / 1 skip / 3 falhas ambientais conhecidas** (n8n `bypass_hours`, RLS
isolation, e2e link — idênticas ao baseline); novos testes unit (`validate_combo_shape`/`_combo_matches`)
+ integração (venda custom/override, renovação custom, attach, checkout atômico, avulso, combo de catálogo
inválido). Frontend `tsc`/`eslint`/`next build` limpos (21 rotas).

**Deploy:** ✅ **produção 2026-06-27** (VM backend HEAD `693fa94`; frontend archive `7d8c88d`). Migration
`0015` aplicada (head=0015, `client_memberships.plan_id` nullable=YES) via `Dockerfile.migrate` com URL
admin **construída inline** do `.env` (POSTGRES_USER/PASSWORD/DB) — a VM **ainda não tem `ADMIN_DATABASE_URL`
no `.env`** (logo `deploy/update.sh` falharia na migração; rodei pull+migrate+`compose up --build` à mão).
Backups pré-deploy: `backups/predeploy_0015_*.sql` (DB) + `backups/frontend_src_*.tgz`. Containers healthy;
`/memberships/usos/attach`, `SellIn.combo_service_ids`, `ConcluirRequest.membership_id` no openapi live.
**Pendente:** adicionar `ADMIN_DATABASE_URL` ao `.env` da VM (p/ `deploy/update.sh` futuro) + demo no browser.

---

### D-49 — CRM/atendimento via Chatwoot (VM nova) + WhatsApp Cloud API; backend = sistema de registro

**Data:** 2026-06-27 (7ª sessão)
**Contexto:** o pedido inicial ("integrar Supabase ao Chatwoot p/ criar o CRM") embolava três decisões
distintas. Após esclarecer a motivação (multi-operador, omnichannel, sair da VM única, insatisfação com o
CRM custom e **Evolution quebrada**) e revalidar o D-41 (número restrito; conserto da Evolution **esgotado**,
testado até 2.4.0-rc2), a rota foi redesenhada.

**Decisões:**
1. **Chatwoot self-hosted em VM nova** assume Inbox conversacional + atendimento humano multi-operador
   (atribuição/transferência) + omnichannel (WhatsApp/Instagram/e-mail/site). **Aposenta as Fases 4/5/6** de
   `CRM_WHATSAPP_EVOLUCAO_ROADMAP.md` (Inbox 3 painéis, SSE, envio humano) — Chatwoot entrega isso pronto.
2. **WhatsApp via Cloud API oficial (Meta) + número novo dedicado.** Abandona Evolution/Baileys no fluxo do
   bot (alinhado ao D-41; Cloud API é nativo no Chatwoot). Lembrete/reativação (proativos >24h) exigem
   **templates aprovados**.
3. **Backend FastAPI/Postgres permanece o sistema de registro** — funil/Kanban, agenda, financeiro, clientes,
   assinaturas **não** migram. RLS multi-tenant continua sendo do backend (Chatwoot não tem RLS; hoje é org 1).
4. **Raquel (IA) vira Agent Bot do Chatwoot:** n8n acionado por webhook do Chatwoot, responde pela API dele;
   handoff bot↔humano nativo (substitui `clients.bot_paused`). Tools `/bot/*` preservadas.
5. **Supabase fora do escopo** — "Postgres gerenciado" é decisão de infra separada (avaliar depois: Supabase
   vs Cloud SQL vs Neon, com LGPD).

**Impacto no código (localizado):** saída = repontar `app/services/whatsapp.py::send_text` (hoje POST à
Evolution) p/ Graph API/Chatwoot; entrada = o parser Evolution de `app/api/wa_webhook.py` sai do caminho;
surge webhook novo Chatwoot→FastAPI (upsert lead/cliente + avanço de funil). Containers `evolution_*`
arquivados após cutover.

**Plano:** `CHATWOOT_CLOUD_API_ARQUITETURA.md` (visão + roadmap F0–F5) e
`CHATWOOT_FASE1_FASE4_SPEC.md` (provisionamento da VM/compose + contrato do webhook). **Status:** plano —
nada implementado. **Começar pela Fase 0** (Meta Business + número novo — gargalo externo de prazo).

---

### D-50 — Fidelidade por Pontos (Fase 2): ledger append-only + tiers/regras configuráveis — DEPLOYADO em prod

**Data:** 2026-06-28 (8ª sessão)
**Contexto:** a fidelidade existente era **snapshot-only** (nível derivado de visitas/gasto, enum fixo,
benefícios hardcoded) — sem ledger, sem configuração por org, sem resgate. A Fase 1 (PR #5) já tinha
prototipado o `MembershipAgent` points-driven no `AI Kernel/`. Esta fase leva o modelo para o backend +
frontend, **100% aditivo** (nivel/categoria e API legada preservados; drop só em cleanup futuro).

**Decisões (confirmadas pelo usuário):**
1. **Ladder único de pontos** (aposenta nível×categoria como eixo): tiers **Bronze 0 / Prata 150 / Ouro 500 /
   Diamante 1.000 / Black 2.000**, com desconto 0/5/10/15/20%.
2. **Pontos por R$ gasto + por visita**, configuráveis por org: default **1 pt/R$ + 10 pts/visita**.
3. **Resgate de pontos** gera voucher de crédito: default **1 pt = R$ 1**.
4. **Ledger append-only** (`loyalty_point_ledger`, CHECK `balance_after>=0`, earn idempotente por
   appointment via UNIQUE partial) é a fonte de verdade; `client_loyalty.points_balance`/`current_tier_id`
   são derivados.

**Implementação:**
- **Backend (PR #6 → `main`, merge `1896d53`):** migrations `0016_loyalty_points` (4 tabelas
  `loyalty_tiers`/`loyalty_rules`/`loyalty_vouchers`/`loyalty_point_ledger` + `client_loyalty.points_balance`/
  `current_tier_id` + RLS) e `0017_grant_loyalty_points` (GRANT ao `barber_app`). `app/services/loyalty.py`
  (seed lazy de tiers/regras, `recalculate` idempotente, `redeem_points`, `adjust_points`). `app/api/loyalty.py`
  (endpoints `/ledger`, `/points`, `/redeem`, `/vouchers`, `GET /tiers`, `GET|PUT /rules`).
  `scripts/backfill_loyalty_points.py` (idempotente, sem regressão de tier). 10 testes novos.
- **Frontend (commit local `d0cb7b9` no repo aninhado; remote morto → sem PR):** tela `/admin/fidelidade`
  (era placeholder) com abas **Clientes** (saldo/nível/próximo + extrato/ledger + vouchers + resgate/ajuste)
  e **Configuração** (regra + ladder). `hooks/use-loyalty.ts` + `components/loyalty/*`. Escopo restrito à
  tela (badges/filtro de Clientes e slice do Dashboard por tier ficam para um **PR-C** futuro, pois mexem em
  telas vivas + `clientes.py`/`dashboard.py`).

**Deploy em produção (2026-06-28):** PR #6 mergeado na `main`; VM `git pull`; migration `0015 → 0017`
aplicada (head `0017`) via container efêmero montando o código do host com credencial admin obtida do
container `barbeariapro-postgres` (sem expor segredo); `backfill` rodado (1 cliente, 0 piso); backend
rebuildado (`healthy`). Frontend deployado por scp+build (remote morto). **Smoke autenticado validado no
browser** (Augusto: 1.440 pts / Diamante / 560 p/ Black + extrato coerente; Configuração com defaults; sem
erros no console). Backfill **antes** de subir o código novo → sem janela de quebra (aditivo).

**Pendente:** PR-C (tier em Clientes/Dashboard); auditor adversarial (opcional); renovações automáticas,
`system_events`/`audit_logs`, integração Agenda↔checkout (consumir voucher) — fases futuras.

---

### D-51 — Assinatura: ferramentas de correção/reversão da recepcionista + endurecimento (auditoria do módulo)

**Data:** 2026-06-28 (8ª sessão)
**Contexto:** auditoria crítica multiagente do módulo Assinaturas (memberships) com verificação adversarial.
O módulo era **append-only sem caminhos de correção**: cancelar era irreversível e sem confirmação; "Usar
agora" consumia um pacote e concluía o atendimento de forma irreversível; não havia editar/excluir uma venda
errada; renovar gerava múltiplas assinaturas ativas; e a recepção (usuária principal) recebia **403 ao listar
o catálogo de planos** apesar de poder vender. Foco: tirar a recepcionista dos becos-sem-saída sem aumentar
risco de inconsistência. **100% aditivo e retrocompatível.**

**Decisões/implementação (escopo Tier 0+1+2; aprovado pelo usuário com "continue"):**
1. **Ferramentas de reversão (novos endpoints):** `POST /memberships/{id}/reativar` (desfaz cancelamento na
   vigência, se não houver outra ativa); `PATCH /memberships/{id}` e `DELETE /memberships/{id}` (corrige/remove
   venda **sem uso** — cliente/preço/combo/vigência); `PATCH /barbeiro/atendimento/{id}/estornar-uso` (estorna
   o uso de atendimento **concluído** pago por assinatura: cancela o atendimento, devolve o saldo do pacote,
   **reverte os pontos de fidelidade** — `reverse_appointment_points`, lançamento `reversal` no ledger — e
   recalcula o snapshot). Fecha os traps T1–T8. *(A reversão de pontos foi um bug pego pela revisão
   adversarial: `recalculate` só credita; sem a reversão, o `earn` ficava no ledger e inflava saldo/tier.)*
2. **Invariante ≤1 ativa por cliente:** `renew_membership` encerra a anterior (`vencida`); auto-pick de
   assinatura (checkout/attach sem `membership_id`) retorna **409** quando há múltiplas ativas, exigindo escolha.
3. **Concorrência/consistência:** `revert_usage` reescrito como UPDATE atômico com RETURNING (sem
   double-decrement); `_load_appointment` com `FOR UPDATE` (impede Payment duplicado na conclusão em dinheiro);
   `IntegrityError` da unicidade de uso → **409 limpo**; índice único **parcial** (`reverted_at IS NULL`) p/
   permitir re-vínculo após estorno (migration `0018`).
4. **Auditoria:** `client_memberships.canceled_by_user_id` + `membership_usages.reverted_by_user_id` (migration
   `0018`, FKs `SET NULL`).
5. **Estado derivado:** leitura mostra `vencida` quando `end_at<=now` mesmo sem o cron (fim do limbo
   "ativa-vencida").
6. **RBAC:** recepção passa a **listar planos ativos** (vender já era `full_access`); criar/editar/arquivar
   plano e listar arquivados seguem `manager`.
7. **UX (frontend, só a tela `/admin/assinaturas`):** confirmação inline + feedback de erro em
   Cancelar/Renovar/Excluir; botão **Reativar** no histórico; aviso ao vender com assinatura vigente;
   confirmação no "Usar agora". Sem lib de toast nova (padrão de erro inline do app).

**Migrations:** `0018_membership_corrections` (aditiva) — `down_revision=0017`. **DEPLOYADO em produção
2026-06-28** (PR #8 → `main` `dc64e5c`; head `0018`; backup `predeploy_0018_*.sql`; backend+frontend
rebuildados `healthy`; endpoints novos no openapi; smoke sem-auth 401). A VM não tem `ADMIN_DATABASE_URL` no
`.env` — migration rodada via imagem `Dockerfile.migrate` com URL admin construída do password do container
`barbeariapro-postgres` (superuser `postgres`).
**Testes:** `tests/test_membership_corrections.py` (10 novos, todos verdes); suíte **289 pass / 3 falhas
ambientais pré-existentes** (provadas pré-existentes via `git stash`). Frontend: `tsc --noEmit` limpo e lint
sem problemas nos arquivos do módulo.
**Fora de escopo (Tier 3, plano próprio):** pausar/reativar (estado `pausada`), trocar de plano com crédito
proporcional, renovação automática (cron), reembolso no cancelamento, expiração multi-org, registro de caixa
na venda + separação "receita reconhecida × recebido".

---

## D-52 — Tools de Gestão ("Agente Gestor"): Fase A (fundação + financeiro/ranking) — 2026-06-28

**Contexto:** o sistema atendia bem a Raquel (recepção/operação), mas faltava uma camada para o
**Gestor/dono** — quem decide (faturamento, produção por barbeiro, o que está vazando). Visão do produto
(CLAUDE.md §3) prevê "funcionária virtual" por linguagem natural via *tools* REST. Plano completo em
`/Users/apleandro/.claude/plans/a-humming-pond.md`.

**Decisão de arquitetura:** **1 camada de cálculo, 3 apresentações.** Toda a lógica vive em
`app/services/management.py` (funções `async (db, ...)` sob RLS), consumida por:
- **Bot (pull):** `/bot/gestor/*` — `X-Bot-Token` + gating por telefone do remetente. Org fixa
  (`settings.bot_organization_id`). O AI Agent (n8n) chama `whoami` primeiro.
- **Dashboard (JWT):** `/admin/gestor/*` — `get_tenant_db` + `require_manager_access` (recepção fora).
- **Cron (push):** previsto na Fase C (`/internal/gestor/*` + `send_text`).

**Gating por telefone (escolha do usuário):** cruza o telefone do remetente com a role do `User`.
`User`/`Barber` **não tinham telefone** → migration **`0019_gestor_fields`** adiciona `users.phone_e164`
(+ índice parcial único por org) e `organizations.monthly_revenue_goal` (alerta futuro). Helper
`resolve_role_by_phone()` + `is_manager_role()`; toda tool sensível do bot recheca (defense-in-depth).

**Reuso (não reescrever):** `_barber_revenue_rows` saiu de `financeiro.py` para
`management.barber_revenue_rows` (financeiro passou a importar — sem regressão). `local_date`/`today_local`,
`resolve_role`, `normalize_phone` reaproveitados.

**Entregue (Fase A):** `whoami`, `financeiro` (receita/comissões/despesas/líquido), `ranking` (receita/
ticket médio/comissão) nos canais bot + dashboard. **Despesas** seguem a competência mensal já adotada
(`Expense.competence_month`) — `net` é pleno em janela de mês fechado.
**Migration `0019` aplicada no staging** (via superuser `postgres`; o owner das tabelas é `barber_owner`,
e o usuário do app não é dono — DDL exige superuser/owner).

**Entregue (Fase B):** `inativos` (status fidelidade ou `days`) + `inativos/disparar` (reusa
`reactivation.run` — cooldown/opt-out/trava de envio); `buracos` (janelas ociosas/barbeiro via
`BusinessHours` − agendamentos − folgas, corta o passado se hoje); `ia-faturamento` (`booking_channel=
whatsapp` concluídos + leads fora do horário comercial); `mrr` (`price_paid/duration_days×30` das ativas +
vencendo em 30d). Helper puro `_free_windows`. Tudo nos canais bot + dashboard.

**Entregue (Fase C — push proativo + UI):** `app/services/gestor_notify.py` monta o texto pt-BR e envia via
`send_text` aos `manager_phones` (owner/manager com telefone). Endpoints internos (cron, X-Bot-Token):
`POST /internal/gestor/resumo-diario` (`daily_digest`: faturamento/atendimentos/topo/faltas/IA + ociosidade
de amanhã) e `POST /internal/gestor/alertas` (`revenue_alerts`: projeção do mês vs `monthly_revenue_goal` +
queda vs média semanal). Meta cadastrável via `PATCH /empresa` (`organizations.monthly_revenue_goal`). Crons
documentados em `docs/GESTOR_CRON_N8N.md` (não editar `workflows.json` local — diverge da VM).
**Frontend:** página `/admin/gestor` (Next.js) com `SegmentedControl` de período + `GestorKpis` (receita/
comissões/líquido/atend./MRR/IA), `RankingPanel`, `InativosPanel` (com botão Disparar via mutation) e
`BuracosPanel`; React Query (`hooks/use-gestor.ts` + `useAuthedQuery`/`AsyncState`), item "Gestor" no menu
GESTÃO. `tsc --noEmit` 0 erros + eslint limpo.

**Testes:** `tests/test_gestor_unit.py` (período/role/free_windows/builders, 15) +
`tests/test_gestor_integration.py` (dashboard RBAC, gating do bot, regressão `financeiro mes ==
/financeiro/mensal`, endpoints internos, 16). Suíte **320 pass / 2 skip / 3 falhas ambientais
pré-existentes** (bypass_hours, RLS isolation, e2e — não são bugs). Envio/disparo **não** é exercido em teste
(evita WhatsApp real; sem telefone de gestor no seed, `sent=0`).

**Pendente (deploy):** aplicar migration `0019` na VM; popular `users.phone_e164` do(s) gestor(es) (tela
`/admin/usuarios` é placeholder); cadastrar `monthly_revenue_goal`; criar os 2 crons no n8n; mergear/deployar
o frontend. Evolução: gating de role no menu/rota do frontend; seleção pontual de clientes no disparo.

---

## Dívida técnica conhecida (não resolver sem discussão)

| Item | Arquivo | Severidade | Observação |
|---|---|---|---|
| Sem backup dos volumes Docker da VM | infra VM | ⚠️ Alto | VM ficou TERMINATED em 2026-06-25 |
| ~~Debug print temporário no webhook~~ | `app/api/wa_webhook.py` | ✅ Resolvido | D-40: trocado por `logger.debug` (commit `13822a1`) |
| Bot responses não confirmadas no CRM | fluxo n8n + Evolution | ⚠️ Alto | Pendente confirmação end-to-end |
| ~~Frontend sem remote git funcional~~ | `barbearia-frontend/.git` | ✅ Resolvido | 2026-06-29: remote movido p/ `augustopegoraro-droid/barbearia-frontend` (privado) + submódulo registrado (`.gitmodules`). Resíduo: bumpar ponteiro após merge do frontend |
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
| ~~Migrations 0012–0014 + telas novas não deployadas~~ | VM / `barbearia-frontend` | ✅ Resolvido | D-46 (2026-06-27): 0012/0013 já estavam; 0014 aplicada; `/admin/assinaturas`+`/admin/empresa` deployadas. Falta só smoke test visual. |
| `ADMIN_DATABASE_URL` ausente no `.env` da VM | `/opt/barbeariapro/.env` | Médio | Só nos `.example`; `deploy/update.sh` quebra no passo de migration (`set -u`). Provisionar p/ deploy automatizado (D-46). |
