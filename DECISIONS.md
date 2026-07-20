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
**Ponteiro do submódulo:** bumpado para `8ba47e1` (main do frontend pós-merge do PR #1,
já com a tela do Gestor) em 2026-06-29.
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

**✅ DEPLOYADO em produção 2026-06-29:** backend em `fefd316` (container healthy; 7 rotas `/admin/gestor/*`,
8 `/bot/gestor/*`, 2 `/internal/gestor/*` no openapi; gating 401); migration `0019` aplicada (head=`0019`,
2 colunas novas) via URL admin inline após `pg_dump` pré-deploy (`backups/predeploy_0019_20260629_154543.sql`);
frontend deployado (archive→scp→build; `/admin/gestor` responde 307; container healthy); `users.phone_e164`
gravado p/ Taylor (`+5563984566177`) e Thedy (`+5563999663695`). Pin da Evolution no `docker-compose.yml`
preservado (stash/pop).

**Pendente:** cadastrar `monthly_revenue_goal` (tela Empresa) + criar os 2 crons no n8n (`docs/GESTOR_CRON_N8N.md`)
— ambos opcionais e independentes. Evolução: gating de role no menu/rota do frontend; seleção pontual de
clientes no disparo. Smoke visual logado em prod pende (precisa do login do gestor).

---

### D-53 — WhatsApp: envio bloqueado por aparelho conectado (companion); número vira receive-only — 2026-06-29

**Contexto:** pedido de trocar Evolution → serviço Baileys próprio. Antes de construir, rodou-se o gate de
envio (Fase 0 do plano `~/.claude/plans/a-humming-pond.md`). Refina o **D-41**.

**Achados:**
- `send_text` para 2 destinatários distintos (Taylor `+5563984566177`, Augusto `+5563999368196`): `sent=True`
  (Evolution aceita) mas **nenhum recebeu**.
- **Sinal novo decisivo:** o **app do WhatsApp no celular do `5563920001734` envia normalmente** → a conta **não
  está banida**. A restrição é específica de **envio por aparelho conectado (companion/linked device)**.
- **Re-pareamento limpo testado** (`DELETE /instance/logout/Barbearia` → `state:close` → QR novo escaneado →
  `state:open`): recebimento voltou, mas o envio **continua** falhando com `Closing session/pendingPreKey/status:ERROR`
  na sessão **nova** → não é sessão corrompida, é flag de conta.
- **Implica que Baileys NÃO resolve neste número** — Baileys é companion (mesmo protocolo multi-device da Evolution),
  cai na mesma trava. (Gate barrou a construção antes de gastar dias.)

**Decisão (gestor):** usar `5563920001734` **só para RECEBER** por ora (Inbox/CRM inbound segue via Evolution, que
foi religada no re-pareamento). **Plano Baileys PAUSADO.** Retomar **só com número NOVO**; recomendação reforçada:
**Cloud API oficial** sobre Baileys (Cloud API não é companion → sem a trava; Baileys em número novo corre risco de
ser flagado de novo — provável origem do problema atual).

**Impacto no Gestor (D-52):** dashboard web `/admin/gestor/*` funciona 100% (não usa WhatsApp). Bot WhatsApp
`/bot/gestor/*` e push (`resumo-diario`/`alertas`) **não entregam** neste número (precisam enviar) — só com número novo.

---

### D-54 — Multi-tenant real: org_id deixa de ser hardcoded (subdomínio → org no login; instância WhatsApp → org no bot) — 2026-06-29

**Contexto:** o `org_id` estava fixo em build (`NEXT_PUBLIC_ORG_ID` no frontend) e em config (`settings.bot_organization_id`
no bot) — dívida que bloqueava a expansão SaaS multi-tenant. RLS + `organization_id` nas tabelas já existiam (fundação OK).
Auditoria do estado atual: o **JWT já carregava `org`** e **toda request autenticada já lia o org do token** (`get_tenant_db`)
— itens 1 e 2 do pedido já estavam feitos. As `management.py` **não usam `settings`**: operam sob RLS (org vem da sessão);
adicionar `org_id` como parâmetro seria redundante e poderia furar o isolamento — mantido sob RLS (item 4 reinterpretado).

**Decisões (gestor):**
- **Bot → org pela INSTÂNCIA WhatsApp** (não pelo telefone do remetente: `phone_e164` não é único → ambíguo e furaria a RLS).
- **Login → org pelo SUBDOMÍNIO** (`taylor.app.com` → org); `NEXT_PUBLIC_ORG_ID` vira só fallback de dev (localhost).

