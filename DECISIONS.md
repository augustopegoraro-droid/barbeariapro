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
**Deploy:** via tar+SSH direto para `/opt/barbeariapro/barbearia-frontend/` na VM.
Ver PROJECT_CONTEXT §2 para o comando completo.
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
**Motivo:** Separação de concerns; sidebar e header são reutilizáveis independentemente.
**Design tokens:** dark theme fixo (classe `dark` no `<html>`), amber `#f59e0b` como cor primária.

### D-32 — CRM view inicializada via `window.location.search`, não `useSearchParams`
**Data:** 2026-06-25
**Decisão:** `useState<"board"|"inbox">(() => new URLSearchParams(window.location.search).get("view") === "inbox" ? "inbox" : "board")`
**Motivo:** `useSearchParams()` do Next.js exige `<Suspense>` boundary; sem ele,
`next build` falha com "prerender error" na rota `/admin/crm`.
A abordagem com lazy initializer evita o Suspense e funciona em client components.
**Consequência:** `/admin/conversas` redireciona para `/admin/crm?view=inbox` (server redirect).

### D-33 — `/admin/conversas` é redirect, não página separada
**Data:** 2026-06-25
**Decisão:** `app/admin/conversas/page.tsx` chama `redirect("/admin/crm?view=inbox")` (server-side).
**Motivo:** O Inbox já está implementado no CRM page como toggle. Manter uma única fonte
de UI evita duplicação. O nav item "Conversas" usa `/admin/conversas` para semântica de URL.

---

## Produto e priorização

### D-11 — Lembrete 24h é feature de alto ROI
**Data:** 2026-06-21
**Decisão:** Após estabilização do CRM, próxima prioridade é lembrete 24h antes via WhatsApp.
Infraestrutura pronta (`CronReminder24h01` ativo, nunca testado end-to-end).

### D-12 — Google Calendar sync é ROI baixo (mas foi pedido)
**Data:** 2026-06-21
**Motivo:** Pedido direto do usuário.

---

## Infraestrutura e produção

### D-13 — Produção roda na VM via docker-compose, NÃO no Cloud Run
**Data:** 2026-06-23
**Decisão:** VM GCP `barbeariapro` (`34.95.199.134`), stack em containers.
**Consequência:** Sem backup automatizado dos volumes — VM já foi zerada uma vez.

### D-14 — n8n: SEMPRE via API REST, NUNCA editar o SQLite direto
**Data:** 2026-06-23
**Decisão:** Qualquer alteração de credencial ou workflow via API REST.
**Motivo (aprendido na marra):** Criptografia do n8n v2.x é formato OpenSSL;
WAL/SHM descartam mudanças; `versionId` separa rascunho de versão ativa.
```bash
curl -s -c /tmp/n8n_cookies -X POST 'http://localhost:5678/rest/login' \
  -H 'Content-Type: application/json' \
  -d '{"emailOrLdapLoginId":"admin@barbearia.com","password":"Barbearia@2026!"}'
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
**Decisão:** nginx instalado diretamente no host da VM (não como container).
Config em `/etc/nginx/sites-available/barbeariapro`; `default_server` na porta 80
proxia para `localhost:3000` (frontend). `api.taylorethedy.com` → `localhost:8000`.
**Motivo:** Simples, sem overhead de container-para-container. Certbot integra nativamente.
**SSL pendente:** domínio `taylorethedy.app` não registrado. Quando registrado:
```bash
sudo certbot --nginx -d taylorethedy.app -d api.taylorethedy.com --redirect
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

### D-28 — Acidente n8n `user-management:reset` e recuperação
**Data:** 2026-06-24 (2ª sessão)
**Novas credenciais n8n:** `admin@barbearia.com` / `Barbearia@2026!`
**Recuperação:**
```bash
curl -X POST http://localhost:5678/rest/owner/setup \
  -H 'Content-Type: application/json' \
  -d '{"firstName":"Admin","lastName":"Admin","email":"admin@barbearia.com","password":"Barbearia@2026!"}'
```
**Lição:** Nunca rodar comandos de reset do n8n em produção.

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

---

## Dívida técnica conhecida (não resolver sem discussão)

| Item | Arquivo | Severidade | Observação |
|---|---|---|---|
| Sem backup dos volumes Docker da VM | infra VM | ⚠️ Alto | VM já foi zerada uma vez |
| Debug print temporário no webhook | `app/api/wa_webhook.py` | ⚠️ Médio | Remover após confirmar send.message |
| Bot responses não confirmadas no CRM | fluxo n8n + Evolution | ⚠️ Alto | Pendente confirmação end-to-end |
| Frontend sem remote git funcional | `barbearia-frontend/.git` | ⚠️ Médio | DoctorDCombo/barbearia-frontend não existe |
| HTTPS / domínio não configurado | infra VM | Médio | nginx pronto; falta registrar taylorethedy.app |
| Portas abertas ao mundo na VM | firewall GCP | Médio | 5678/8000/3000/8080 públicas; fechar após HTTPS |
| Estado do bot em memória (debounce) | `app/api/bot.py` | Médio | Restart perde estado. Aguarda Redis. |
| SSE single-process | `app/services/sse_broker.py` | Baixo | Não funciona com múltiplos workers |
| Token JWT visível em query string do SSE | `GET /crm/stream?token=` | Baixo | Aceitável para MVP interno |
| `workflows.json` local diverge da VM | `workflows.json` | ⚠️ Alto | Exportar da VM antes de qualquer edição local |
| Formato de telefone 8 vs 9 dígitos | DB + `normalize_phone` | Médio | conv_id=1 tem 8 dígitos. Ver D-29. |
| 2 testes hardcoded na org 3 | `tests/` | Baixo | Fail ambiental; não são bugs |