> ✅ **DEPLOYADO em produção 2026-06-30** (PRs #12/#2 mergeados em `main`; head prod `0021`; org 1 backfillada `taylor`/`Barbearia`). Procedimento operacional em `PROJECT_CONTEXT.md §0.0000`.

**Implementação:**
- **Migration `0020`** (head): `organizations.subdomain` + `organizations.wa_instance_name` (TEXT, únicos via índice parcial
  quando não-nulos) + 2 funções `SECURITY DEFINER` (`app_org_id_by_subdomain` / `app_org_id_by_wa_instance`) que resolvem
  a org **antes** de saber o tenant (RLS bloquearia um SELECT sem `app.current_org_id`) e devolvem **só o `id`** (sem vazar
  linha). `GRANT EXECUTE` ao `barber_app`.
- **`app/services/tenant.py`** — wrappers async dessas funções (sessão pré-tenant).
- **`GET /auth/tenant?subdomain=`** (público) → `{organization_id, name}`; 404 se desconhecido. O frontend chama antes do login.
- **Bot multi-tenant via header `X-Instance`** (n8n envia): `get_bot_db` resolve org/unidade pela instância e expõe via
  `get_bot_org_id`/`get_bot_unit_id`; `bot.py`/`loyalty.py`/`reminders.py` passaram a injetar esses valores em vez de ler
  `settings`. **Fallback:** instância sem mapeamento (ou sem header) → `settings.bot_organization_id`/`bot_unit_id` →
  comportamento atual de prod **inalterado** até o backfill.
- **Frontend** (`lib/tenant.ts` + `lib/auth.ts`): `authorize` resolve o `organization_id` do subdomínio do host via
  `/auth/tenant`; sem tenant resolvido o login falha (não cai em org default). `NEXT_PUBLIC_ORG_ID` só fallback de dev.
- **`SEED_ORG_ID`** (item 6): default dos testes 3 → **1** (casa com o seed real do staging, org 1); env só de teste.

**Testes:** `tests/test_tenant_resolution.py` (6 testes: `/auth/tenant` ok/case-insensitive/404, funções SECURITY DEFINER,
bot via `X-Instance` + fallback). Baseline preservado: **326 pass / 2 skip / 3 fail** (as 3 ambientais de sempre).

**Pós-deploy — pendente (não bloqueia o que está no ar):** configurar **DNS de subdomínios** (registrador; domínio ainda
não registrado); fazer o **n8n enviar `X-Instance`** nas chamadas `/bot/*` (só necessário ao entrar a 2ª org — hoje a
instância `Barbearia` mapeia org 1 = idêntico ao fallback `settings`). **Fora de escopo (single-tenant via settings ainda):**
`chatwoot.py` (D-49, inerte) e o cron de reminders/reactivation por org única — viram multi-tenant quando o n8n iterar orgs.

---

### D-55 — Painel de Plataforma (Superadmin): camada ACIMA dos tenants, cross-tenant — 2026-06-29

**Contexto:** falta a camada do dono do SaaS — gerenciar todas as orgs (onboarding,
billing, suspensão, indicadores consolidados) sem ser limitado pela RLS. Construído
sobre `feat/multi-tenant-org-id` (D-54), na branch `feat/platform-superadmin`.

**Restrições decisivas (exploração):** `barber_app` é **NOBYPASSRLS** e a VM **não tem
`ADMIN_DATABASE_URL`** → em runtime, SELECT cross-org dá 0 linhas e o app não cria org
sob RLS. Único bypass disponível: funções **`SECURITY DEFINER`** (molde D-54/`0020`).

**Decisões (gestor):** (1) auth do superadmin por **password_hash bcrypt**; (2) cross-tenant
**híbrido** (SECURITY DEFINER para listagem/contagens; `mrr()` reusado iterando orgs em
**sessões helper isoladas** — endpoint nunca seta `app.current_org_id`); (3) **backend
completo agora; frontend `/superadmin` separado depois**.

> ✅ **DEPLOYADO em produção 2026-06-30** (PR #13 mergeado em `main`; head `0021`). Superadmin criado:
> `augustopegoraro.apl@gmail.com` (senha é segredo). Acesso **API-only** (`POST /platform/auth/login`); frontend `/superadmin` pendente.

**Implementado (head `0021`):**
- Migration `0021`: tabela `platform_admins` (global, sem `organization_id`, **sem RLS**,
  **sem GRANT a `barber_app`**) + funções `SECURITY DEFINER` (`app_platform_admin_login`,
  `_admin_exists`, `_list_orgs`, `_active_org_ids`, `_usage`, `_create_org`) com
  `GRANT EXECUTE TO barber_app`.
- `models/platform_admin.py`; `app/core/security.py::create_platform_token` (`typ="platform"`,
  sem `org`); `app/services/platform.py` (wrappers); `app/services/onboarding.py`
  (`provision_org` + `SERVICES_CATALOG` extraído do `seed.py`, que passou a importá-lo);
  `app/api/platform.py` (guard `require_platform_admin` + endpoints
  `auth/login`, `orgs` GET/POST/PATCH/`suspend`/`reactivate`, `dashboard`); registrado em
  `main.py`. Bootstrap: `scripts/seed_platform_admin.py` (role dona).
- **Isolamento bilateral de token:** tenant↔plataforma se rejeitam mutuamente (presença
  de `org` vs `typ`). Suspensão = `organizations.deleted_at` (não há status "suspended" no
  enum `subscription_status`; "suspenso" é derivado de `deleted_at`).

**Testes:** `tests/test_platform.py` (6): sem token 401, token de tenant→401, login+lista,
onboarding cria org+owner+seed (owner novo loga) + suspend/reactivate (com purge),
dashboard MRR consolidado. Baseline **332 pass / 2 skip / 3 fail** ambientais.

**Fora de escopo / pendente:** frontend `/superadmin` (app Next.js separado — exigência:
nunca no frontend de tenant); saúde de bot ao vivo (Evolution API; hoje só proxy
`wa_instance_name`); deploy prod (provisionar `ADMIN_DATABASE_URL` na VM, aplicar `0021`,
rodar bootstrap do superadmin).

**Pós code review (correções aplicadas):**
- **Suspensão agora é efetiva:** `/auth/login` recusa org com `deleted_at` (403). Antes a
  suspensão era cosmética (RLS de `organizations` não filtra `deleted_at` e o login por
  `organization_id` não passa pela resolução de subdomínio). Tokens já emitidos expiram
  naturalmente (limitação aceita).
- **Dashboard — dois MRR distintos:** `saas_mrr` (soma de `Plan.price_month` das assinaturas
  ativas = receita do SaaS) **e** `tenants_membership_mrr` (soma de `mrr()` = mensalidades dos
  clientes finais, volume que passa pelos tenants). Antes só havia o segundo, rotulado como se
  fosse a receita do SaaS. `app_platform_list_orgs` passou a expor `plan_price_month`.
- Robustez: `create_org` mapeia só `IntegrityError`→409 (resto propaga, sem vazar SQL);
  `patch_org` valida plano (400 se inexistente, evita 500 na FK); loop de MRR isola por org
  (um tenant ruim não derruba o painel); `_set_org_deleted` via ORM (sem f-string SQL);
  contagens do dashboard reusam `_derive_status` (fonte única de status).

**Limitações conhecidas (débito, não bloqueante):** funções `SECURITY DEFINER` de plataforma
têm `GRANT EXECUTE` a `barber_app` (o app tem só esse role) — a barreira é o guard HTTP
`require_platform_admin`; endurecer com role de plataforma dedicado é trabalho futuro.
Dashboard/`_get_org_out` fazem O(N) round-trips (agregação via função `SECURITY DEFINER`
quando a base crescer).

---

### D-56 — Frontend do Superadmin: repo/app separado + deploy preparado (sem ativar) — 2026-07-01

**Contexto:** a D-55 deixou o backend do painel de plataforma completo em prod (API-only) e
o frontend `/superadmin` como pendência explícita ("app Next.js separado — nunca no frontend
de tenant"). Pergunta do dono: para o domínio separado do superadmin, precisa de VM nova?

**Decisões:** (1) **não precisa VM nova** — domínio ≠ servidor; o backend já é compartilhado,
a separação superadmin↔tenant é lógica (token `typ=platform`, `platform_admins`, SECURITY
DEFINER). Subdomínio via DNS + nginx na **mesma VM**. (2) Frontend em **repo git novo**
(escolha do dono), não submódulo do frontend nem pasta no monólito. (3) Compra de domínio =
**um** domínio raiz (`taylorethedy.com`); todos os subdomínios (`admin`, `taylor`, `app`, `api`)
são grátis. Cloudflare Registrar (preço de custo). O domínio destrava também HTTPS (Let's
Encrypt) e o DNS de subdomínios da D-54.

**Implementado (buildável/rodável hoje, contra a API de prod):**
- Repo **`augustopegoraro-droid/barbearia-superadmin`** (privado) — Next 16 · TS strict ·
  Tailwind v4 · next-auth v5 · React Query · axios · lucide. Tema dark + brand amber. Porta dev
  **3100**. Guard via `proxy.ts` (convenção Next 16). **Sem** lógica de org/subdomínio.
- Auth: Credentials → `POST /platform/auth/login`; token `typ=platform` na sessão.
- Telas: `/login`, `/dashboard` (`GET /platform/dashboard` — contagens, `saas_mrr`,
  `tenants_membership_mrr`, uso por tenant), `/tenants` (listar + suspender/reativar + editar
  `PATCH`), `/tenants/new` (onboarding `POST /platform/orgs`).
- Adicionado como **submódulo** do backend em `./barbearia-superadmin` (2º submódulo, ao lado
  de `barbearia-frontend`).

**Deploy preparado (SEM ativar — nada muda em prod):**
- `docker-compose.app.yml`: serviço `superadmin` (:3100) sob **profile `superadmin`** → o `up`
  padrão é idêntico; só sobe com `--profile superadmin`. `Dockerfile` multi-stage (espelha o do
  frontend) validado (imagem builda + serve).
- `deploy/nginx.conf`: server block `admin.taylorethedy.com` → `:3100`.
- `.env.superadmin.example` (`AUTH_SECRET`, `API_URL_INTERNAL`, `AUTH_TRUST_HOST`) + exceção no
  `.gitignore`.

**Ativação futura (pós-compra do domínio, mesma VM):** DNS `admin.taylorethedy.com` → IP →
`docker compose -f docker-compose.app.yml --profile superadmin up -d --build superadmin` →
`certbot --nginx -d admin.taylorethedy.com --redirect`.

**Verificações:** `npm run build` ✅ · `docker build` ✅ · container serve (`/login` 200, `/`→
307 login) ✅ · YAML do compose ✅ · submódulo no SHA certo ✅.

**✅ ATIVADO em prod (2026-07-05, pós-D-64):** domínio já respondia via nginx+TLS (502
esperado); faltava só subir o container. Submódulo nunca tinha sido de fato clonado na VM
(pasta `barbearia-superadmin` existia vazia). Deploy key SSH somente-leitura nova
(`bsuperadmin_deploy`, ED25519) criada na VM + alias `github-bsuperadmin` em
`/root/.ssh/config`, no mesmo molde do `bfrontend_deploy`; chave pública registrada no repo
privado via `gh repo deploy-key add` (o link direto de Settings→Deploy keys deu 404 porque a
sessão do navegador estava logada numa conta GitHub diferente da dona do repo — resolvido
usando a `gh` CLI local, já autenticada como a conta certa, com autorização explícita do
dono). URL do submódulo sobrescrita via `git config submodule.barbearia-superadmin.url`
(SSH, sem tocar `.gitmodules`) → `git submodule update --init` clonou o commit `2fec4b7`.
`.env.superadmin` (existia mas vazio desde 1º/jul) preenchido: `AUTH_SECRET` gerado com
`openssl rand -base64 32` direto na VM (nunca exposto), `API_URL_INTERNAL`,
`AUTH_TRUST_HOST=true`, permissões `600`. Subida com `SUPERADMIN_API_URL=https://api.
taylorethedy.com` (o build embute essa URL em `NEXT_PUBLIC_API_URL`; o default
`localhost:8000` não serve para chamadas client-side do browser em produção). Efeito
colateral sem incidente: o compose recriou também o `backend` (build compartilhado no bake),
voltou `healthy`. **Validado:** `https://admin.taylorethedy.com` → `307` para `/login` com
cookies do next-auth (`__Host-authjs.csrf-token`, `__Secure-authjs.callback-url`); containers
`superadmin` e `backend` `healthy`; logs do superadmin limpos (`✓ Ready`).

---

### D-57 — Gestão inteligente de equipe: folha × receita recorrente + Kernel IA navegador — 2026-07-02

**Contexto:** doc `gestaointeligente/Estrategia_Transicao_Receita_Recorrente_BarbeariaPro.md` —
reduzir a dependência dos sócios via assinaturas (MRR) e responder: *a receita recorrente cobre
a folha? cabe contratar? qual modelo de trabalho usar (CLT/MEI/comissionado/aluguel de
cadeira/híbrido)?* Também: o gpt-4o-mini **alucinava** respondendo números no chat do Kernel IA.

**Decisões:**
1. **Kernel IA vira NAVEGADOR (anti-alucinação):** não responde dados — entende a intenção,
   escolhe UMA rota de um **catálogo fechado** (enum, filtrado por papel/RBAC), responde com
   mensagem **templada** ("Vou te encaminhar para X") e o frontend **redireciona**. O dado real
   aparece na página. Barbeiro: só a própria agenda + `solicitar_remarcacao_turno` (cria pedido
   pendente p/ o sino do gestor). Removidas as tools que devolviam números no chat.
2. **Modelagem de folha (migration `0025`, aditiva):** `barbers` += `work_model` (5 modelos do
   doc; NULL=comissionado), `monthly_cost` (custo fixo mensal total — salário+encargos no CLT)
   e `chair_rent` (aluguel que o profissional PAGA — receita). Comissão variável segue em
   `commission_pct`.
3. **Cálculo (`management.py`):** `payroll_summary` (fixo + comissões do período + aluguéis,
   por profissional/totais) e `recurring_coverage` — compara **MRR × folha fixa líquida**
   (comissões fora de propósito: autofinanciadas pela receita que as gera); devolve
   `covered`/`coverage_pct`/`surplus` (folga p/ contratação).
4. **Superfícies:** `GET /admin/gestor/folha` (gestor) · painel **"Folha × Receita recorrente"**
   em `/admin/gestor` (veredito verde/âmbar + tabela por profissional) · formulário de
   `/admin/equipe` configura modelo/custos · Kernel IA roteia as perguntas do doc p/ `/admin/gestor`.

**Validação (local, LLM real):** Pablo CLT R$2.500 + Sandra aluguel R$800 → folha fixa líquida
R$1.700; MRR R$0 → `covered=false`, "faltam R$1.700"; *"a receita recorrente cobre a folha?"* →
navega p/ `/admin/gestor`. Suíte **369 pass** / 2 fail ambientais.

> ✅ **Migrations `0024`/`0025` DEPLOYADAS em prod 2026-07-02** (head `0025`). Demais superfícies
> do D-57 (Kernel IA navegador, remarcação, painel de folha) seguem validadas em local/staging.

---

### D-58 — Agente financeiro no Kernel IA (grounded, sem reabrir a alucinação do D-57) — 2026-07-02

**Contexto:** pedido do usuário — um "agente de IA especialista em finanças de gestão de
barbearia" respondendo no chat do Kernel IA. Tensão direta com o D-57 (mesmo dia): o Kernel IA
tinha acabado de virar navegador puro porque o gpt-4o-mini alucinava números financeiros no chat.
Alinhado com o usuário antes de implementar: (1) grau de liberdade do LLM — relatório 100% fiel
aos dados + 1 frase de insight por cima (não recusar, nem responder livre); (2) fonte do insight —
playbook curado agora, heurísticas gerais de mercado, sem citação de fonte específica, editável
depois pelo usuário sem tocar em código.

**Decisões:**
1. **Grounding em vez de reversão do D-57:** o LLM continua proibido de calcular/inventar números.
   Ele só (a) escolhe, via function-calling de catálogo fechado (`consultar_financas`, enum
   `topico`+`periodo` — mesmo padrão do `navegar`), qual indicador buscar, e (b) gera 1 frase curta
   de insight — nunca o relatório em si.
2. **Bloco de dados 100% determinístico (`app/services/kernel_ia_finance.py`):** despacha pro
   `management.py` já existente (mesma fonte usada por `/bot/gestor/*` e `/admin/gestor/*`:
   `financial_summary`, `barber_ranking`, `mrr`, `payroll_summary`+`recurring_coverage`,
   `ai_generated_revenue`, `inactive_clients`, `agenda_gaps`) e formata em texto pt-BR — o LLM não
   toca nesses números.
3. **RBAC — `MANAGER_ACCESS`, não `FULL_ACCESS`:** a tool só existe para owner/manager. Corrige de
   passagem um gap: o catálogo de *navegação* do D-57 usava `FULL_ACCESS` (inclui `reception`), mas
   dados financeiros sempre foram `MANAGER_ACCESS` em `/admin/gestor/*` — recepção não deve ganhar
   `consultar_financas`. Coberto por teste de regressão.
4. **Guardrail numérico (defesa em profundidade):** a frase de insight (2ª chamada OpenAI, sem
   tools, temperature 0.3) passa por `kernel_ia_finance.guard_insight` — qualquer número citado que
   não apareça, verbatim, no bloco de dados real **nem** no playbook usado como referência, derruba
   a frase inteira (fail closed; o relatório de dados nunca é perdido, só o insight).
5. **Playbook curado (`app/data/finance_playbook.py`):** dict Python por tópico, heurísticas gerais
   de mercado para pequenos negócios de serviço (faixas de comissão, folha fixa vs. receita
   recorrente, janela de reativação, valor da ociosidade de agenda etc.), comentado como não sendo
   citação de fonte específica — editável livremente depois pelo usuário sem tocar em nenhum código.
6. **Contrato:** novo `action="finance_answer"` em `POST /kernel-ia/query`. Frontend
   (`kernel-ia-launcher.tsx`) não precisou de lógica nova (qualquer `action` ≠ `navigate` já só
   exibe o balão) — só `whitespace-pre-line` no balão do assistente (relatório multi-linha) e o tipo
   do `action` no hook.

**Validação:** suíte **396 pass** / 2 fail ambientais (mesmas do D-57: `bypass_hours` do workflow
n8n e o par hardcoded do teste e2e barbeiro↔serviço — nenhuma nova). 21 testes puros novos de
formatação/guardrail (`tests/test_kernel_ia_finance.py`) + testes de RBAC/dispatch fail-closed em
`tests/test_kernel_ia.py` (owner/manager ganham a tool; reception e barber não; dispatch nunca toca
o banco se o papel não autoriza).

> ✅ **DEPLOYADO em prod 2026-07-02** (backend `652fc2a` + frontend `5f35099`; sem migration nova —
> `0025` já era head). `docker compose up -d --build backend frontend` na VM; ambos containers
> `healthy`; `/kernel-ia/query` no openapi; bundle do frontend confirmado com o FAB (`grep -rl
> "Kernel IA" .next` no container). **Esta foi, na prática, a 1ª vez que o Kernel IA inteiro
> (D-57 navegação + D-58 finanças) chegou ao frontend de produção** — só as migrations do D-57
> tinham ido antes.
>
> ⚠️ **Bloqueado por chave OpenAI inválida em prod:** `OPENAI_API_KEY` da VM devolve 401
> (`invalid_api_key`) — confirmado invocando `kernel_ia.answer()` diretamente no container contra
> o org 1 real. Degrada com graça (`action=config`), sem erro 500, mas o chat não funciona para
> ninguém até a chave ser rotacionada em `/opt/barbeariapro/.env`. **A validação manual "LLM real"
> deste D-58 segue pendente** por causa disso — repetir os prompts de teste assim que a chave for
> corrigida.

---

### D-59 — Fechamento de caixa diário: histórico migrado da Trinks — 2026-07-02

**Contexto:** export `movimentacaofinanceira2026.csv` (Trinks) traz DUAS tabelas no mesmo
arquivo: (1) pagamentos por comanda (~3.688 linhas) — fora de escopo, exigiria casar/importar
agendamentos de jan-jun inteiros (só temos julho); (2) **"Resumo de Movimentação de Entradas e
Saídas"** — um fechamento por dia (abertura/recebido/troco/despesas/sangria/saldo), 149 dias
(05/01 a 02/07/2026). O sistema **ainda não tem módulo de Caixa** (abrir/fechar em tempo real —
`CLAUDE.md §6`); esta é só a migração do histórico, no mesmo molde de `client_debts` (D-56/0023).

**Decisões:**
1. **Tabela nova `cash_daily_closings`** (migration `0026`, aditiva): `organization_id` CASCADE +
   RLS + `UNIQUE(organization_id, closing_date)`. Colunas espelham o export: `opening_balance`,
   `cash_received`, `change_given`, `cash_expenses`, `cash_total`, `withdrawal` (sangria),
   `closing_balance`, `other_methods_received`, `other_methods_expenses`, `opening_history`.
2. **`app/services/trinks_cash_closing.py`** (parse puro + persistência), mesmo molde da
   `trinks_debts.py`: localiza a 2ª tabela pelo cabeçalho ("data" + "abertura do caixa"), ignora
   o rodapé "Total período" (1ª coluna vazia). **Upsert por `(org, dia)`** — idempotente, sem
   duplicar em re-importações (diferente de `client_debts`, que só pula duplicata).
3. **Superfícies:** CLI `scripts/import_trinks_cash_closing.py` (roda na VM, `--commit`) + rota
   self-service `POST /admin/import/trinks/cash-closing` (`app/api/imports.py`, dry-run padrão).

**Validação:** parser bateu 149/149 linhas com o arquivo real; soma de `cash_received` (R$
22.906,00) e `other_methods_received` (R$ 389.762,15) **conferem exatamente** com o rodapé "Total
período" do próprio relatório da Trinks. Rodar o import 2x atualiza (upsert), não duplica.
✅ **Aplicado em staging (org 1):** migration `0026` + 149 dias importados. Suíte **370 pass** /
2 fail ambientais (mesmas de sempre).

> ✅ **DEPLOYADO em prod 2026-07-02:** backup pré-deploy (`~/predeploy_d59_cash_closing_*.sql` na
> VM) + migration `0026` aplicada (head `0026`) + backend rebuildado (commit `0ae1470`) + CLI
> rodado com o arquivo real (org 1) — **149 dias importados**, totais conferindo com o relatório
> (mesmos R$ 22.906,00 / R$ 389.762,15). Containers `backend`/`frontend` healthy pós-deploy.

Fora de escopo desta entrada: importar a tabela 1 (pagamentos por comanda) e construir o módulo
de Caixa vivo (abrir/fechar em tempo real).

**Consumo dos dados (mesmo dia):** `GET /financeiro/caixa?month=` (`app/api/financeiro.py`) lista
os dias de `cash_daily_closings` do mês (mesmo guard de gestor dos demais endpoints de
`/financeiro`; mês sem dados devolve lista vazia). Frontend: card **"Histórico de caixa"** na
visão Mês de `/admin/financeiro` (`components/financeiro/caixa-historico.tsx`), tabela com
scroll interno + header fixo; estado vazio explícito para meses fora do período migrado.
✅ **DEPLOYADO em prod 2026-07-02** (backend commit `8514fb3`; frontend commit `72931b3` —
cherry-pick isolado sobre o `main` do submódulo, sem arrastar trabalho não relacionado de outras
branches em andamento). Validado ao vivo (local + prod): janeiro/2026 populado, agosto/2026 vazio.

---

### D-60 — Code review das migrations 0024/0025: CHECKs de integridade + guards de API (migration 0027) — 2026-07-03

**Contexto:** revisão multi-agente (8 subagentes em paralelo: Security, Backend, Database, RBAC,
Testing, Migration, Performance, Code Review — cada achado verificado lendo o arquivo real antes de
aceitar) das migrations **0024** (`appointment_reschedule_requests`, D-57) e **0025** (custos de
equipe em `barbers`, D-57). Como 0024/0025/0026 **já estão em prod → imutáveis**, a correção é uma
migration **nova (0027)**, aditiva (só constraints), sobre `down_revision="0026_cash_daily_closings"`.

**Achados corrigidos (4 CHECKs em 0027 + espelho no ORM — convenção do repo: constraint declarada
na migration E no `__table_args__`):**
- **F1 — período invertido:** `appointment_reschedule_requests` aceitava `period_end <= period_start`.
  CHECK `reschedule_period_order` (`period_start IS NULL OR period_end IS NULL OR period_end >
  period_start`, `>` estrito igual a TimeOff/Appointment/Membership; tolerante a NULL pois pedido do
  Kernel IA não traz datas) + `@model_validator` em `RescheduleCreateIn` (`app/api/reschedule.py`) →
  422 no request.
- **F3 — `source` sem CHECK:** 0024 só constrangeu `status`. CHECK `reschedule_source_valid`
  (`source IN ('app','kernel_ia')`) — paridade com o de status.
- **F5 — filtro `?status=` silencioso:** `GET /remarcacoes?status=` (vazio) caía num `[]` mudo em vez
  de "todos". Normalização em `listar_remarcacoes`: vazio/`todas`/`todos`/`all` → todos; valor do
  catálogo → filtra; qualquer outro → 422 (nunca `[]` silencioso).
- **F7 — custos de equipe sem CHECK:** `barbers.monthly_cost`/`chair_rent` (0025, colunas de dinheiro)
  não tinham `>= 0` — única migration de coluna monetária que quebrou a convenção (~30 CHECKs). CHECKs
  `barbers_monthly_cost_nonneg`/`barbers_chair_rent_nonneg`. A API (`BarberEditIn`/`BarberCreateIn`,
  `Field(ge=0)`) já barra; o DB é o backstop para writers fora da API (imports/scripts/onboarding) —
  protege o cálculo de folha/cobertura (`management.recurring_coverage`).

**Achados deferidos (decididos, não implementados):**
- **F2 — `GRANT ... ALL SEQUENCES` sem REVOKE no downgrade da 0024/0026:** **não mexer.** Consenso dos
  agentes de Security/Migration/Database: um `REVOKE ON ALL SEQUENCES` num downgrade revogaria grants
  de OUTRAS tabelas (o grant é schema-wide, idempotente). Nunca adicionar.
- **F4 — múltiplos pedidos `pendente` por barbeiro:** **intencional (confirmado pelo dono).** O barbeiro
  pode ter vários pedidos abertos para períodos diferentes. Sem índice único parcial / sem dedup. TODO
  registrado caso o produto queira 1-pendente-por-período no futuro.
- **F6 — `reviewed_at = func.now()` (relógio do DB) vs relógio da app:** **sem mudança.** Não há bug vivo;
  manter `func.now()` por consistência com o `server_default` de `created_at`.
- **F8 — `list_requests` sem `ORDER BY` determinístico:** ✅ **implementado 2026-07-03** (logo após o
  deploy da 0027; code-only, sem migration). `list_requests` já ordenava por `created_at DESC`, mas
  empates (inserts na mesma transação compartilham `func.now()`) ficavam com ordem indefinida — o sort
  do Postgres não é estável. Desempate por `id DESC` em `app/services/reschedule.py`; teste em
  `tests/test_reschedule_integration.py` insere 3 pedidos na mesma transação e exige id DESC.

**Cobertura de testes (motivador declarado: 0/100 → 90/100+):** `tests/test_reschedule_integration.py`
+7 (F1 invertido→422 / válido→201 / sem-período→201; F5 inválido→422 / vazio-traz-todos / filtra; F8
ordena id DESC no empate) e **fixture autouse de limpeza** (zera pedidos do tenant semeado antes/depois
de cada teste — os testes commitam sem rollback e acumulavam pendentes, tornando contagens
não-determinísticas; usa o GRANT DELETE do `barber_app` da 0024). `tests/test_gestao_equipe.py` +1
(F7 custo negativo→422).

**Validação (local/staging):** pré-audit dos 4 CHECKs = **0 violações** (todas as orgs, role admin);
0027 aplicada no staging (head `0027`); os 4 constraints existem e **rejeitam escrita inválida no nível
do DB** provado via `barber_app`/RLS (backstop independente do guard de app), aceitando o período válido;
`alembic check` **não acusa drift nos 4 constraints** (só o ruído pré-existente de 5 índices
parciais/de-expressão — limitação conhecida do autogenerate, tabelas não tocadas). Suíte: **408 pass /
2 fail ambientais** (as de sempre: `bypass_hours` do workflow n8n + e2e link barbeiro↔serviço — nenhuma
tocada por esta mudança) **/ 2 skip. 0 regressões.** (408 = 407 + o teste do F8.)

> ✅ **DEPLOYADO em prod 2026-07-03.** Migration head `0026 → 0027`, os **4 constraints presentes** em
> `pg_constraint`; backend rebuildado (F1/F5) e healthy; `/remarcacoes` responde 401 (viva + protegida).
> Runbook executado (o mesmo molde da D-54/D-55):
> 1. **Backup:** `pg_dump` → `backups/predeploy_d60_20260703_112029.sql` (585K).
> 2. **Pré-audit** (role `postgres`, todas as orgs) — os 4 counts abaixo deram **0** (tabela de
>    remarcação vazia: a feature D-57 nunca foi usada — coerente com a `OPENAI_API_KEY` inválida).
>    Crítico o `reschedule_period_order`: a API só passou a barrar período invertido com o F1 — se prod
>    tivesse linha invertida, o CHECK falharia o upgrade.
>    ```sql
>    SELECT count(*) FROM barbers WHERE monthly_cost < 0;
>    SELECT count(*) FROM barbers WHERE chair_rent < 0;
>    SELECT count(*) FROM appointment_reschedule_requests WHERE source NOT IN ('app','kernel_ia');
>    SELECT count(*) FROM appointment_reschedule_requests
>      WHERE period_start IS NOT NULL AND period_end IS NOT NULL AND period_end <= period_start;
>    ```
> 3. **`git pull`** na VM (`--ff-only`, sem recursar o submódulo do frontend) — traz 0027 + models +
>    `reschedule.py` (merge `c08aa94`, PR #17).
> 4. **Migration:** a imagem do backend **não copia `alembic/`** → montar o repo do host e conectar como
>    superuser. `PGPW` lido **na VM** (`docker exec barbeariapro-postgres printenv POSTGRES_PASSWORD`,
>    nunca inline), URL `postgresql+psycopg://postgres:…@host.docker.internal:5432/barbeariapro`, e
>    `docker compose -f docker-compose.app.yml run --rm --user root -v /opt/barbeariapro:/repo:ro -w /repo
>    -e DATABASE_URL="$URL" backend python -m alembic upgrade head`. (`env.py` lê `DATABASE_URL`; o
>    `postgres` superuser altera `barbers` mesmo pertencendo a `barber_owner`.) `ADMIN_DATABASE_URL`
>    segue **ausente no `.env` da VM** (dívida conhecida) → URL admin montada inline.
> 5. **Rebuild** do backend (`up -d --build backend`) para carregar os guards F1/F5.
> 6. **Verificado:** `alembic_version` = `0027_reschedule_and_cost_checks`; os 4 `conname` presentes.

---

### D-61 — Painel SuperAdmin completo + arquitetura de Billing (Stripe via BillingProvider) — 2026-07-03

**Status: ✅ DEPLOYADO EM PROD 2026-07-03 (commits `b849b10` backend / `2fec4b7` painel; migrations 0028–0034 aplicadas, head `0034`; backend rebuildado healthy; backup `predeploy_d61_20260703_165238.sql` na VM). Billing em `mock` até chaves Stripe (B-02); painel via localhost até domínio (B-01); criar cron do lifecycle no n8n (B-03).**

Missão autônoma executada de ponta a ponta — documentação completa e viva em
**`docs/superadmin/`** (architecture, decisions SA-D01…SA-D09, roadmap M1–MF,
progress, api, blockers, bugs, todo). Resumo do que existe agora:

- **Painel superadmin** (repo `barbearia-superadmin`): Dashboard executivo (MRR/
  ARR/churn/LTV + séries), Central de Operações (alertas por regra), Barbearias
  (tabela rica + detalhe 360° com notas internas/timeline/onboarding), Onboarding
  (funil 11 etapas derivadas + overrides manuais), Assinaturas (dunning + 8 ações),
  Financeiro, Logs (auditoria + webhooks com reprocesso), Configurações (planos
  CRUD + sync gateway, cupons), paleta ⌘K, design system alinhado ao tenant.
- **Billing** (`app/services/billing/`): domínio completo (migration 0032 —
  invoices/billing_payments/payment_attempts/coupons/credits/billing_events/
  webhook_events/plan_prices/plan_limits/feature_flags), interface `BillingProvider`
  + `StripeBillingProvider` (único import de stripe; Checkout mode=subscription,
  Portal, Prices, webhook assinado, API 2026-06-24.dahlia) + `MockBillingProvider`
  (default sem chave), lifecycle manual (`/internal/billing/run-lifecycle`, cron
  n8n pendente), entitlements com `BILLING_ENFORCEMENT=off|log|hard` (1º ponto:
  criação de barbeiro).
- **Plataforma**: `/platform/metrics|alerts|audit-log`, `/platform/orgs/overview`
  + detalhe 360°, onboarding, `/platform/billing/*`, impersonação
  (`POST /platform/orgs/{id}/impersonate` — motivo obrigatório, token 5–60 min
  com claim `imp_by`, auditoria em `platform_audit_log` [migration 0034, molde
  estrito sem GRANT]).
- **Envs novos**: `BILLING_PROVIDER`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `BILLING_GRACE_DAYS_PAST_DUE`, `BILLING_ENFORCEMENT`. Dep nova: `stripe`.
- **Deploy**: aplicar 0028–0034 (aditivas), setar envs, criar cron do lifecycle,
  webhook endpoint na Stripe. Bloqueios externos em `docs/superadmin/blockers.md`
  (B-01 domínio, B-02 chaves Stripe, B-03 cron n8n).

### D-62 — Sincronização de fidelidade a partir do ranking da Trinks (destrava a reativação) — 2026-07-03
**Contexto:** a reativação de clientes filtra por `client_loyalty.status` (`em_risco`/`inativo`),
mas `client_loyalty` só nascia ao **concluir atendimentos pelo próprio sistema**. Como a base de
prod (org 1) veio migrada da Trinks (~2,9k clientes com histórico fora do sistema), a tabela estava
**vazia** → a reativação enxergava **0 alvos**; idem a visão de inativos em Clientes/Fidelidade. O
pedido "sincronizar o CRM" era exatamente destravar isso.
**Decisão:** semear `client_loyalty` + o ledger de pontos a partir do **ranking da Trinks** — coluna
"Último Atendimento" → status via `compute_status`; "Total"/"Visitas" → pontos históricos (1 pt/R$ +
10/visita, regra D-50). Bootstrap único: quando um atendimento real concluir, `recalculate()`
sobrescreve os campos de snapshot com os agregados do sistema, mas os pontos do ledger (append-only)
permanecem.
**Implementação:** `app/services/trinks_ranking.py::sync_loyalty_from_ranking` (dry-run + idempotente —
pontos creditados 1×/cliente via marcador de `reason` no ledger; snapshot reescrito a cada run) + rota
`POST /admin/import/trinks/loyalty` (gestor, mesmo molde das demais) + `scripts/import_trinks_loyalty.py`
(CLI, roda na VM) + `tests/test_trinks_loyalty.py` (8 testes: parsers puros + integração RLS com rollback).
**Cron (parte A do pedido):** o `CronReactivation1` do n8n **já** roda 1×/dia às 11h BRT (`0 11 * * *`,
ativo, execuções ok) — nada a ajustar; o que travava a reativação era a fidelidade vazia, não a cadência.
**✅ DADOS GRAVADOS EM PROD 2026-07-03 (org 1, via CLI):** 2.442 linhas do ranking casadas por telefone
(0 órfãs; 23 sem telefone) → **2.197 clientes únicos** com fidelidade: 640 ativos / 290 em risco / 1.267
inativos → **1.557 alvos de reativação** (antes: 0). 965.181 pontos históricos no ledger (saldo do
snapshot confere com a soma do ledger). **Reativação continua DESLIGADA** — o número restrito (D-41)
exige Cloud API para entrega confiável; isto só populou os dados.
**Consequências / ressalvas:** casar por telefone tem a imperfeição conhecida de telefone não-único
(245 linhas duplicadas colapsaram no mesmo cliente — vale o snapshot da última linha, pontos 1×);
aceitável para o bootstrap. **Código pendente de commit/deploy permanente:** o sync foi rodado via CLI
injetado no container (uvicorn sem reload → processo vivo intacto) e a rota `/loyalty` ainda **não** está
no backend de prod; falta commit + rebuild para persistir (dados independem disso).

### D-63 — Import de transações de pagamento da Trinks (histórico analítico, tabela dedicada) — 2026-07-04
**Contexto:** o usuário perguntou se o export **"Pagamentos/Estornos"** da Trinks
(`taylorethedy26pagamentos.csv`) já estava implementado. Não estava — é justamente o **pagamento por
comanda** que o D-59 (fechamento de caixa) marcou **fora de escopo**. Ele não cabe no `Payment` do
sistema: `Payment.appointment_id` é NOT NULL / FK RESTRICT e não temos o histórico de agendamentos do
período; e o enum `PaymentMethod` (só dinheiro/cartão/pix) não captura taxa de operadora, antecipação,
parcela, estorno nem conta financeira.
**Decisão (do usuário, via pergunta dirigida):** importar como **tabela analítica dedicada**
`payment_transactions`, espelhando o export **como está** — base para relatórios de mix de formas de
pagamento, custo de cartão e fluxo de recebíveis. **Não** toca em `payments` (sistema) nem exige vínculo
a agendamento. Mesmo molde dos demais imports Trinks (parser puro + persistência + rota self-service +
CLI + testes).
**Implementação:** migration **`0035`** (`payment_transactions`; RLS + policy `tenant_isolation` + grants
a `barber_app` no molde da `0026`; índice `(org, movement_date)`; **sem UNIQUE**) + `models/payment_transaction.py`
+ `app/services/trinks_payments.py` (`parse_payments` puro + `import_payments`) + rota
`POST /admin/import/trinks/payments` (gestor, corpo = CSV bruto, `commit` dry-run/grava) +
`scripts/import_trinks_payments.py` (CLI, roda na VM) + `tests/test_trinks_payments.py` (8 testes:
moeda BR com sinal / data / extração de colunas / descarte sem data + integração RLS com rollback).
**Decisões de design:**
1. **Sem CHECK constraints** (ao contrário do D-60): desconto de operadora e troco carregam valores
   **legitimamente negativos** — CHECK de não-negatividade quebraria a importação do histórico real.
2. **Idempotência por substituição de período** (delete-by-range de `movement_date` filtrado a
   `source='trinks'`), **não upsert**: o export não tem chave natural única (pagamentos idênticos no
   mesmo dia são possíveis). Re-rodar o mesmo arquivo converge; reexportar um período corrigido o
   substitui.
3. **Minimização de PII (LGPD):** a tabela **exclui** nome do cliente / quem fechou a conta / comentário
   — o objetivo analítico (mix, taxa, recebíveis) não precisa deles. `movement_date` cai para a data do
   atendimento quando a de movimentação falta.
**Validação:** migration aplicada no **staging** (head `0035`); suíte **472 pass / 2 falhas ambientais
(as de sempre: `bypass_hours` do workflow n8n + e2e login/cliente/agendamento) / 0 regressões** (+8
testes novos verdes). Arquivo real inspecionado só em agregados (23 colunas, ~3,7k linhas, latin-1, `;`;
soma Valor Pago ≈ R$ 414 mil) — o cru é PII/financeiro, **nunca versionado** (`.gitignore`); fixture
anonimizada (`tests/fixtures/trinks/payments_sample.csv`) versionada.
**✅ DEPLOYADO em prod 2026-07-04 (molde D-59):** PR #22 mergeado (merge `c050b0d`, commit do D-63 `9fa6f91`);
`git pull` na VM; backup `~/predeploy_d63_20260704_163707.sql` (1,2 MB, 15.715 linhas); migration `0035`
aplicada como superuser `postgres` montando o repo do host (a imagem não copia `alembic/`; `ADMIN_DATABASE_URL`
ausente na VM → URL inline; head agora `0035`); rebuild do backend (`/health` = `{"status":"ok"}`); import
via CLI na org 1: **3.714 transações** (1 linha sem data descartada), período **05/01–03/07/2026**,
**R$ 414.137,15** pagos / **R$ 407.315,12** a receber / **−R$ 6.823,55** de taxa de operadora — validação
independente via `psql` (filtro org 1) conferiu count + somas, batendo com o relatório da Trinks.
`removed_existing=0` (tabela nova, idempotência por substituição de período confirmada no dry-run). CSV cru
apagado da VM (minimização de PII, LGPD). **Falta:** consumo — relatórios de mix de formas / custo de cartão /
recebíveis no frontend — passo próprio.

### D-64 — Domínio próprio ativado: `taylorethedy.com` com TLS coringa (Cloudflare DNS-01) — 2026-07-05
**Contexto:** o domínio `taylorethedy.com` foi comprado (guarda-chuva, DNS gerenciado na Cloudflare) para
destravar duas frentes que dependiam dele: o multi-tenant real por subdomínio (D-54, código pronto desde
2026-06-30 mas sem DNS pra ser alcançado) e o painel de Superadmin (D-55/D-56, deploy preparado mas não
ativado). Também é a base para uma futura "porta" de agendamento self-service do cliente final (discutida,
não implementada).
**Decisão:** subdomínio **coringa** (`*.taylorethedy.com`) em vez de registros individuais por tenant —
uma barbearia nova vira acessível sem tocar em DNS de novo. Isso exige certificado TLS coringa, que só é
validável por **DNS-01** (não HTTP-01) — logo, Cloudflare + `certbot-dns-cloudflare` (token de API restrito
à zona, escopo `Zone:DNS:Edit`, não o Global API Key).
**Registros DNS:** `A @ → 34.95.199.134` + `A * → 34.95.199.134`, ambos **DNS only** (nuvem cinza, sem
proxy da Cloudflare) — mantém o TLS terminando direto na VM via nginx/certbot, sem reconfigurar modo SSL
da Cloudflare nem repasse de IP real.
**Migração do certbot de apt → snap:** `certbot certonly --dns-cloudflare` via apt travou com
`AttributeError: module 'lib' has no attribute 'GEN_EMAIL'` — descompasso de versão entre `pyOpenSSL` e
`cryptography` do sistema (bug conhecido do certbot instalado via apt). Como nenhum certificado válido
existia ainda (DNS nunca tinha propagado antes), a troca para o método oficialmente recomendado (snap,
isolado das libs Python do sistema) foi feita sem risco:
```
snap install --classic certbot && ln -sf /snap/bin/certbot /usr/bin/certbot
snap install certbot-dns-cloudflare
snap set certbot trust-plugin-with-root=ok
snap connect certbot:plugin certbot-dns-cloudflare
certbot certonly --dns-cloudflare --dns-cloudflare-credentials /root/.secrets/certbot/cloudflare.ini \
  -d taylorethedy.com -d "*.taylorethedy.com"
```
Renovação automática via timer do próprio snap (`snap.certbot.renew.timer`), sem passo manual a cada 90 dias.
**`deploy/nginx.conf`:** corrigida a inconsistência de domínio do rascunho anterior (frontend estava em
`taylorethedy.app`, backend/superadmin já em `.com`) — tudo unificado em `taylorethedy.com`. Estrutura final:
bloco 80→443 redirect (todos os hosts) + bloco 443 `taylorethedy.com`/`*.taylorethedy.com` → frontend de
tenant (:3000, D-54) + bloco 443 `api.taylorethedy.com` → backend (:8000) + bloco 443
`admin.taylorethedy.com` → superadmin (:3100, D-55/56). Nginx prioriza `server_name` exato sobre coringa,
então `admin.`/`api.` nunca são capturados pelo bloco coringa dos tenants.
**`deploy/setup-vm.sh`:** reordenado — SSL (passo 3) agora roda **antes** do nginx (passo 4), porque o
`nginx.conf` referencia os arquivos do certificado; carregar o nginx primeiro faria o `nginx -t` falhar por
o certificado ainda não existir. Também trocado `apt install certbot` por `snapd` + instruções do snap, e
corrigidas as referências a `taylorethedy.app`.
**Validado em prod (VM já provisionada, fora do `setup-vm.sh`):** `git pull` (`ce80710`) + `nginx -t` OK +
`systemctl reload nginx`. Testes:
- `https://api.taylorethedy.com/health` → 405 em `HEAD` (só aceita `GET`, comportamento normal do
  FastAPI) — confirma TLS + proxy pro backend OK.
- `https://admin.taylorethedy.com` → 502 (esperado: container do superadmin ainda não ativado, D-56
  segue como próximo passo separado).
- `https://taylor.taylorethedy.com` (subdomínio real da org 1) → 307 para `/login` com cookies do
  next-auth (`callback-url=https://taylor.taylorethedy.com`) — **primeira confirmação em produção de que
  a resolução multi-tenant por subdomínio (D-54) funciona de ponta a ponta.**
**Pendente:** ~~ativar o container do superadmin~~ — feito em 2026-07-05, ver D-56 (seção "✅ ATIVADO em
prod").

### D-65 — Import do DRE mensal da Trinks: histórico financeiro por competência (tabela analítica dedicada) — 2026-07-06
**Contexto:** o sistema nunca teve histórico de custos/resultado — a tabela `Expense` está vazia e a
receita só existe a partir dos atendimentos concluídos pelo próprio app. A Trinks exporta o **"DRE"**
(Demonstrativo de Resultado) mensal: receita por tipo + despesa por categoria/subgrupo + resultado, mês a
mês, desde mai/2020. É a peça que faltava pro dashboard executivo — custo **fixo × variável**, folha
(alinha com o D-57), margem e evolução de ~6 anos. Complementa o D-59 (caixa/recebimento) e o D-63
(pagamentos por comanda): o DRE é **competência** (accrual), não recebimento — **não reconcilia 1:1** com
`payment_transactions`/`cash_daily_closings`; são lentes diferentes.
**Formato do arquivo:** matriz **pivotada** — linhas = itens do DRE, colunas = meses (`"outubro / 2025"` …
+ `"Total do Período"`, esta ignorada). Seções `RECEITAS` e `(-) DESPESAS`; despesa tem 5 subgrupos
(Fixas/Variáveis/Pessoal/Impostos/Outros), cada um com uma linha de **subtotal** seguida das folhas.
Exportado dividido por ano (driblar o timeout síncrono do export da Trinks) — 6 arquivos contíguos.
**Decisão:** **tabela analítica dedicada** `dre_monthly_lines` (migration **0036**, molde das 0026/0035:
FK CASCADE + RLS por `organization_id` + GRANT ao `barber_app`). Guarda **só as linhas-folha**; subtotais
de subgrupo e totais do arquivo são **recomputados** (evita dupla contagem). Colunas: `competence_month`
(1º dia do mês), `section` (receita|despesa, **CHECK** `dre_section_valid`), `subgroup` (slug; NULL em
receita), `line_item`, `amount Numeric(12,2)`, `source='trinks'`. **Sem CHECK de sinal** em `amount`
(≠ D-60): contra-receitas — ex.: "Consumo de Pré-pago" — são legitimamente negativas, igual à taxa de
operadora do D-63. **Sem UNIQUE**: idempotência por **substituição dos meses** cobertos pelo arquivo
(delete-by-mês + insert), no molde do D-63.
**Parser (`app/services/trinks_dre.py`):** despivota os meses (trata latin-1 + acento em `março`),
detecta seções pelos cabeçalhos e subgrupos **estruturalmente** (o 1º item-com-valor após uma linha em
branco, dentro de DESPESAS, é o subtotal do subgrupo → define o subgrupo e é pulado). Um **self-check**
soma as folhas por mês e compara com os totais declarados no próprio arquivo (`checksum_ok`) — vira um
detector de erro de parse. Pula valores zero (mantém a tabela enxuta). Parte pura (`parse_dre`) +
persistência (`import_dre`).
**Tooling (tríade + leitura):** rota self-service `POST /admin/import/trinks/dre` (`app/api/imports.py`,
gestor, corpo = CSV bruto, `commit=false` dry-run) + CLI `scripts/import_trinks_dre.py` (roda **na VM**,
aceita vários arquivos de uma vez — meses disjuntos) + endpoint de leitura `GET /financeiro/dre?inicio=&fim=`
(série mensal: receita, despesa com quebra por subgrupo, resultado, margem). Testes
`tests/test_trinks_dre.py` (9) com **fixture sintética** `dre_sample.csv` (o DRE é P&L sensível — nunca
usar números reais de T&T no repo).
**Débitos descartados:** em paralelo, o export "Débitos de clientes" da Trinks foi confirmado **inválido**
pelo dono e sai do escopo (era um dos 5 blocos candidatos). Como `client_debts` é tabela-folha (nada a
referencia; `client_id` é FK opcional de saída), removê-los não cascateia. Não há rota de DELETE no app →
`scripts/delete_org_debts.py` (molde do `reset_org.py`: `barber_app`+RLS, dry-run, `--commit` exige
`--confirm-name`). A remover na org 1 em prod (contas a receber da migration 0023 seguem existindo p/ orgs
futuras, só a carga T&T é descartada).
**Validação (staging, head 0036):** parser rodado nos **6 arquivos reais** → `checksum_ok=True` e 0
mismatches em **todos os 75 meses** (mai/2020 → jul/2026, contíguos, sem overlap), 2.752 linhas-folha, 5
subgrupos detectados. Suíte **481 pass / 2 skip / 2 ambientais / 0 regressões**. Migration aplicada na
staging com a role dona (`ADMIN_DATABASE_URL`; `barber_app` não cria em `public`).

**✅ DEPLOYADO em prod 2026-07-06** (PR #23, merge `6ab1a3e`; molde D-59/D-63):
1. **Branch + PR + merge** para `main` (`feat/trinks-dre-import` → `6ab1a3e`).
2. **Backup** `pg_dump` → `~/predeploy_d65_20260706.sql` (1.8 MB) na VM.
3. **Débitos:** confirmado **0 linhas** em `client_debts` da org 1 — a carga nunca foi para produção (era só
   tooling), então o `delete_org_debts.py` seria no-op; **nada a apagar**.
4. **`git pull`** (ff-only `ce80710`→`6ab1a3e`) + **migration 0036** rodada num container efêmero montando o
   repo do host, como owner `postgres` (URL inline lida do container postgres; `ADMIN_DATABASE_URL` ausente na
   VM). Head → `0036`; tabela criada com CHECK `dre_section_valid`, índice, FK CASCADE, policy RLS
   `tenant_isolation` e grants `barber_app=arwd`.
5. **Import** dos 6 arquivos na org 1 via CLI (container efêmero, CSVs montados read-only de área temporária no
   home): **dry-run** (todos `checksum_ok`) → **commit** = **2.752 linhas-folha / 75 meses**,
   `removed_existing=0` (1ª carga). Validado por `psql` independente: contagens por seção/subgrupo batem, e
   **isolamento RLS confirmado** (0 linhas em outras orgs).
6. **Rebuild backend** (`up -d --build backend`): `healthy`, `/health` ok, rotas `/financeiro/dre` e
   `/admin/import/trinks/dre` no OpenAPI (código novo no ar).
7. **Limpeza LGPD:** CSVs de DRE removidos da VM (P&L sensível); backup preservado.

**✅ Consumo no dashboard — DEPLOYADO em prod 2026-07-06** (frontend PR #5, merge `2665437`): terceira visão
do Financeiro (`Dia · Mês · DRE`) em `/admin/financeiro` consumindo `GET /financeiro/dre` — 4 KPIs
(receita/despesa/resultado/margem), gráfico Receita×Despesa por mês (barras verde/vermelha, eixo de anos,
tooltip no hover), composição da despesa por subgrupo (Pessoal/Fixos/Variáveis/Impostos/Outros), detalhamento
mensal e nota de competência (DRE é accrual — **não reconcilia 1:1 com o caixa**). Seletor de período 12/24
meses/tudo (padrão 24m). Design system: `AsyncState` (5 estados) + React Query (`useFinanceiroDre`) + tokens
`--chart-*` (gráfico e barras à mão — o projeto não usa lib de chart); validado nos temas claro e escuro
(séries sintéticas de 75 e 12 meses). `components/financeiro/dre-view.tsx` (novo) + 5 arquivos (`types`,
`hooks/use-financeiro`, `constants`, `index`, `financeiro/page`); `tsc`+`eslint` limpos. Deploy só-frontend
(sem migration): `git pull` na VM (fast-forward `e985d85`→`2665437`) + rebuild `--build frontend`; smoke
`/login` 200, HTTPS `taylor.taylorethedy.com` 200, e o bundle `.next` contém o código do DRE.

### D-66 — Consumo no frontend do D-63 (Pagamentos) + DRE detalhado (drill-down) + CORS multi-tenant — 2026-07-06
**Contexto:** dois relatórios do Financeiro tinham o backend pronto mas sem consumo. O **DRE** (D-65) só
mostrava o agregado por subgrupo — o dono queria ver as **contas individuais**; e os **Pagamentos/Estornos**
(D-63, `payment_transactions`, 3.714 transações em prod) não tinham nenhuma tela — o mix de formas, o custo
de cartão e o recebimento mês a mês só existiam no banco.
**Backend (2 endpoints, PR #24 — merge `41b591a`, commit `12ed60c`):**
- `GET /financeiro/dre` ganhou `despesas_por_item` (linhas-folha por subgrupo) **além** do agregado —
  aditivo, sem quebrar o contrato anterior.
- `GET /financeiro/pagamentos?inicio=&fim=` **novo**: lê `payment_transactions` e devolve totais (recebido,
  taxa, líquido, ticket médio, PIX%), mix `por_tipo`, `por_bandeira` (custo e % por bandeira) e série
  `por_mes` (recebido/taxa/líquido). Números 100% do banco — nada calculado no cliente.
- Testes `tests/test_financeiro_dre_pagamentos.py` (5) com **fixture sintética** (ano 2099 — P&L é sensível,
  nunca usar números reais de T&T no repo). Suíte sem regressão.
**Frontend (PR #6 do submódulo — merge `b57320a`):** Financeiro passa a ter 4 abas (`Dia · Mês · DRE ·
Pagamentos`).
- **DRE detalhado:** cada subgrupo da "Composição da despesa" virou um **accordion** (`SubgrupoAccordion`)
  que abre as contas-folha ordenadas por valor, com barra proporcional; + card **"Top 10 maiores despesas"**
  do período. Apresentação escolhida pelo dono: "os dois juntos" (drill-down + Top 10).
- **Pagamentos** (`components/financeiro/pagamentos-view.tsx`, 4ª aba): 4 KPIs (recebido/custo de
  cartão/líquido/ticket), "Mix por forma de pagamento" (barras tokenizadas), "Custo de cartão por bandeira"
  (tabela) e "Recebimento por mês" (barras com tooltip). Rodapé: recebimento ≠ competência (não reconcilia
  1:1 com o DRE). Seletor 12/24 meses/tudo (padrão 24m).
- Design system: `AsyncState` (5 estados) + React Query (`useFinanceiroDre`/`useFinanceiroPagamentos`) +
  tokens `--chart-*`; `tsc`+`eslint` limpos; validado nos temas claro e escuro.
**Fix de CORS multi-tenant (PR #25 — merge `e2b495d`, commit `8143cae`):** a validação em prod esbarrou num
bug **pré-existente** — `https://taylor.taylorethedy.com` não estava no `CORS_ORIGINS` (allowlist fixa), então
todo preflight do browser dava **400** e o admin não carregava dados (o **login** funcionava porque o
next-auth Credentials roda server-side, fora do CORS — por isso o bug passou despercebido até a 1ª validação
de dados no browser). Correção: campo novo `cors_origin_regex` (`app/core/config.py`) → `allow_origin_regex`
no middleware (`app/main.py`), em **OR** com a allowlist. Em prod:
`CORS_ORIGIN_REGEX=https://([a-z0-9-]+\.)?taylorethedy\.com` no `.env` da VM — cobre o apex + qualquer
subdomínio de tenant (`taylor.`, futuro `org.`, `admin.`) **sem redeploy por tenant**. Testes
`tests/test_cors_origin.py` (9): apex/tenant/admin/localhost permitidos; `evil.com`, sufixo/prefixo forjado e
`http://` barrados (400, sem header allow-origin).
**Arquitetura de domínios (decisão do dono):** `taylorethedy.com` (apex) será a **página do cliente final**
da org 1 (a fazer); `taylor.taylorethedy.com` será renomeado para **`org.taylorethedy.com`** = portal de login
de funcionários/donos/gerentes da org 1. A regex de CORS já cobre os dois — o rename **não** exigirá mudança
de backend.
**✅ DEPLOYADO em prod 2026-07-06 (sem migration):** backend (PR #24 `41b591a` + PR #25 `e2b495d`; `git pull`
+ rebuild `--build backend`, `/health` ok, `CORS_ORIGIN_REGEX` adicionado ao `.env` da VM), frontend (PR #6
`b57320a`; `git pull` + rebuild `--build frontend`). **Validado no browser em prod** (org 1, dados reais,
temas claro e escuro): aba Pagamentos com **R$ 414.137,15 recebido / −R$ 6.823,55 de custo de cartão / 3.714
transações** (conferindo com o D-63) e o DRE com drill-down por subgrupo + Top 10 sobre os 75 meses de
competência (Receita R$ 1.942.326,22 / Despesa R$ 1.700.037,14 / Margem 12,5% no recorte de 24m). Preflight
em prod confirmado: tenant permitido, `evil.com` barrado.

### D-67 — Núcleo de autorização RBAC por permissões (Fase 2 do plano de Segurança) — 2026-07-07 (só staging)

Origem: prompt `promptseguranca.md` (Segurança/Governança Enterprise, 9 fases com checkpoints).
**Fase 0** produziu `AUDITORIA_SEGURANCA.md` (29 achados, 1 Crítica/5 Altas; confirmados contra a VM de prod:
webhook `/bot/wa-webhook` sem auth = `WA_WEBHOOK_SECRET` ausente; portas 8000/3000 **não** expostas no firewall
GCP; `barber_app` NOBYPASSRLS e sem GRANT em `platform_admins`; `AUTH_SECRET` de prod forte). **Fase 1** produziu
`ARQUITETURA_ALVO.md` (RBAC por permissões + ABAC, guard central, `/me/permissions`, sessão/refresh, auditoria,
multi-tenant reforçado, LGPD, UX da área "Segurança").

**Fase 2 (esta entrega — só staging):** núcleo de autorização baseado em **permissões nomeadas** (`recurso.sub.ação`),
substituindo a causa-raiz dos bugs de autorização (RBAC por papel checado manualmente, "abre por omissão").
- **Fonte única em código** `app/core/permissions.py`: 58 permissões + matriz dos **9 papéis de sistema**
  (owner/partner/manager/reception/barber/intern/finance/marketing/support). Papéis de sistema resolvem
  permissões pelo código (fail-safe, sem depender de seed).
- **Schema** (migration **0037**, head `0037`): `permissions` (global), `roles` (sistema org NULL + personalizados
  por org), `role_permissions`, `user_roles`, `permission_overrides` — RLS no molde da 0036 (`roles`/`role_permissions`
  = "global OU tenant" com WITH CHECK; `user_roles`/`overrides` = tenant-only). `FORCE RLS` deferido p/ hardening
  uniforme (Fase 3). `app/services/authz_seed.py::sync_system_catalog` (idempotente) espelha o catálogo no banco
  (via `scripts/seed.py` e `scripts/sync_authz_catalog.py`).
- **Resolver** `app/services/authz.py::resolve_permissions` = permissões do papel de sistema (de `user_units`, via
  código) ∪ papéis extras/personalizados (`user_roles`) ∪ overrides (deny vence). **Retrocompatível:** os 4 papéis
  atuais mapeiam 1:1; nenhum acesso muda exceto as correções abaixo.
- **Guard central** `app/authz.py::require(permission)` (dependência de rota) + `AuthContext` p/ filtragem por campo.
  `GET /auth/me/permissions` alimenta o frontend (só UX).
- **Correções de auditoria aplicadas** (defaults de permissão + guards): **V5** (dashboard redige receita/comissão
  sem `reports.dashboard.financial.view` → recepção deixa de ver financeiro no dashboard), **V6**
  (`integracoes` status/QR exigem `integrations.view`/`integrations.whatsapp.manage`), **V7** (`clientes/bot-pause`
  exige `clients.bot_pause`), **V4** (SSE `/crm/stream` revalida usuário + exige `conversations.stream`), **V19**
  (`_require_bot_token` tempo-constante). **V24 (billing) adiado de propósito** (restringir `/billing/subscription`
  quebraria o feature-gating por entitlements que o frontend usa em todos os papéis).
- **Testes:** `tests/test_authz_unit.py` (8, matriz/drift) + `tests/test_authz_integration.py` (11, /me/permissions
  por papel + V4/V5/V6/V7 nos endpoints reais). Seed ganhou usuários **gerente/recepção** (`seed_admin_users`);
  conftest ganhou fixtures `manager_headers`/`reception_headers`. **Suíte: 514 pass / 2 ambientais / 0 regressões.**
- **F2.5 — migração dos endpoints legados (✅ concluída):** ~90 call-sites de `require_full_access`/
  `require_manager_access` migrados para `require_permission(db, user, code)` em 15 routers (agenda, clientes,
  crm, conversations, loyalty, memberships, financeiro, equipe, servicos, empresa, gestor, debts, imports,
  reschedule, dashboard). Mapeamento **provadamente não-regressivo**: cada guard → permissão cujo conjunto de
  papéis (entre os 4 atuais) é **idêntico** ao antigo (ex.: full_access → `schedule.all.manage`/`clients.manage`/
  `crm.leads.manage`/... = {owner,manager,reception}; manager_access → `finance.revenue.view`/`team.manage`/... =
  {owner,manager}). Ajuste da matriz p/ o mapeamento fechar: `team.view` e `schedule.reschedule.approve` saíram do
  default da recepção (eram manager-only) + permissão nova `data.import`. **`billing.py` ficou no guard legado de
  propósito** (checkout/portal exigiriam `billing.manage`, owner-only na matriz — converter agora tightening o
  manager; fica p/ decisão de produto). **Teste de cobertura** (`tests/test_authz_coverage.py`) afirma que toda
  rota não-pública tem ponto de auth na árvore de dependências (fecha a classe "esqueci o guard"). +
  `tests/test_authz_sweep.py` (matriz de papéis nos endpoints migrados). **Suíte: 526 pass / 2 ambientais / 0
  regressões.**
- **F2.6 — frontend consome `/auth/me/permissions` (✅, submódulo `barbearia-frontend`):** hook
  `hooks/use-permissions.ts` (`usePermissions().has(code)`, via React Query, cache 5 min; enquanto carrega `has`
  retorna false → item restrito não pisca). **`AdminSidebar`** filtra itens/grupos por permissão (cada item ganhou
  `perm`; grupo sem itens visíveis some) + **rodapé com identidade real** (email + papel pt-BR, antes hardcoded
  "Administrador/admin@sistema.com"). **`AdminHeader`** avatar com inicial real + email no `title` (antes "A" fixo).
  **Botão "Conectar WhatsApp"** (`/admin/integracoes`) escondido sem `integrations.whatsapp.manage` (V6 na UI;
  recepção vê status, não o botão). Typecheck (`tsc --noEmit`) limpo. **Não verificado no browser ainda**
  (recomendado antes do deploy). Débito: gating dos cards financeiros do Dashboard p/ recepção (hoje o backend
  zera os valores — V5 — mas a UI ainda mostra os cards zerados; mesmo padrão `usePermissions`).
- **✅ DEPLOYADO em prod 2026-07-07** (backend `bf2acb2` + frontend `8535796`, direto na main):
  backup `~/predeploy_d67_20260707_205028.sql` → `git pull` → **migration 0037** aplicada (head `0037`, 5 tabelas +
  RLS) → **catálogo sincronizado** (59 perms / 9 papéis / 251 grants) → rebuild backend + frontend.
  **Validado em prod:** `resolve_permissions` como `barber_app`/RLS sobre dados reais → **owner (Taylor) = 59
  permissões** (mantém tudo), **barbeiro = 4** (correto, sem finance); rotas `/auth/me/permissions`+`/financeiro`
  = 401 (vivas+protegidas), `/auth/tenant` = 200, `/health` = 200, HTTPS `api.`+`taylor.taylorethedy.com` = 200.
  **Impacto comportamental nulo:** prod org 1 só tem 2 owner + 3 barbeiro (0 reception/manager) → V5/V6 (recepção)
  não afetam ninguém; barbeiros mantêm o workflow (`/barbeiro/*`+`barbeiro.py` intocados). **Notas operacionais:**
  o backend **não** está na `barbearia_network` — alcança o PG via `host.docker.internal:5432` (a migration/sync
  usaram esse host, não o nome do container); a imagem do backend **não copia `scripts/`** → migration E sync
  rodam montando o repo do host (`-v /opt/barbeariapro:/repo:ro -w /repo`), molde D-60. Ordem crítica respeitada:
  migration ANTES do rebuild (senão o resolver 500a em tabela inexistente).

### D-68 — Sessão, dispositivos e hardening de autenticação (Fase 3 do plano de Segurança) + UI de gestor — 2026-07-09 (pronto localmente, não commitado/deployado)

Fase 3 do `promptseguranca.md`, seguindo o núcleo de permissões do D-67. Fecha V1 (parcial — refresh/revogação),
V2 (rate limit/lockout), V9 (JWT sem revogação), V10/V4 (token na query string do SSE), V11 (parcial — reset
administrativo sem e-mail), V12 (headers de segurança/`/docs` exposto), V13 (enumeração de usuário), V16 (FORCE RLS).

**Backend:**
- Access token curto (**15min**, era 60) + **refresh token rotativo** (tabela `sessions`, Postgres — fonte de
  verdade; Redis só guarda dado efêmero) com **detecção de reuso**: reapresentar um refresh já rotacionado revoga
  a sessão inteira (indício de token roubado). Migration **0038** (head `0038`): tabela `sessions` (RLS +
  `users.must_change_password`) e **`FORCE ROW LEVEL SECURITY`** aplicado dinamicamente a todas as tabelas com RLS
  (via `pg_class`, não lista manual — cobre `sessions` e as ~30 tabelas de tenant já existentes).
- Dispositivos: parsing de user-agent (`user_agents`) → SO/navegador + IP; `ip_geo` reservado (sem geolocalização —
  exigiria base MaxMind própria, fora do MVP).
- Rate limiting (slowapi + Redis, `app/core/rate_limit.py`) + lockout progressivo de login por IP e IP+e-mail
  (`app/core/config.py`: `login_max_attempts`/`_window`/`_duration`). Anti-enumeração (V13): bcrypt roda sempre
  (hash real ou `DUMMY_PASSWORD_HASH`), mesma resposta para usuário inexistente/senha errada/org suspensa.
  Headers de segurança (`SecurityHeadersMiddleware`: HSTS/CSP/X-Frame-Options/etc.) + `/docs`/`/redoc`/`/openapi.json`
  desligados por padrão (`docs_enabled=False`).
- Rotas: `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/change-password` (revoga as OUTRAS sessões),
  `GET/POST /auth/me/sessions*` (self-service). `app/api/security.py` (novo router `/admin/security/*`, gestor
  agindo sobre outro usuário): `POST /users/{id}/reset-password` (senha temporária de uso único, força troca,
  revoga todas as sessões do alvo — sem e-mail no stack, repasse é manual) + `GET /sessions` (revoga
  `POST /sessions/{id}/revoke`). SSE do CRM parou de levar o JWT na query string (V10/V4): `hooks/use-conversas.ts`
  troca por um **ticket de uso único (30s)**, com reconexão manual (o retry nativo do `EventSource` reapresentaria
  a mesma URL já consumida).
- **UI de gestor (fechada nesta sessão, completando a Fase 3):** `GET /admin/security/users` (lista usuários da
  org: e-mail/papel/status/`must_change_password`) e `GET /admin/security/sessions` passou a incluir
  `user_id`/`user_email` (antes só existia o filtro `?user_id=`, sem UI para descobrir de quem era cada sessão).
  Guardados pelas permissões já existentes no catálogo (`security.users.manage`/`security.sessions.*`, D-67).
- **Bug corrigido nesta sessão:** `_issue_session` (`app/api/auth.py`) salvava `str(parsed.os)`/`str(parsed.browser)`
  — o **repr** do namedtuple da lib `user_agents` (ex.: `"Browser(family='curl', version=(8, 7, 1), ...)"`), não um
  texto legível. Trocado por `parsed.get_os()`/`parsed.get_browser()` (ex.: `"Chrome 120.0.0"`). Sessões
  criadas antes da correção mantêm o texto antigo (histórico, cosmético, sem novo login não se corrige sozinho).
- Testes: `tests/test_auth_sessions.py` (24 — refresh/reuso, logout, troca de senha, self-service, lockout,
  anti-enumeração, reset administrativo, headers, `/docs` desligado, FORCE RLS, **+ 5 novos**: listagem de usuários
  da org, sessões de terceiros com `user_id`/`user_email`, revogação de sessão de outro usuário, e as duas negações
  de permissão para quem não é gestor). **Suíte: 546 pass / 2 ambientais (pré-existentes, não relacionadas) / 0
  regressões.**

**Frontend (submódulo `barbearia-frontend`):**
- Refresh token nunca chega ao client-side JS: vive só dentro do JWT criptografado do próprio next-auth
  (`lib/auth.ts`), que já é httpOnly por padrão — renovação automática ~1min antes de expirar, com dedup de
  chamadas concorrentes (evita 2 refreshes simultâneos colidirem com a rotação do backend e derrubarem a sessão).
  `proxy.ts` trata refresh falho como deslogado (redireciona ao login) e força `/trocar-senha` quando
  `mustChangePassword` está ligado (reset administrativo).
- `/admin/seguranca/sessoes` — self-service (listar/revogar os próprios dispositivos, "sair de todos os outros").
- **`/admin/usuarios` deixou de ser placeholder** ("em breve") **— tela completa nesta sessão**: lista os usuários
  da org (`hooks/use-admin-users.ts`) com papel/status/badge de troca pendente; ação "Sessões" abre diálogo com os
  dispositivos daquele usuário (revogação individual); ação "Resetar senha" pede confirmação e mostra a senha
  temporária **uma única vez** (com botão copiar). `lib/roles.ts` extraído (rótulo de papel pt-BR, antes só na
  `AdminSidebar`) para reuso entre a sidebar e a nova tela. `formatSessionDate`/`sessionDeviceLabel` extraídos de
  `hooks/use-sessions.ts` para reuso entre a tela self-service e a de gestor.
- Validado no browser (dev local): login, listagem de usuários, diálogo de sessões (estado vazio incluído),
  confirmação + geração de senha temporária, badge "Troca de senha pendente" atualizando em tempo real via
  invalidação do React Query. Build de produção (`next build`) e `tsc --noEmit` limpos.

**✅ DEPLOYADO em prod 2026-07-09** (backend `db828cf` + frontend `c453b47`, direto na main; molde D-60/D-67):
backup `~/predeploy_d68_20260709_034435.sql` → `git pull` (conflito local em `docker-compose.yml` — VM tinha o
digest do Evolution pinado direto, não commitado; resolvido com `stash`/`pull`/`stash pop`, sem perda) →
`git submodule update --init --recursive` (frontend em `c453b47`) → **migration 0038** aplicada (head `0038`,
via repo do host montado + superuser `postgres`, mesmo molde) → **novo serviço `redis`** subiu no
`docker-compose.app.yml` (`barbeariapro-app-redis`, saudável) → rebuild backend+frontend.
**Validado em prod:** `sessions` com `relrowsecurity`/`relforcerowsecurity` = true; **0 tabelas** com RLS sem
FORCE em todo o schema `public` (a migration dinâmica cobriu tudo); os 3 containers (`redis`/`backend`/`frontend`)
saudáveis; `/health` 200 com headers de segurança (HSTS/X-Frame-Options/CSP) presentes; `/docs` 404 (desligado);
`/admin/security/{users,sessions}` e `/auth/me/permissions` = 401 sem token (vivas+protegidas); `/auth/refresh`
com token inválido devolve 401 com mensagem (não 500); `/auth/tenant?subdomain=taylor` = 200 (público, intacto);
`/admin/usuarios` e `/trocar-senha` no frontend devolvem 307→login sem sessão (rotas existem, gate funcionando).
**Não testado nesta validação:** login real ponta a ponta com credencial de produção (evitado por não digitar a
senha real da conta em comando de shell) — recomendado um login manual do dono antes de considerar 100% fechado.
**Débito consciente:** sem middleware de CSRF dedicado — mitigado arquiteturalmente (a API só aceita Bearer no
header `Authorization`, nunca cookie; o refresh token não é acessível a JS de terceiros); revisar se algum fluxo
futuro passar a depender de cookie de sessão da própria API.

### D-69 — Health score por tenant + MRR em risco no painel de plataforma — 2026-07-09

**Contexto:** com a abertura do SaaS para várias empresas, o superadmin precisava de visão **proativa** de churn —
a Central de Operações (D-61) só reage a eventos pontuais (atraso, trial acabando); faltava um indicador composto
que ranqueasse a base inteira e dissesse "quem está escapando e por quê".

**Decisão:** score 0–100 por org, calculado **on-the-fly** em `app/services/health.py` (função pura, sem
migration — toda a matéria-prima já sai de `app_platform_org_overview()` + `app_platform_billing_subscriptions()`):
- **Engajamento (45 pts)**: recência da última atividade (25) + volume de agendamentos 30d (20).
- **Adoção (25 pts)**: profissionais (8) + clientes (12) + usuários (5).
- **Financeiro (30 pts)**: base por status da assinatura, penalidade progressiva de 2 pts/dia de atraso.
- Faixas: ≥70 `healthy` · ≥40 `watch` · <40 `at_risk` · suspensa → `suspended` (score 0, fora do ranking).
  Conta com <14 dias de vida tem carência: nunca cai abaixo de `watch` (sem histórico ≠ em risco).
- Cada dedução gera um **motivo legível** (pt-BR) — o painel mostra "por quê", não só o número.

**API:** `GET /platform/health` (distribuição por faixa + `mrr_at_risk` = MRR ativo de orgs `at_risk` + ranking
piores-primeiro); `/platform/orgs/overview` ganhou `health_score/band/reasons` + `order=health`;
`/platform/metrics` ganhou `mrr_growth` (último mês fechado vs anterior, mesma convenção do churn).

**Superadmin:** dashboard com seção "Saúde da base" (contagens por faixa, MRR em risco, fila dos 5 piores com
motivos + link 360°) e card "Crescimento MRR"; tabela de barbearias com coluna Saúde ordenável (badge + tooltip
com motivos). Testes: `tests/test_platform_health.py` (unidade da função pura + shape/isolamento dos endpoints);
suíte 556 pass (2 falhas pré-existentes fora de plataforma: `test_bot_unit` e e2e dependente de redis local).
Limiar/pesos são heurística inicial — recalibrar quando houver base real de churn observado.

**✅ DEPLOYADO em prod 2026-07-09** (backend `a7ff73a` + superadmin `f8a62b2`, submódulo bumpado em `75a272d`;
sem migration): backup `~/predeploy_d69_20260709_044630.sql` → stash do `docker-compose.yml` local (digest do
Evolution pinado, preservado) → `git pull` + `submodule update` (git na VM exige `sudo` — `.git` é do root; foi
preciso `safe.directory` p/ o submódulo) → rebuild `backend`+`superadmin` → ambos healthy. Smoke externo:
`/health` 200 · `/platform/health` e `/platform/metrics` 401 sem token · `admin.taylorethedy.com` 307 · logs
limpos. **Validado com login real do dono em 2026-07-09** — após corrigir um bug de deploy descoberto na hora:
o rebuild assou `NEXT_PUBLIC_API_URL=localhost:8000` no bundle do browser porque `SUPERADMIN_API_URL` (build-arg
do serviço `superadmin`) nunca fora setado no `.env` da VM (follow-up antigo baseado na premissa FALSA de que o
superadmin não chama a API client-side — as queries React Query rodam no browser; só o login/SSR usa
`API_URL_INTERNAL`). Fix: `SUPERADMIN_API_URL=https://api.taylorethedy.com` no `/opt/barbeariapro/.env` +
rebuild. **Todo rebuild futuro do superadmin depende dessa var** (é build-arg, não runtime).

### D-70 — Auditoria (Fase 4 do plano de Segurança) — 2026-07-09 (✅ DEPLOYADO em prod)

Fase 4 do `promptseguranca.md`, seguindo o núcleo de permissões do D-67 e a sessão/hardening do D-68. Fecha a
lacuna estrutural (§1.7/§2 do `ARQUITETURA_ALVO.md`): nenhuma tabela de auditoria genérica existia — só trilhas
parciais por domínio (`LeadEvent`, `canceled_by_user_id`/`reverted_by_user_id`, `platform_audit_log` da
plataforma, sem RLS).

**Backend:**
- **`audit_logs`** (migration **0039**, head `0039`): tenant, RLS + `FORCE ROW LEVEL SECURITY` explícito (nasce
  depois do loop dinâmico do D-68 — não é coberta por ele). **Append-only de fato**: `barber_app` recebe só
  `SELECT`/`INSERT` (sem `UPDATE`/`DELETE`), molde `platform_audit_log` (D-55) adaptado para RLS de tenant.
  Campos: ator (`actor_user_id`+`actor_kind`), ação, recurso (`resource_type`/`resource_id`), `before`/`after`
  (JSONB), `result` (`allow`/`deny`), motivo, IP, user-agent, e **`prev_hash`/`hash`** — cada evento inclui o hash
  do anterior da mesma org (`app/services/audit.py`, SHA-256 sobre JSON canônico), serializado por
  `pg_advisory_xact_lock` (mesmo mecanismo de `scheduling.py` para numeração atômica) — adulteração ou remoção de
  uma linha no meio quebra a cadeia dos eventos seguintes. `organizations.audit_retention_months` (default 12,
  aditivo) + função `SECURITY DEFINER app_audit_purge_expired()` (apaga por retenção, cruzando todas as orgs numa
  única chamada) + cron interno `POST /internal/audit/purge` (`X-Bot-Token`, molde `/internal/billing/run-lifecycle`
  — pendente de agendamento no n8n, mesmo padrão de todo cron do projeto).
- **Emissão fire-and-forget** (`app/services/audit.py::record_event`): agenda a escrita numa `asyncio.Task` com
  sessão própria (`AsyncSessionLocal`+`set_current_org`, molde `calendar_sync.py::push_appointment`) — não
  bloqueia o response. **Sem fila/worker separado**: o projeto não tem infra de fila (Redis é só dado efêmero) nem
  processo de worker (cron é sempre n8n batendo em `/internal/*`); a Task in-process é o "assíncrono" possível sem
  infra nova — trade-off documentado no próprio módulo (débito: não sobrevive a crash entre o response e a
  execução da Task).
- **Guard central audita sozinho** (`app/authz.py`): os 3 pontos de `raise HTTPException(403)`
  (`AuthContext.require`, `require_permission`, `require()._dep`) passaram a emitir `result=deny` **antes** de
  negar — cobre **100% das ~90 rotas** já protegidas por permissão nomeada (D-67) sem tocar em nenhuma delas.
  Só `require()._dep` (dependência de rota) captura IP/user-agent (tem `Request` injetado pelo FastAPI); os dois
  caminhos imperativos (`require_permission`/`AuthContext.require`, usados pela maioria dos call-sites) gravam sem
  IP/UA — trade-off para não re-tocar as ~90 chamadas da F2.5.
- **Eventos obrigatórios instrumentados** (§1.7): login (sucesso/falha)/logout/reuso de refresh detectado
  (`auth.py`); reset administrativo de senha e revogação de sessão (`security.py`); CRUD de clientes + bloqueio +
  bot-pause (`clientes.py`); despesas (criar/excluir) + exports financeiros (`financeiro.py`); venda/cancelamento/
  reativação/edição/exclusão de assinatura (`memberships.py`, reaproveita o `canceled_by_user_id` do D-51 como
  primeira fonte já migrada); conclusão de atendimento + estorno de uso de assinatura (`barbeiro.py`); config da
  empresa/unidade/horários (`empresa.py`); QR do WhatsApp (`integracoes.py`). **Não instrumentados** (confirmado
  que não existem ainda, débito de fase anterior): mudança de papel/permissão/override e convite/desativação de
  usuário — a UI "Papéis & Permissões" do `ARQUITETURA_ALVO.md §1.12` segue sem backend.
- **`GET /admin/security/audit`** (timeline filtrável: ator/ação/recurso/período/`allow`|`deny`, paginada) e
  **`GET /admin/security/audit/export.csv`** — cada uma atrás da permissão própria já existente no catálogo desde
  o D-67 (`security.audit.view`/`security.audit.export`, sem migration nova de permissão); a exportação **audita a
  si mesma** (§1.7: "exportação também controlada... e ela própria auditada").
- Testes: `tests/test_audit.py` (8 — cadeia de hash sequencial, deny automático do guard nos dois caminhos
  imperativo e `Depends(require)` com captura de IP/UA, gate de permissão das rotas novas, exportação auto-auditada,
  isolamento por RLS). **Suíte: 564 pass / 2 ambientais (pré-existentes, `test_bot_unit`/`test_e2e_flow`, não
  relacionadas) / 0 regressões.** Achado do próprio teste de cobertura (`test_authz_coverage.py`): a rota nova
  `/internal/audit/purge` precisou entrar em `PUBLIC_PATHS` (autentica por `X-Bot-Token` no handler, não por
  dependência) — mesmo tratamento já dado a `/internal/billing/run-lifecycle`.
- **Achado pós-commit, ao investigar um teste instável sob concorrência real (2 processos `pytest` completos
  rodando ao mesmo tempo por engano contra o mesmo staging — ver D-71):** `record_event` é fire-and-forget
  (`asyncio.ensure_future`), então duas chamadas seguidas do MESMO caller **não têm ordem de conclusão garantida
  entre si** — a propriedade que a auditoria garante é a integridade do encadeamento na ordem real de commit (cada
  linha aponta pro hash da anterior por `id`), não a ordem em que o código as *chamou*. `test_hash_chain_links_...`
  assumia essa ordem e foi corrigido para verificar a integridade do encadeamento numa janela de linhas (robusto a
  concorrência de outros testes/requests na mesma org), não um par específico. **Débito de escala observado (não
  regressão):** como todo evento de uma org serializa por um único `pg_advisory_xact_lock`, uma rajada MUITO grande
  de escritas concorrentes na MESMA org pode enfileirar e segurar conexões do pool enquanto espera o lock — sob
  tráfego real de uma barbearia (dezenas, não milhares, de requests concorrentes) isso não é esperado ser um
  problema; revisitar se algum dia o volume por org crescer muito.

**Frontend (submódulo `barbearia-frontend`):**
- `/admin/seguranca/auditoria` (`hooks/use-audit.ts` + página própria, molde `/admin/seguranca/sessoes`): timeline
  com filtro por ação (busca), resultado (`SegmentedControl` Todos/Permitido/Negado), período, paginação, linha
  expansível com `before`/`after`/motivo, botão "Exportar CSV" (mesmo padrão de download-por-blob do
  `useDownloadCsv` do Financeiro). Item **"Auditoria"** novo na sidebar (grupo CONFIGURAÇÕES, ao lado de
  "Sessões"), gated por `security.audit.view` via `usePermissions()` — decisão de escopo: manter a estrutura plana
  atual em vez de introduzir o grupo "Segurança" com sub-abas do `ARQUITETURA_ALVO.md §1.12` (fica para quando
  "Papéis & Permissões"/"Privacidade" também tiverem tela, evita um grupo com um item só).
- Validado no browser (dev local, dados reais da org 1): bloqueio/desbloqueio de um cliente e a própria
  exportação da auditoria aparecem corretamente na timeline (ator, ação, recurso, resultado, hora); filtro
  "Negado" filtra de fato; `tsc --noEmit` e `eslint` limpos nos arquivos novos.

**✅ Commitado 2026-07-09** (backend `0a0427c` + frontend `ecc071e`, direto na main, molde D-67/D-68/D-69).
**✅ DEPLOYADO em prod 2026-07-09** — carona no deploy do D-72 (sessão paralela, backend `58112ea`): migration
`0039` aplicada em prod (head na época `0040`, incluindo D-72). **Pendente:** agendar
`POST /internal/audit/purge` no n8n (mesmo molde dos demais crons — sem cron, a retenção configurada em
`audit_retention_months` fica sem efeito prático, só a coluna existe).

### D-71 — Painel de segurança para gestores (Fase 5 do plano de Segurança) — 2026-07-09 (✅ DEPLOYADO em prod)

Fase 5 do `promptseguranca.md` (`ARQUITETURA_ALVO.md §3`, item 4): "dashboard de segurança (logins, negados,
dispositivos, exportações, mudanças de permissão) + alertas de anomalia". Construído inteiramente **sobre o
`audit_logs` do D-70** — nenhuma tabela nova, nenhuma migration.

**Backend:**
- `app/services/security_dashboard.py::dashboard_summary(db, org, days)` — agregações puras sob RLS: série diária
  de logins (`action=auth.login`, `result=allow`) × tentativas negadas (`result=deny`) via `local_date()` (mesmo
  helper de fuso local do financeiro/agenda, não UTC); 7 cards (logins, usuários ativos — distintos com evento no
  período —, negados, dispositivos conectados — `sessions` sem `revoked_at` —, exportações, mudanças de permissão
  — `security.roles%`/`security.users%`/recurso `user_role`/`permission_override`/`role`, hoje tipicamente 0 porque
  essas rotas ainda não existem (D-70) —, ações críticas — tudo que não é `auth.*` e foi permitido); top 5 ações
  mais negadas; últimas 5 negações (ator/ação/motivo/hora).
- **Alerta de anomalia** (`_detect_anomaly`): compara as negações de hoje com a média dos 7 dias anteriores;
  dispara só se **hoje ≥ max(5, 3× a média)** — limiar mínimo absoluto evita alarme por ruído em bases pequenas
  (mesma cautela do D-69: heurística inicial, sem base real de incidentes para calibrar ainda).
- `GET /admin/security/dashboard?days=` (7–90, default 30) — **reaproveita `security.audit.view`** (D-67) em vez
  de criar permissão nova: o painel é construído em cima do mesmo dado/mesma audiência da tela de Auditoria, e uma
  permissão nova exigiria re-sync do catálogo (`scripts/sync_authz_catalog.py`) em cada ambiente sem ganho real de
  granularidade.
- Testes: `tests/test_security_dashboard.py` (6 — permissão, shape da resposta, reflexo de um deny recente nos
  cards/top/recent, heurística de anomalia unitária em 3 cenários).

**Frontend (submódulo `barbearia-frontend`):**
- `/admin/seguranca` (`hooks/use-security-dashboard.ts` + página própria): 7 `StatCard`s, gráfico de barras
  logins×negados por dia (CSS puro com tooltip, mesmo molde de `DreBars` do Financeiro — sem lib de gráfico, ver
  `AGENTS.md`), banner de anomalia (quando presente), listas "Ações mais negadas"/"Últimas negações". Item
  **"Segurança"** novo na sidebar (grupo CONFIGURAÇÕES, antes de "Sessões"/"Auditoria"), gated por
  `security.audit.view`. `tsc --noEmit` e `eslint` limpos.
- **Validação visual pendente:** a rota backend foi confirmada via `curl` autenticado (JSON correto, 7 dias de
  série, cards coerentes com dados reais da org 1). A checagem no browser (extensão Chrome) falhou com um erro
  persistente da própria ferramenta ("Frame with ID 0 is showing error page") que não cedeu após várias tentativas
  em abas novas — não foi possível confirmar visualmente nesta sessão; recomendado revisar manualmente.

**Achado colateral desta fase — deadlock real sob `pytest`, não só flakiness:** investigar um teste instável
(`test_audit.py::test_hash_chain_links_sequential_events`) levou a um bug estrutural genuíno. `record_event`
(D-70) é fire-and-forget (`asyncio.ensure_future`) — o event loop **function-scoped** do `pytest-asyncio` fecha
entre testes, e uma Task de auditoria ainda em voo fica órfã. Pior: **3 testes fazem `DELETE` síncrono** (engine
bloqueante, `sqlalchemy.create_engine`) em `users`/`organizations` logo depois de ações que disparam auditoria
(`test_auth_sessions.py`, `test_platform.py`, `test_billing_integration.py`) — a chamada síncrona bloqueia a
THREAD inteira esperando um lock (FK `audit_logs.actor_user_id`/`organization_id`) que só seria liberado pelo
próprio event loop que essa mesma chamada está impedindo de rodar. **Deadlock real**, observado travando o
processo por 8-9 minutos até ser morto (`kill -9`) — reproduzido 3 vezes até o diagnóstico ficar claro (a sessão
paralela do D-72, batendo no mesmo Postgres de staging ao mesmo tempo, também esbarrou nisso e fez sua própria
limpeza de transações penduradas — ver nota do D-72). **Produção não tem esse risco** (um único event loop vive
pela vida do processo; não há chamada síncrona bloqueante no caminho de request). Fix: `tests/conftest.py` ganhou
uma fixture `autouse` (`_flush_audit_tasks`) que esvazia as Tasks pendentes no teardown de **todo** teste, mais
`await wait_for_pending()` explícito imediatamente antes de cada uma das 3 limpezas síncronas identificadas.
Depois do fix, suíte completa rodou limpa e rápida (~76s, sem travar) múltiplas vezes seguidas.

**✅ Commitado 2026-07-09** (backend `64ff540` + frontend `80aded5`, direto na main, molde D-67/D-68/D-69/D-70).
Suíte completa (limpa, um único processo, sem o deadlock): **576 pass / 2 ambientais (pré-existentes,
`test_bot_unit`/`test_e2e_flow`) / 0 regressões reais** (uma 3ª org de teste órfã, id 274, sobrou de uma execução
morta à força **antes** do fix — purgada em seguida, autorizada pelo dono).
**✅ DEPLOYADO em prod 2026-07-09** — carona no deploy do D-72 (sessão paralela, backend `58112ea`).
**Reparo notado por essa sessão:** o bump do submódulo `barbearia-frontend` para `80aded5` tinha ido para a main
do monorepo sem o push correspondente no repo do frontend — corrigido lá (lição: sempre pushar o submódulo antes
do monorepo).

### D-72 — Central de Operações com regras configuráveis (M11) — 2026-07-09

**Contexto:** os limiares dos alertas do superadmin eram hardcoded no `GET /platform/alerts` (SA-D10). Com o
SaaS abrindo para várias empresas, o dono precisa calibrar a régua operacional (quando alertar, com que
severidade, quais regras valem) sem redeploy — e o health score (D-69) pedia uma regra própria.

**Decisão:** migration **0040** cria `platform_alert_rules` (molde ESTRITO de `platform_admins`: sem RLS, sem
GRANT, acesso só via SECURITY DEFINER `app_platform_alert_rules_list/rule_set`), uma linha por `kind`, semeada
reproduzindo o comportamento original + regra nova:
`payment_overdue` ≥1d (crítico) · `trial_ending` ≤7d (aviso) · `onboarding_stuck` >7d (aviso) ·
`inactive_account` ≥30d (aviso) · `webhook_failures` ≥1 (crítico) · **`health_at_risk` score <40 (aviso, novo)**.
CHECKs (kind/severity/threshold 0–1000) espelhados no ORM (`PlatformAlertRule`). Semântica do threshold por
kind documentada na migration.

**API:** `GET /platform/alert-rules` (com label/descrição/unidade — o frontend não conhece kinds) e
`PUT /platform/alert-rules/{kind}` (valida faixa; health ≤100; audita `alert_rule_updated` em
`platform_audit_log`). `GET /platform/alerts` refatorado para ser dirigido pelas regras: regra desligada não
roda (nem paga o custo da consulta), threshold/severity vêm do banco; regra `health_at_risk` alerta por org
não-suspensa com score abaixo do limiar (top 3 motivos no detail).

**Superadmin (submódulo):** botão "Configurar regras" na Central de Operações abre painel inline com linha por
regra (Ativa/Desligada, limiar com unidade, severidade Crítico/Atenção/Info, salvar por linha com validação e
último editor visível). Testes: `tests/test_platform_alert_rules.py` (defaults do seed, PUT+auditoria,
validações, "todas desligadas → zero alertas", coerência health_at_risk × /platform/health).

**✅ DEPLOYADO em prod 2026-07-09** (backend `58112ea` + superadmin `775fd71`, bump `10143b0`; molde D-60/D-69):
backup `~/predeploy_d72_*.sql` → pull → **migrations `0039`+`0040`** aplicadas (head `0040`; seed das 6 regras
conferido no banco) → rebuild backend+frontend+superadmin, todos healthy. **Este deploy carregou junto D-70 e
D-71** (já estavam na main local; push desta sessão os publicou). **Reparo no caminho:** o bump do submódulo
`barbearia-frontend` para `80aded5` (D-71) tinha ido para a main do monorepo SEM o push correspondente no repo
do frontend — `git submodule update` quebrava em qualquer clone (visto na VM). Corrigido pushando `80aded5`
(já commitado na main local do submódulo). Lição: **ao bumpar ponteiro de submódulo, pushe o submódulo ANTES
do monorepo.** Smoke: `/health` 200 · `/platform/alert-rules`, `/platform/alerts` e `/admin/security/dashboard`
(D-71) 401 sem token · `admin.` 307 e tenant 307 · bundle do superadmin com `SUPERADMIN_API_URL` correto (D-69)
· logs limpos. **Validado com login real do dono em 2026-07-09** (edição de regras funcionando no painel).
Pendências herdadas do D-70 seguem: cron n8n de `POST /internal/audit/purge`.

### D-73 — Configuração de visibilidade do site público do cliente final (Fase 6 do plano de Segurança) — 2026-07-09 (✅ DEPLOYADO em prod 2026-07-15, junto com D-74/D-76)

Fase 6 do `promptseguranca.md` (`ARQUITETURA_ALVO.md §1.9`): "telas de configuração do que aparece no site
público de agendamento". **Escopo combinado com o dono antes de começar:** o site público em si **não existe**
no produto (confirmado na Fase 0 da auditoria) — construir só a CONFIGURAÇÃO (não descartável: quando o site
público entrar no roadmap, só passa a consumir o que já existe aqui) em vez de pular a fase ou simular consumo.

**Backend:**
- `client_visibility_settings` (migration **0041**, head `0041` — encadeada em `0040_platform_alert_rules`, a
  migration do D-72 já era o head no disco compartilhado desta sessão): 1 linha por org (`organization_id` é a
  própria PK, sem `id` separado), RLS + `FORCE ROW LEVEL SECURITY` explícito. Diferente do `audit_logs` (D-70,
  append-only): aqui o gestor edita repetidamente, então `barber_app` recebe `SELECT`/`INSERT`/`UPDATE` (com
  `UPDATE`, ao contrário do D-70). Campos: `services`/`professionals` (`{mode: all|custom, ids: []}`),
  `show_hours`/`show_reviews`/`show_promotions` (bool), `banner` (`{enabled, image_url, title, subtitle,
  cta_label, cta_url}`), `public_info` (`{address, phone, whatsapp, instagram, website}`), `updated_by`/`updated_at`.
  **Bug pego na hora**: o default JSONB do banner (`'{"enabled": false}'`) quebrou a migration na primeira
  tentativa — `sa.text()` interpreta `:false` como bind parameter (renderizou `NULL` em vez do literal),
  mesma pegadinha de dois-pontos dentro de string; corrigido trocando por `sa.literal_column()` (não faz esse
  parsing). Migration falhou e fez rollback limpo (transacional) antes do fix — sem sujeira no banco.
- `GET/PUT /admin/security/site-visibility` (`app/services/site_visibility.py::get_or_create` — lazy-create do
  registro no primeiro acesso, com defaults) — **reaproveita `security.site_visibility.manage`**, já no catálogo
  desde o D-67, sem permissão nova. `PUT` audita a mudança (`settings.site_visibility.update`, D-70).
  **Bug pego pelos próprios testes**: os dois handlers chamavam `db.commit()` manualmente **dentro** do escopo
  de `session.begin()` da dependência `get_tenant_db` — o commit explícito fecha a transação da própria
  dependência, e qualquer query seguinte no mesmo handler quebra com `Can't operate on closed transaction
  inside context manager`. Como quase toda outra rota do arquivo não commita explicitamente (a dependência
  commita sozinha ao fim do request), a correção foi só remover os dois `db.commit()` — nunca era necessário.
- **Sem endpoint público de leitura ainda** (decisão explícita, ver escopo acima) — fica para quando o site
  público entrar no roadmap do produto; reusaria `app_org_id_by_subdomain` (D-54) para resolver a org sem tenant,
  como o `ARQUITETURA_ALVO.md §1.9` já previa.
- Testes: `tests/test_site_visibility.py` (5 — permissão do GET/PUT, lazy-create com defaults, PUT reflete no
  GET seguinte, evento de auditoria emitido).

**Frontend (submódulo `barbearia-frontend`):**
- `/admin/seguranca/visibilidade`: seletor Todos/Selecionados para serviços e profissionais (lista de checkboxes
  reaproveitando `useServicos`/`useEquipe` já existentes — sem endpoint novo só para listar), toggles Sim/Não
  (`SegmentedControl`, sem criar um componente `Switch` novo — nada no design system pedia um antes), seção de
  banner condicional (só mostra os campos quando "Exibir banner" = Sim) e informações públicas. Item **"Visibilidade
  do site"** na sidebar (grupo CONFIGURAÇÕES, gated por `security.site_visibility.manage`). `tsc --noEmit` e
  `eslint` limpos.
- **Validação visual não concluída** (mesma falha persistente da ferramenta de browser das Fases 4/5 — "Frame
  with ID 0 is showing error page"); rota confirmada via `curl` autenticado com o shape e defaults corretos.

**Nota de concorrência:** esta sessão trabalhou o tempo todo ao lado de uma sessão paralela (D-72, modelo Claude
Fable 5) no MESMO diretório de trabalho — não um worktree separado. Cuidados tomados: nunca `git add -A`/`.`
(sempre lista explícita de arquivos própria), migration nova sempre encadeada no head real do disco (não
assumido), verificação de `git status`/`git diff --stat` antes de cada commit para confirmar que só entravam
arquivos próprios. A sessão paralela acabou fazendo `git push` + deploy em prod do que já estava commitado
localmente por mim (D-70/D-71) — ver nota no D-72 acima.

Suíte completa após a Fase 6: **582 pass / 2 ambientais (pré-existentes) / 0 regressões**, ~82s, sem travar.
**✅ Commitado 2026-07-09** (backend `efde6fc` + frontend `5eff95d`, direto na main, molde D-67/D-68/D-69/D-70/D-71).
**✅ DEPLOYADO em prod 2026-07-15** — migration `0041` aplicada no deploy combinado do D-76 (backend `51f6125`);
detalhes de backup/validação na entrada D-76.

### D-74 — Direitos do titular + histórico de consentimento (Fase 8 do plano de Segurança) — 2026-07-09 (✅ DEPLOYADO em prod 2026-07-15, junto com D-73/D-76)

Fase 8 do `promptseguranca.md` (`ARQUITETURA_ALVO.md §1.11`). **Escopo recortado** (mesmo espírito do D-73):
banner de cookies / central de preferências por categoria / Consent Mode fazem sentido para um site público com
cookies de analytics/marketing — que não existe (`promptsitepublico.md`, ainda não iniciado). Construído aqui só
o que já tem valor real HOJE sobre dado que já existe: histórico de consentimento do WhatsApp (evolui o opt-in/
opt-out do D-51) e os dois direitos do titular mais concretos (exportar e ser esquecido), aplicáveis aos ~2.900
clientes reais já importados da Trinks (D-56).

**Backend:**
- **`consent_records`** (migration **0042**, head `0042`): histórico **append-only** (molde `audit_logs`/D-70:
  RLS+FORCE, só `SELECT`/`INSERT` para `barber_app`) — evolui `client_consents` (D-51) **sem substituí-la**:
  `client_consents` continua sendo o estado atual, lido por `reminders.py`/`reactivation.py` antes de disparar
  mensagem proativa; `consent_records` é o log completo (canal, status, origem, IP, quando) de cada mudança, para
  prova de consentimento numa auditoria de verdade. `app/services/consent.py::record_consent` — chamado a partir
  de `opt_out.py::register_opt_out` (opt-out por palavra-chave) e `lead_funnel.py` (opt-in implícito no primeiro
  contato via bot) **sem alterar o comportamento existente** de nenhum dos dois (puramente aditivo).
- **`clients.anonymized_at`** (aditivo) + `app/services/lgpd.py`:
  - `export_client_data`: dados do titular (cadastro, fidelidade, agendamentos, assinaturas, consentimentos) em
    JSON portável.
  - `anonymize_client`: remove nome/telefone/e-mail/nascimento/observações/fotos — **preserva `Payment`/
    `AppointmentItem` intocados** (a receita já reconhecida não pode sumir do relatório financeiro, conforme
    `ARQUITETURA_ALVO.md §1.11: "anonimiza PII, preserva agregados financeiros"`). Telefone vira um placeholder
    sintético único (`+1000000000<id>`) — não pode ser `NULL`/vazio (`CHECK` de formato E-164 + `UNIQUE` por org
    na própria tabela `clients`).
- **Ambas ações são gestor-assistidas**, não self-service: não existe portal do cliente final ainda
  (`promptsitepublico.md`) — o titular pede por telefone/WhatsApp e o gestor executa em
  `/admin/security/lgpd/*` (`app/api/lgpd.py`, router novo — `security.py` já ia em 425 linhas). Gated por
  `privacy.lgpd.manage`, que no catálogo (D-67) é **owner-only** (excluído até do `manager`) — decisão deliberada
  de origem: dado de titular externo é sensível demais para delegar por padrão. Ambas as ações auditam a si
  mesmas (`privacy.lgpd.export`/`privacy.lgpd.anonymize`, D-70).
- **Fora de escopo desta sessão** (decisão explícita): banner de cookies, central de preferências por categoria,
  Consent Mode, retenção configurável por tipo de dado (a de auditoria já existe, D-70) — ficam para quando
  houver um site público de verdade ou tracking de terceiros a governar.
- Testes: `tests/test_lgpd.py` (7 — permissão de export/anonimização, shape do export, 404 de cliente
  inexistente, PII realmente removida após anonimizar, evento de auditoria emitido, `register_opt_out` passa a
  gravar em `consent_records` além de `client_consents`).

**Frontend (submódulo `barbearia-frontend`):**
- Tela de Clientes ganhou 2 ações novas no menu de cada linha (`cliente-row.tsx`), visíveis só para quem tem
  `privacy.lgpd.manage` (owner): "Exportar dados (LGPD)" (baixa o JSON) e "Anonimizar (LGPD)" (diálogo de
  confirmação destrutivo, molde `DeleteClienteDialog`, invalida a lista de clientes ao concluir). Sem tela
  dedicada nova — o ponto de entrada natural é a própria ficha do cliente, não um painel separado.
- `tsc --noEmit` e `eslint` limpos. Validação visual no browser não concluída (mesma falha persistente da
  ferramenta desde a Fase 4); fluxo completo (criar cliente → exportar → conferir JSON) validado via `curl`
  ponta a ponta no backend de dev.

Suíte completa: **589 pass / 2 ambientais (pré-existentes) / 0 regressões**, ~81s.
**✅ Commitado 2026-07-12** (backend `afed2a4` + frontend `60de9c3`, direto na main, molde D-67…D-73). Mesmo
commit versionou `promptseguranca.md` pela primeira vez (estava untracked desde o início da iniciativa) e criou
`promptsitepublico.md`. **✅ DEPLOYADO em prod 2026-07-15** — migration `0042` aplicada no deploy combinado do
D-76 (backend `51f6125`); detalhes de backup/validação na entrada D-76.

### D-75 — Fase 9: revisão final da iniciativa de Segurança/Governança — 2026-07-13 (checkpoint, sem código)

Checkpoint obrigatório de encerramento do `promptseguranca.md` (Fases 0-8 endereçadas: D-67…D-74). Produzido
`FASE9_REVISAO_FINAL.md` (raiz do repo) com: checklist V1-V29 verificado **no código atual** (não no plano),
matriz completa papel×permissão, runbook de criação de papel/permissão, ADRs resumidos e plano de rollout.

**Resultado da verificação, achado por achado (agente dedicado, cruzando `AUDITORIA_SEGURANCA.md` × código real):**
**12 resolvidos** (V2, V4, V5, V6, V7, V9, V10, V11, V12, V13, V19, V23), **4 parciais** (V3, V8, V16, V21), **13
em aberto** (V1, V14, V15, V17, V18, V20, V22, V24*, V25, V26, V27, V28, V29). *V24 é aceite consciente já
registrado (D-2/histórico), não pendência real.

**O item que importa mais: V1 (Crítica) segue aberto** — `WA_WEBHOOK_SECRET` continua opcional em
`app/api/wa_webhook.py:59`. Não é negligência: o webhook já recebe tráfego real do WhatsApp em produção, e
tornar o secret obrigatório no código sem confirmar que a Evolution API da VM já envia o header
`X-Webhook-Secret` derrubaria o bot em prod. Fix é trivial (poucas linhas) — **aguardando confirmação do dono**
de que o secret já está configurado nos dois lados antes de flipar para fail-closed.

Demais itens abertos classificados em `FASE9_REVISAO_FINAL.md` §2/§3: alguns exigem decisão do dono antes de
mexer (V29 reescreve histórico git — destrutivo; V22 CORS mexe em middleware que toda requisição passa), outros
são seguros para corrigir numa sessão futura sem dependência externa (V14/V15/V16/V17/V18/V20/V25/V26/V28).

**Sem código nesta entrada** — é só o checkpoint de revisão. Próxima ação depende da decisão do dono sobre os
itens da seção 2 do `FASE9_REVISAO_FINAL.md`.

### D-76 — Fase 9: fechamento em lote dos achados de baixo risco (V1, V14-V18a, V25, V26, V28) — 2026-07-14

Continuação do D-75: o dono confirmou o secret do WhatsApp e autorizou "os dois, nessa ordem" — primeiro fechar
os achados de baixo risco sem dependência externa, depois um deploy único combinado (ver plano em
`FASE9_REVISAO_FINAL.md` §7).

**V1 (Crítica) — resolvido em produção, sem deploy de código:** `WA_WEBHOOK_SECRET` gerado e configurado nos
dois lados — `.env` da VM e header `X-Webhook-Secret` na config do webhook da Evolution API
(`/webhook/set/{instance}`). Testado ao vivo: requisição sem o header ou com valor errado → `401`; com o valor
correto → `200`. O código (`app/api/wa_webhook.py`/`config.py`) já era fail-closed quando o secret está setado —
o achado sempre foi de configuração de infra, não de lógica.

**Fixes de código (commitados, aguardando deploy — migration `0043`):**
- **V14** (PII em log) — `app/core/phone.py::mask_phone` (mantém DDI+DDD+últimos 3 dígitos) aplicado em todo
  `_logger.*(...phone...)` de `wa_webhook.py`, `bot.py`, `chatwoot.py`, `whatsapp.py`.
- **V15** (dados de cliente ao OpenAI) — `kernel_ia_finance.py::redact_for_llm` tira o nome do cliente do bloco
  de texto **antes** de virar prompt do LLM (só o tópico `inativos` lista nome por linha hoje); o relatório que
  o gestor vê no chat continua com o nome real — só o que vai pro OpenAI é anonimizado. `guard_insight` segue
  validando apenas números.
- **V16** (tabelas de plataforma sem `REVOKE`) — confirmado design intencional (acesso só via `SECURITY
  DEFINER`, molde D-55); `scripts/setup_local.sh` agora revoga explicitamente `platform_admins`,
  `platform_alert_rules`, `platform_audit_log`, `platform_onboarding_overrides`, `platform_org_notes` do
  `barber_app` depois do `GRANT ON ALL TABLES` genérico, fechando a brecha de setup local.
- **V17** (`appointment_items` sem RLS própria) — migration `0043` denormaliza `organization_id` (sempre igual
  ao da `Appointment` pai; backfill via `UPDATE ... FROM appointments`), cria índice + RLS + `FORCE`; os 4 pontos
  de criação (`agenda.py`, `bot.py`, `membership.py`, `trinks_appointments.py`) passam a setar o campo.
- **V18a** (`webhook_events` sem RLS) — mesma migration, política "global OU tenant"
  (`organization_id IS NULL OR organization_id = NULLIF(current_setting(...), '')::bigint`) porque a linha pode
  chegar antes da org ser resolvida (nullable de propósito, D-32).
- **V25** (confusão de tipo no `state` OAuth do Google Calendar) — `integracoes.py::_build_state`/`_verify_state`
  ganham `typ="oauth_state"` dedicado no payload do JWT, rejeitando token de outro tipo reaproveitado no fluxo.
- **V26** (advisory lock com f-string) — `agenda.py:305`, `bot.py:905`, `membership.py:768` trocados para bind
  parameter (`text("SELECT pg_advisory_xact_lock(:unit_id)"), {"unit_id": ...}`); não era explorável hoje (sem
  input externo no valor), mas fecha o padrão perigoso antes que alguém copie o molde para um caso injetável.
- **V28** (`except Exception` mascarando erro como sucesso) — só em `platform_billing.py::create_coupon`: agora
  captura especificamente `IntegrityError` → `409` ("já existe"); qualquer outra exceção propaga. `wa_webhook.py`
  e `chatwoot.py` foram **revistos e mantidos como estão** — o ack `200` ali é design deliberado anti-retry-storm
  do provedor, com log de erro real por trás, não mascaramento silencioso.

**V18b (`coupons`) tentado e revertido — fica registrado como lição:** a primeira versão da migration `0043`
também revogava `INSERT`/`UPDATE`/`DELETE` em `coupons` do `barber_app`. Quebrou o resgate real de cupom em
staging (`permission denied for table coupons`) porque **todas** as rotas — tenant e plataforma — compartilham a
mesma conexão `barber_app`; não existe um papel elevado separado para rotas de plataforma como existe para
`platform_admins`/`platform_audit_log` (que só são acessíveis via função `SECURITY DEFINER`, D-55). `coupons` é
catálogo global de verdade (sem `organization_id`, RLS não se aplica). Corrigir de verdade exige mover a escrita
para uma função `SECURITY DEFINER` no molde do D-55 — fora do escopo desta sessão; a migration final **não
mexe em `coupons`**. **V18b segue aberto.**

**Segundo achado real durante o desenvolvimento — GUC residual em conexão pooled:** a política "global OU
tenant" do V18a inicialmente usava `current_setting('app.current_org_id', true)::bigint` direto. Sob a suíte
completa (conexões reaproveitadas do pool), estourava `invalid input syntax for type bigint: ""` — numa conexão
que já teve `set_current_org` chamado antes (LOCAL-scoped) e cuja transação encerrou, o valor reverte para
string vazia `''`, não `NULL`. Só afetava `webhook_events` porque é a única tabela com RLS acessada por sessão
sem tenant (`_mark_webhook` usa uma `AsyncSessionLocal()` fresca, sem `set_current_org`); as demais tabelas
sempre passam por `get_tenant_db`/`get_bot_db`, que sempre setam o GUC primeiro. Corrigido com
`NULLIF(current_setting(...), '')::bigint`.

**V20 (debounce cross-tenant) — adiado conscientemente, não corrigido:** chavear o debounce por org exigiria o
n8n (workflow na VM) passar o header `X-Instance` aos nós HTTP de Debounce/Flush — hoje não passa (`grep` em
`workflows.json` = 0 ocorrências). Mudar só o backend sem isso não resolve nada; fica para quando o bot for
multi-tenant de verdade (mesmo gatilho do V21, já parcial).

**Testes:** suíte completa **589 pass / 2 falhas ambientais conhecidas / 0 regressões**, confirmado limpo em 2
execuções consecutivas. Durante o desenvolvimento, pollution numa staging DB muito reutilizada (15-20+ runs
completos na mesma sessão) causou falhas intermitentes em `test_platform_alert_rules.py`,
`test_platform_alerts_audit.py`, `test_membership_corrections.py`, `test_membership_integration.py`,
`test_lgpd.py` — todas passam isoladas, confirmadas como ruído de ambiente, não regressão real.

**Documentação:** `FASE9_REVISAO_FINAL.md` atualizado (checklist V1-V29, sumário executivo, seções 2/3, ADRs,
plano de rollout).

**✅ DEPLOYADO em prod 2026-07-15** (backend `51f6125`, direto na main; molde D-59/D-63/D-65/D-67/D-68 — deploy
único combinando D-73 + D-74 + D-76): backup `~/predeploy_d76_20260715_024101.sql` → `git stash` (VM tinha o
digest do Evolution pinado localmente em `docker-compose.yml`, mesmo resíduo do D-68) → `git pull --ff-only`
(head `0040`→`51f6125`, sem recursar submódulo — frontend não mudou neste lote) → `git stash pop` → **migrations
`0041`→`0042`→`0043`** aplicadas em sequência via repo do host montado (`-v /opt/barbeariapro:/repo:ro -w /repo`,
superuser `postgres`, molde D-60/D-67) → rebuild `backend`. **Validado em prod:** `alembic current` = `0043`
(head); `appointment_items` com backfill 100% (115/115 linhas com `organization_id`); `relrowsecurity`/
`relforcerowsecurity` = true em `appointment_items` e `webhook_events`; `/health` 200 (HTTPS); rotas novas
protegidas (`/admin/security/site-visibility` 401, `/admin/security/lgpd/clients/{id}/export` 401,
`/platform/billing/coupons` 401 — todas vivas, não 404/500); `/auth/tenant` público segue 200. **`coupons`
confirmado intocado:** GRANTs do `barber_app` (INSERT/SELECT/UPDATE) idênticos aos de antes do deploy — a
migration final nunca mexeu nessa tabela (V18b revertido ainda em staging), então o resgate real de cupom não
foi exposto a risco nesta produção.

### D-77 — Kernel IA migrado da OpenAI para a API do Claude (Anthropic) — 2026-07-15

**Contexto.** A `OPENAI_API_KEY` de prod está inválida desde 2026-07-02 (Kernel IA D-57/D-58 inteiro fora do ar,
degradando com graça em `action=config`). Como seria preciso rotacionar chave de qualquer forma, decidiu-se
trocar o provedor do Kernel IA de OpenAI (`gpt-4o-mini`) para **Anthropic/Claude** (`claude-opus-4-8`,
configurável via `KERNEL_IA_MODEL`). O bot "Raquel" no n8n **não** foi tocado (segue OpenAI; decisão separada).

**O que mudou (só camada de provedor — contrato, RBAC e guardrails intactos):**
- `app/core/config.py`: `openai_api_key` → `anthropic_api_key` (`ANTHROPIC_API_KEY` no `.env`);
  `kernel_ia_model` default `gpt-4o-mini` → `claude-opus-4-8`.
- `app/services/kernel_ia.py`: SDK `anthropic` (`AsyncAnthropic`, import tardio como antes); tools no formato
  Claude (`name`/`description`/`input_schema` — antes `function.parameters`); loop de tool-use com blocos
  `tool_use`/`tool_result` (o `input` já vem parseado → helper `_json` removido); `system` como parâmetro
  top-level; **sem `temperature`** (removida na API do Opus 4.8 — enviar dá 400); insight do D-58 com
  `max_tokens=150`. Chave inválida → `AuthenticationError` → mesma degradação `action=config` de antes.
- `requirements.txt`: `openai>=1.40` → `anthropic>=0.69` (nada mais no backend importava `openai`).
- Testes: shape das tools atualizado (`t["name"]`), skip por `anthropic_api_key`. **Suíte 589 pass / 2
  ambientais / 0 regressões** (o 3º fail intermitente `test_excluir_venda_sem_uso` passa isolado — ruído de
  ordenação já visto no D-76).

**O que NÃO mudou:** catálogo fechado de rotas, mensagens templadas, `guard_insight` fail-closed,
`redact_for_llm` (V15/LGPD), RBAC por papel (recepção/barbeiro sem `consultar_financas`), contrato do endpoint
(`action ∈ {navigate, reschedule, finance_answer, answer, config, erro}`) — frontend não precisa de mudança.

**Custo:** Opus 4.8 ($5/$25 por MTok) > `gpt-4o-mini`; volume atual é baixo (chat interno do gestor). Se o
custo incomodar, trocar `KERNEL_IA_MODEL=claude-haiku-4-5` ($1/$5) sem mexer em código. O débito "sem rate
limiting em `/kernel-ia/query`" continua valendo (agora com custo maior por chamada).

**✅ DEPLOYADO em prod 2026-07-15** (backend `5cea9af`, direto na main; molde D-76 — sem migration): backup
`~/predeploy_d77_*.sql` → `git merge --ff-only origin/main` (`51f6125`→`5cea9af`, sem stash — o lote não toca o
`docker-compose.yml` com digest pinado) → rebuild `backend`. **Validado:** container healthy; `anthropic 0.116.0`
na imagem e `openai` removido (import falha, como esperado); `/health` 200 (HTTPS); `/kernel-ia/query` sem auth
→ 401.

**Pendente:** `ANTHROPIC_API_KEY` **confirmada ausente no `.env` da VM** — até ser provisionada (criar em
console.anthropic.com → `/opt/barbeariapro/.env` → `docker compose up -d backend`, sem rebuild), o Kernel IA
responde `action=config` ("falta ANTHROPIC_API_KEY"), mesma degradação graciosa de antes. Depois disso, validação
manual "LLM real" (navegação + finanças) — pendência herdada do D-58. A `OPENAI_API_KEY` da VM fica só para o n8n.

### D-78 — Arquitetura de domínios do site público: apex = cliente final, `app.` = portal da equipe — 2026-07-16 (decisão, nada implementado)

**Contexto:** análise do `promptsitepublico.md` (site público de agendamento, iniciativa ainda não iniciada)
cruzada com a logística atual (nginx, `lib/tenant.ts`, CORS regex do D-66, `client_visibility_settings` do D-73).
Hoje o nginx serve o painel da equipe tanto no apex quanto em qualquer subdomínio
(`taylorethedy.com` e `*.taylorethedy.com` → :3000).

**Decisão do dono (substitui o rename `org.taylorethedy.com` registrado no D-66):**
- **`taylorethedy.com` (apex)** = site público do cliente final, com a **logo da Taylor & Thedy** em destaque.
- **`app.taylorethedy.com`** = portal dos profissionais/gestores da org 1 (o painel que hoje responde em
  `taylor.taylorethedy.com`).

**Plano de execução (barato, independente do site em si):**
1. DNS: nada a criar — wildcard `*.taylorethedy.com` + TLS coringa (D-64) já cobrem `app.`.
2. Banco: `UPDATE organizations SET subdomain = 'app' WHERE id = 1` — o login resolve org pelo subdomínio
   (`lib/tenant.ts` → `GET /auth/tenant?subdomain=`), então funciona sem tocar em código. Trade-off aceito:
   `app` é nome genérico e fica "tomado" pela org 1 — OK porque o domínio é da própria Taylor & Thedy
   (tenants futuros terão domínio/subdomínio próprios).
3. nginx: server block dedicado ao apex apontando para o futuro serviço do site público (ex.: :3200),
   deixando o wildcard para o painel (:3000).
4. CORS: nada a fazer — `CORS_ORIGIN_REGEX` já cobre apex + qualquer subdomínio.
5. Transição: manter `taylor.taylorethedy.com` com redirect 301 → `app.` por um tempo (favoritos da equipe).

**Logo:** não existe nenhum arquivo de logo no repositório (`barbearia-frontend/public/` só tem SVGs padrão do
Next). Além do asset (dono precisa fornecer SVG/PNG), a logo deve virar configuração por org: campo `logo_url`
dentro de `public_info` (JSONB do `client_visibility_settings` — sem migration) + upload futuro na tela
`/admin/seguranca/visibilidade`.

**Melhorias incorporadas ao `promptsitepublico.md`** (seção "Melhorias incorporadas — 2026-07-16" no próprio
arquivo): OTP via WhatsApp é dependência de caminho crítico (número restrito D-41, Cloud API D-49 só plano —
prever fallback SMS); endpoint de "horários disponíveis" não existe e deve nascer em `app/services/` (reúso por
painel/bot); reusar Redis (D-68) para rate limit do OTP e cache do `/public/{subdomain}/info`; auditar ações do
cliente final no `audit_logs` (D-70); merge por `phone_e164` com os ~2.913 clientes da Trinks + exibir
fidelidade/assinatura no site; SEO no apex (SSR/ISR, `LocalBusiness`, Open Graph com a logo); regras de
cancelamento/remarcação configuráveis num lugar definido; Fase 6 estende `reminders.py`, não cria canal paralelo.

**Status:** decisão registrada; nenhuma mudança aplicada (nem DNS/banco/nginx, nem código do site).
> ✅ **Executado em 2026-07-17 junto com o D-79** (site público v1): `subdomain='app'` no banco, apex → :3200,
> `taylor.` → 301 `app.`, tudo validado em prod.

---

### D-79 — Site público de agendamento do cliente final v1 (sem OTP) + execução do D-78 — 2026-07-17 (✅ DEPLOYADO em prod)

**Contexto:** `promptsitepublico.md` Fases 0–5 executadas num único ciclo. Fase 0 → `AUDITORIA_SITE_PUBLICO.md`
(achado central: a promessa "nunca mais loga" só é garantível com PWA instalado — iOS Safari ITP apaga storage
de aba solta após 7 dias de inatividade, fonte primária WebKit; cookie de servidor dura até 400 dias como
melhor esforço). Fase 1 → `ARQUITETURA_SITE_PUBLICO.md`. **Decisões do dono:** (a) **lançar sem OTP** — o
WhatsApp está restrito (D-41) e não entrega mensagens; a estrutura nasce pronta para o OTP entrar depois
(Cloud API); (b) escopo v1 = agendamento completo; (c) D-78 no pacote.

**Trade-off de segurança central (consciente, documentado):** sem verificação do telefone, a sessão do cliente
**só enxerga agendamentos criados por ela mesma** (`appointments.created_by_client_session_id`) — nunca o
histórico do telefone (impede ver dados de terceiros digitando telefone alheio). `client_sessions.verified_at`
já existe: quando o OTP chegar, sessões verificadas veem tudo e ganham rotação de token (padrão D-68/RFC 9700).
**Sem rotação nesta v1** — sem identidade verificada, rotação não agrega; entra com o OTP.

**Backend (migration `0044_public_site`, head `0044`):**
- `client_sessions` (RLS+FORCE, molde 0042; GRANT sem DELETE — sessão se revoga, não se apaga): token opaco
  256 bits, só hash SHA-256 persiste; cookie `tt_session` HttpOnly+Secure+SameSite=Lax,
  `Domain=.taylorethedy.com` (`PUBLIC_COOKIE_DOMAIN` no `.env` da VM), Max-Age 400 dias.
- `appointments.created_by_client_session_id` (FK SET NULL) + `contact_channel` += `'site'`.
- `app/services/availability.py` (novo, reusável por painel/bot): slots livres = `business_hours` da unidade
  (fuso local) − agendamentos ativos − `TimeOff`, passo 30min, antecedência mínima 30min.
- `app/api/public.py` (`/public/{subdomain}/…`): `info` (vitrine 100% gateada pelo
  `client_visibility_settings`/D-73, cache Redis 60s), `slots`, `auth/session` (merge por `phone_e164` com a
  base Trinks — nunca duplica; `is_blocked` → 403 genérico), `appointments` (cadeia de validação espelhada da
  agenda + revalidação de slot + advisory lock; preço sempre do catálogo; Google Calendar sync; lembrete 24h
  entra de graça), `me/appointments`, `me/appointments/{id}/cancel` (só `agendado` e >2h antes —
  `PUBLIC_CANCEL_MIN_HOURS`), `auth/logout`. Rate limits por rota; auditoria D-70 com `actor_kind="client"`
  (`public.session_created/appointment_created/appointment_canceled`).
- Testes: `tests/test_public_site.py` (13) + `test_authz_coverage` atualizado (`get_client_session` como
  entrypoint de auth; info/slots/session na allowlist). Suíte **603 pass / 2 ambientais / 0 regressões**.

**Frontend `barbearia-public/` (novo app Next 16, :3200, PASTA no repo do backend — não submódulo; sem
segredo no código, deploy junto no `git pull`):** home SSR/ISR (JSON-LD `LocalBusiness`, Open Graph),
`/agendar` (stepper serviço→profissional→dia/horário→identificação+confirmação; nome em localStorage só como
memória de UX — 401 refaz identificação), `/meus-agendamentos` (cancelar com regra de 2h comunicada), **PWA**
(manifest+SW mínimo+ícones gerados; banner pós-agendamento incentivando "Adicionar à Tela de Início" com
instrução específica iOS — é a mitigação do ITP, parte do produto). Design próprio (Fraunces+Archivo, paleta
carvão/couro/creme/âmbar, listra de barbeiro como assinatura). Sem next-auth; fetch com
`credentials:'include'`. Tenant fixo por env `NEXT_PUBLIC_TENANT_SLUG` (multi-tenant por host = v2).

**Infra:** serviço `public` no `docker-compose.app.yml` (sem profile — sobe no `up` padrão; build args
`PUBLIC_API_URL`/`PUBLIC_TENANT_SLUG=app`/`PUBLIC_SITE_URL`); nginx com bloco exato do apex → :3200,
`taylor.` → 301 `app.`, coringa continua → :3000 (config anterior salva em
`/etc/nginx/sites-available/barbeariapro.pre-d79.bak`).

**✅ Deploy em prod 2026-07-17** (backend `e2c85ad`, molde D-59/D-63/D-67/D-68): backup
`~/predeploy_d79_20260717_035406.sql` → migration `0044` (repo do host montado, superuser, RLS+FORCE
confirmados) → rebuild backend (`/health` 200) → build `public` → **virada D-78** (`subdomain='app'` + nginx
reload + restart do site p/ limpar ISR). **Smoke completo:** apex 200 com serviços reais renderizados; `app.`
307→login (painel OK); `taylor.` 301→`app.`; `admin.` intacto; `/auth/tenant?subdomain=app` resolve; **E2E
real em prod** (sessão→slots→agendar→cancelar→logout, cookie de 400 dias confirmado) com limpeza dos dados de
teste via psql.

**Identidade visual da fachada (2026-07-17, mesmo dia — ✅ DEPLOYADA em prod, commit `faa99e1`):** o dono
enviou foto da placa real → identidade do site refeita a partir dela: **logo recriada em SVG**
(`barbearia-public/components/logo.tsx` — ligadura dupla de "t" que serve de T para Taylor e Thedy, com a
inversão grafite/prata no quadrado claro; lockup "aylor/hedy" + slogan "Renove seu Estilo"); **paleta
grafite-azulado + prata** da placa (`#262C36`/`#ECEEF1`, substitui o carvão/âmbar herdado do painel);
**tipografia Tenor Sans** (≈ o traço flareado da placa) + **Quicksand** (≈ o rounded do slogan); ícones do
PWA/manifest regenerados com o monograma. Validado por screenshot headless (nota: Chrome headless no macOS
tem largura mínima de janela ~500 — capturas "390" saem cortadas; não é bug do layout, que é fluido).
> **Correções no mesmo dia (commits `53448cb` + `bed01a9`, deployadas):** o dono apontou que o glifo não
> batia — recortes ampliados da foto revelaram a estrutura real: **um único "t" caligráfico** dentro de uma
> caixa clara ALTA que atravessa as duas linhas (cabeça em curl à esquerda, bandeira em vírgula terminando
> na baseline do "aylor", bojo de ponta erguida na altura-x do "hedy"; a faixa fina à esquerda que parecia
> um "l" era só a borda escura da placa aparecendo na foto — confirmado pelo dono). A fonte da placa foi
> identificada por comparação lado a lado como **Optima** (sem webfont livre; Tenor Sans é o substituto
> canônico, com `textLength` compensando a largura). Monograma redesenhado em bezier iterando screenshot ×
> foto (8 versões). Se o dono conseguir a arte original do designer da placa, substituir.
> **Redesenho do lockup (2026-07-17, working tree — o dono reprovou o "t"/monograma e pediu igual à foto):**
> abandonados a caixa clara + o "t" caligráfico à mão. Agora é **arte final vetorial extraída via fontTools**
> (glifos embutidos, sem webfont): layout **horizontal fiel à fachada** — `"Taylor"` + **"T" maiúsculo
> monumental** + `"hedy"`, lendo *TaylorThedy* (o "T" grande é o de Thedy). As palavras saem da **Optima
> Regular** (a fonte da placa, escolha do dono: reta > itálica); o **"T" monumental é o "T" do Didot** —
> serif de alto contraste (barra fina com serifas, pés espalhados), o mais próximo do letreiro entre as
> serifadas do sistema (comparado lado a lado vs Times/Georgia/Baskerville/Bodoni). Paths em
> `components/logo-paths.ts` (`TAYLOR_D`/`HEDY_D` Optima em=1000, `TEE_D` Didot em=1000, `SLOGAN_D`);
> `logo.tsx` compõe com `translate()`+`scale(1,-1)` (Y do em→SVG). Validado por render headless (Chrome)
> lado a lado com a foto. **Ainda não commitado/deployado.**

**Pendências conhecidas:** validação visual num celular real (extensão Chrome não conectou —
abrir `https://taylorethedy.com` no aparelho); OTP/verificação (bloqueado pela Cloud API,
D-49); "meus dispositivos"; fidelidade/assinatura no site (v2); `public_info.logo_url` continua tendo
precedência sobre o lockup SVG se um arquivo oficial de logo for fornecido; regras de cancelamento
configuráveis (fixo 2h).

### D-80 — Hero cinematográfico com vídeo de drone na home do site público — 2026-07-17 (implementado, não deployado)

**Contexto:** a home do site público (D-79) abria com o lockup SVG estático. O dono pediu um **hero
cinematográfico** com o vídeo de drone da barbearia em tela cheia, estilo site premium 2030 — sem sacrificar
a conversão (o CTA "Agendar horário" continua sendo o 1º alvo do polegar no mobile).

**Otimização do vídeo (ffmpeg, instalado via brew):** o fonte `barbearia-public/VideoTa&TheDRONE.mp4` é 4K
(3840×2160), 30fps, ~4min, 32 Mbps, **1,1 GB**. O dono indicou que o melhor trecho começa em **2:50**. Extraído
com `-ss 170 -t 14 -an` (14s, **sem áudio**), `scale=1280:-2:flags=lanczos,fps=24`, `libx264 -profile:v main
-crf 25 -preset slow -pix_fmt yuv420p -movflags +faststart` → **`public/hero-drone.mp4` = 1,4 MB** (~820 kb/s),
dentro do alvo ~2-3 MB e leve para 4G/WhatsApp. Poster de capa do frame ~2:52 →
**`public/hero-poster.jpg` = ~100 KB** (`-frames:v 1 -q:v 4`). **`.gitignore` do app** passou a ignorar o
fonte cru (`VideoTa&TheDRONE.mp4`, `*.source.mp4`, `.DS_Store`); o otimizado + poster **são versionados**
(vivem em `public/`, deploy junto no `git pull`).

**Componente `components/hero-cinematic.tsx` (client) — SCROLL-SCRUBBING:** o efeito evoluiu do "afundar" para
**scrubbing** a pedido do dono ("passar o vídeo ao rolar"): o vídeo **não toca sozinho** — o `currentTime` é
amarrado ao scroll (rAF + listener `passive`, sem lib, sem re-render). Estrutura = wrapper alto (`h-[200svh]`)
com camada **`sticky top-0 h-[100svh]`**; o excedente de altura é o "trilho" que varre a timeline. `video`
`muted playsInline preload="auto"` + `poster` (capa antes de carregar), sem `autoplay`/`loop`. **Destrava iOS**
no 1º toque/scroll (`play()→pause()`, necessário para o seek fluir no Safari). No fim do scrub o véu grafite
escurece um toque e a dica "Role para ver" some; a marca faz leve parallax. **Respeita `prefers-reduced-motion`**
(scrub desligado → 1º quadro estático). O app público tem **tema grafite fixo** (não o toggle do admin) — só os
tokens existentes. **Vídeo reencodado com keyframes densos** (`-g 12 -keyint_min 12 -sc_threshold 0`, crf 26 →
**2,5 MB**) para o seek ficar fluido; keyframe esparso trava o scrub.

**CTA "Agendar horário" premium (`.cta-agendar` em `globals.css`):** pílula com **gradiente metálico prata
escovada** (a cara da placa), brilho superior (`inset`), **glow pulsante** (`@keyframes cta-glow`) que chama o
olhar, **facho de luz** varrendo o botão (`@keyframes cta-sheen`), **seta →** que desliza no `group-hover` e
micro-interação no toque (`active:scale`). As animações são desligadas por `prefers-reduced-motion` (media query
global já existente).

**Conversão preservada:** com o `sticky`, o CTA fica na **faixa do polegar durante todo o hero**
(`pb-[calc(env(safe-area-inset-bottom)+2rem)]`), sempre visível; a seção de Serviços (que inicia o fluxo) vem
logo abaixo do wrapper.

**Logo fiel à fachada (2026-07-18):** o dono pediu a logo do topo **igual à fachada do vídeo e do print**
(`assets/images/taylor_thedy_logo.png` — placa marinho com "Taylor" + "T" monumental + "hedy" cromado 3D +
"RENOVE SEU ESTILO", em **letra caligráfica**, que a versão SVG em Optima [D-79] não reproduzia). Em vez de
revetorizar à mão (tentado e reprovado no D-79), a logo foi **extraída da própria arte**: recorte do print →
**correção de perspectiva** (warp 4-pontos via PIL, solver Gaussiano sem numpy) → **remoção do fundo marinho**
por *blue-key* (`b−(r+g)/2`, letras cromadas são neutras/blue≈0, marinho blue≥21) + despill + curva de alpha →
**`public/logo-lockup.webp` (94 KB, 1000×472, transparente)**. `hero-cinematic.tsx` usa `<img src={logoUrl ||
"/logo-lockup.webp"}>` (o `logo_url` do org mantém precedência — regra D-79); `LogoLockup`/`logo-paths.ts` (SVG
Optima/Didot) ficam órfãos mas preservados. Se o dono conseguir a arte vetorial original do designer, trocar o
webp por ela.

**`app/page.tsx`:** o hero saiu do container `max-w-md` (agora `<HeroCinematic/>` full-bleed + `<main>` com o
resto); imports `Link`/`LogoLockup` removidos (migraram para o componente).

**Otimização do vídeo revisada para o scrub:** o alvo subiu para **2,5 MB** (crf 26, `-g 12`) — keyframes densos
são o que torna o scrubbing fluido (com `-g 6` deu 4,4 MB, além do alvo). Fonte, trecho (2:50) e "sem áudio"
inalterados.

**Validação:** `tsc --noEmit` limpo, `next build` OK (home estática, revalidate 5m), SSR renderiza o hero +
`<source src="/hero-drone.mp4">` + poster + `.cta-agendar` + logo, assets servidos (vídeo 2,5 MB / logo webp
94 KB / poster ~100 KB). Preview visual do hero (logo + botão sobre o frame do vídeo) renderizado por PIL em
viewport iPhone. **Pendente:** validação visual/scroll num celular real (a extensão do Chrome não conectou nesta
sessão — abrir a home no aparelho) e **deploy** (rebuild do serviço `public` na VM; sem migration).

## Dívida técnica conhecida (não resolver sem discussão)

| Item | Arquivo | Severidade | Observação |
|---|---|---|---|
| Sem backup dos volumes Docker da VM | infra VM | ⚠️ Alto | VM ficou TERMINATED em 2026-06-25 |
| ~~Debug print temporário no webhook~~ | `app/api/wa_webhook.py` | ✅ Resolvido | D-40: trocado por `logger.debug` (commit `13822a1`) |
| Bot responses não confirmadas no CRM | fluxo n8n + Evolution | ⚠️ Alto | Pendente confirmação end-to-end |
| ~~Frontend sem remote git funcional~~ | `barbearia-frontend/.git` | ✅ Resolvido | 2026-06-29: remote movido p/ `augustopegoraro-droid/barbearia-frontend` (privado) + submódulo registrado (`.gitmodules`) + ponteiro bumpado para `8ba47e1` |
| ~~HTTPS / domínio não configurado~~ | infra VM | ✅ Resolvido | D-64 (2026-07-05): `taylorethedy.com` + wildcard TLS (Cloudflare DNS-01) ativos em prod. |
| Portas abertas ao mundo na VM | firewall GCP | Médio (reduzido) | D-40: 5678/8080 fechadas; 5432 já fechada. Restam 8000/3000 (uso direto do browser) — mover p/ nginx+HTTPS |
| Estado do bot em memória (debounce) | `app/api/bot.py` | Médio | Restart perde estado. Aguarda Redis. |
| SSE single-process | `app/services/sse_broker.py` | Baixo | Não funciona com múltiplos workers |
| ~~Token JWT visível em query string do SSE~~ | `GET /crm/stream?token=` | ✅ Resolvido | D-68 (2026-07-09, DEPLOYADO em prod): ticket de uso único (30s) substitui o JWT na URL. |
| `workflows.json` local diverge da VM | `workflows.json` | ⚠️ Alto | Exportar da VM antes de qualquer edição local |
| Formato de telefone 8 vs 9 dígitos | DB + `normalize_phone` | Médio | conv_id=1 tem 8 dígitos. Ver D-29. |
| 3 testes ambientais falham | `tests/` | Baixo | n8n bypass_hours, RLS isolation, par `1/6` hardcoded — **não são bugs** |
| Drag da Agenda reverte silencioso em erro | `barbearia-frontend/components/agenda` | Baixo | Reagendar inválido (serviço/conflito) → 422 → bloco volta sem toast (D-43). Diálogo Reagendar mostra o erro. |
| Frontend F1–F3 não mergeado/deployado | `barbearia-frontend` branch | ⚠️ Médio | Branch `feat/design-system-react-query-f1-f3`; mergear + deployar (D-42). Inbox exige migrations 0010/0011 (prod já ok). |
| System prompt do bot hardcoda barbeiros | n8n AI Agent node | Médio | Ao cadastrar novo barbeiro, atualizar manualmente (D-38) |
| VM sem política de reinício automático | GCP VM | ⚠️ Alto | WhatsApp cai toda vez que VM reinicia; usar /admin/integracoes |
| ~~Migrations 0012–0014 + telas novas não deployadas~~ | VM / `barbearia-frontend` | ✅ Resolvido | D-46 (2026-06-27): 0012/0013 já estavam; 0014 aplicada; `/admin/assinaturas`+`/admin/empresa` deployadas. Falta só smoke test visual. |
| `ADMIN_DATABASE_URL` ausente no `.env` da VM | `/opt/barbeariapro/.env` | Médio | Só nos `.example`; `deploy/update.sh` quebra no passo de migration (`set -u`). Provisionar p/ deploy automatizado (D-46). |
| `POST /kernel-ia/query` sem rate limiting | `app/api/kernel_ia.py` | Médio | Nenhuma throttle/quota por usuário; cada pergunta financeira (D-58) faz 2 chamadas LLM (Claude desde o D-77 — custo por chamada maior que o gpt-4o-mini). |
