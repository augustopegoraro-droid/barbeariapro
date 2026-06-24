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

### D-08 — Frontend é repositório git separado
**Data:** descoberto em 2026-06-21  
**Decisão:** `barbearia-frontend/` tem seu próprio `.git`. Commits separados.
**Deploy:** via `gcloud compute scp` + `sudo cp` + `docker compose up --build frontend`.

### D-09 — Agenda do barbeiro mobile-first
**Data:** 2026-06-21  
**Arquivo:** `barbearia-frontend/app/barbeiro/agenda/page.tsx` (commit `205e43f`).

### D-10 — Botão "Conectar Calendar" usa endpoint `/authorize-url` (não redirect direto)
**Data:** 2026-06-21  
**Motivo:** Axios/fetch seguem redirects automaticamente, mas Google bloqueia por CORS.
**Arquivo:** `app/api/integracoes.py:188-210` (`authorize_url_json`).

---

## Produto e priorização

### D-11 — Lembrete 24h é a próxima feature de maior ROI
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
**Como fazer:**
```bash
# Login (renovar cookie):
curl -s -c /tmp/n8n_cookies -X POST 'http://localhost:5678/rest/login' \
  -H 'Content-Type: application/json' \
  -d '{"emailOrLdapLoginId":"admin@barbearia.com","password":"Barbearia@2026!"}'

# Atualizar workflow:
curl -sb /tmp/n8n_cookies -X PATCH \
  'http://localhost:5678/rest/workflows/25QZQ664N6hrIg59' \
  -H 'Content-Type: application/json' -d @/tmp/wf_payload.json
```

### D-15 — Bot usa GPT-4o-mini + regra explícita de interpretação de slots
**Data:** 2026-06-23  
**Decisão:** Seção "INTERPRETAÇÃO DE SLOTS" no system prompt do AI Agent.
**Alternativa se reincidir:** trocar node para `gpt-4o`.

### D-16 — `toolHttpRequest` do n8n não avalia `$env` em `fieldValue`
**Data:** 2026-06-23  
**Decisão:** Nos 8 nodes `toolHttpRequest`, o header `X-Bot-Token` recebe a
`BOT_API_KEY` **hardcoded** (não `={{ $env.BOT_API_KEY }}`).  
**Motivo:** Com `valueProvider: "fieldValue"`, n8n envia a string literal sem avaliar.

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
Não há erro visível — workflow termina como `success`.  
**Solução:**
```
ANTES (paralelo — não funciona):
  HTTP Flush Buffer → [Log Inbound, Code Horário]
  AI Agent → [Send Response, Log Outbound]

DEPOIS (série — funciona):
  HTTP Flush Buffer → Code Horário     (Log Inbound desabilitado — ver D-30)
  AI Agent → Send Response → Log Outbound
```

### D-19 — jsonBody de HTTP Request n8n: usar expressão de objeto, não JSON.stringify
**Data:** 2026-06-23 (parte 5)  
**Exemplo correto:**
```json
"jsonBody": "={{ {\"phone\": \"+\" + $('Set Phone').item.json.phone, \"direction\": \"inbound\", \"body\": $('HTTP Flush Buffer').item.json.message} }}"
```

### D-26 — Webhook direto Evolution→FastAPI para eliminar delay do n8n
**Data:** 2026-06-24 (2ª sessão)  
**Decisão:** Evolution aponta para `POST /bot/wa-webhook` (FastAPI) em vez de n8n.
O payload é registrado imediatamente e encaminhado ao n8n em background (retry 3×).  
**Motivo:** O n8n tem debounce de 5 s mínimo; mensagens do cliente chegavam com atraso
visível no Inbox. Com o webhook direto, o SSE dispara em < 100 ms.  
**Arquivo:** `app/api/wa_webhook.py` (novo); `app/core/config.py` (`n8n_webhook_url`, `wa_webhook_secret`).  
**Consequência:** n8n continua recebendo os payloads (para rodar o bot IA), mas não é mais
o responsável pelo registro no CRM.

### D-27 — Expressões n8n com `$` ficam corrompidas ao passar por SSH double-quote
**Data:** 2026-06-24 (2ª sessão)  
**Problema:** Ao enviar payload JSON para n8n via `curl ... -d '...'` dentro de
`gcloud compute ssh --command="..."`, expressões como `$json.field` ou `$('NodeName')`
têm o `$` expandido pela shell local (torna-se vazio ou executa subshell).  
**Solução:** Escrever o payload em arquivo Python no servidor remoto (`cat > /tmp/script.py << 'PYEOF'`
com `PYEOF` entre aspas simples evita expansão), executar Python, depois `curl -d @/tmp/arquivo.json`.  
**Consequência atual:** `Log Outbound Message` usa `$json["key"]["remoteJid"]` (colchetes,
sem ponto, mais seguro contra expansão futura) em vez da expressão original com `$('AI Agent')`.

### D-28 — Acidente n8n `user-management:reset` e recuperação
**Data:** 2026-06-24 (2ª sessão)  
**O que aconteceu:** Comando `docker exec -u node n8n n8n user-management:reset` foi
executado durante investigação. Apagou a conta owner do n8n.  
**Recuperação:**
```bash
curl -X POST http://localhost:5678/rest/owner/setup \
  -H 'Content-Type: application/json' \
  -d '{"firstName":"Admin","lastName":"Admin","email":"admin@barbearia.com","password":"Barbearia@2026!"}'
# Depois logar com POST /rest/login usando emailOrLdapLoginId
```
**Novas credenciais n8n:** `admin@barbearia.com` / `Barbearia@2026!`  
(Antigas eram `admin@barbeariapro.com` / `Barbearia2026` — não existem mais)  
**Lição:** Nunca rodar comandos de reset do n8n em produção. Sempre fazer login via API.

### D-29 — Não aplicar conversão 8→9 dígitos em `normalize_phone` sem migrar o DB
**Data:** 2026-06-24 (2ª sessão)  
**Contexto:** Celulares brasileiros têm 9 dígitos no formato moderno (ex: `+5563999368196`)
mas alguns números antigos têm 8 dígitos (ex: `+556399368196`). Evolution v2.3.7 envia
o mesmo número de WhatsApp em formato 8 dígitos para este cliente específico.  
**Decisão:** NÃO aplicar a conversão 8→9 em `normalize_phone` (revertido de versão local).  
**Motivo:** `conv_id=1` tem `phone_e164 = '+556399368196'` (8 dígitos). Se `normalize_phone`
convertesse para `+5563999368196`, `get_or_create_conversation` não encontraria a conversa
existente e criaria uma nova (duplicata). O n8n também usa o formato que Evolution retorna.  
**Se no futuro quiser normalizar:** migrar o DB primeiro (`UPDATE conversations SET phone_e164 = ...`
e `UPDATE clients SET phone_e164 = ...`), depois aplicar `normalize_phone`.

### D-30 — `Log Inbound Message` desabilitado no n8n (não deletado)
**Data:** 2026-06-24 (2ª sessão)  
**Decisão:** O nó `Log Inbound Message` foi desabilitado (não removido) no workflow n8n.
`HTTP Flush Buffer` agora conecta direto em `Code Horário Comercial`.  
**Motivo:** Com o webhook direto (`wa_webhook.py`), mensagens de cliente já são gravadas
em `messages` antes do n8n processar. Se `Log Inbound` também rodasse, cada mensagem
de cliente seria duplicada no DB (sem `wa_message_id` passado pelo n8n, o índice de
idempotência não protege).  
**Manter desabilitado:** a funcionalidade de gravação de inbound está no webhook direto.

---

## CRM Conversacional (sessão 2026-06-24, 1ª)

### D-20 — `POST /bot/messages` agora grava sem cliente (supersede versão anterior)
**Data original:** 2026-06-23 (parte 5).  
**Estado atual:** `log_message` chama `record_message(client_id=None)`. Conversa criada
sem `client_id`; backfill ocorre quando AI Agent cadastra o cliente.

### D-21 — SSE usa query param para autenticação
**Data:** 2026-06-24 (Fase 5)  
**Decisão:** `GET /crm/stream` aceita JWT como `?token=<jwt>`.  
**Motivo:** Browser `EventSource` não suporta headers customizados.  
**Arquivo:** `app/api/conversations.py:387` (`sse_stream`).

### D-22 — Idempotência de mensagem é namespaced por conversa (não global)
**Data:** 2026-06-24 (Fase 2)  
`UNIQUE(conversation_id, wa_message_id, sender_type) WHERE wa_message_id IS NOT NULL`

### D-23 — `_publish` chamado após `flush()`, antes do `commit()`
**Data:** 2026-06-24 (Fase 5)  
**Motivo:** `flush()` garante `msg.id`; payload completo no evento elimina GET de follow-up.  
**Arquivo:** `app/services/conversation.py:_publish`.

### D-24 — `message_log` é intocado pelo CRM Conversacional
**Data:** 2026-06-24 (Fase 2)  
**Invariante:** `message_log` é para reminders/reativação com template/retry.
`messages` é o store canônico de conversa. Nunca substituir um pelo outro.

### D-25 — `Dockerfile.migrate.dockerignore` para builds de migration
**Data:** 2026-06-24 (fix deploy)  
**Motivo:** `.dockerignore` principal exclui `alembic/`; builds de migration precisam dele.  
**Arquivo:** `Dockerfile.migrate.dockerignore` (criado na raiz do repo).

---

## Dívida técnica conhecida (não resolver sem discussão)

| Item | Arquivo | Severidade | Observação |
|---|---|---|---|
| Sem backup dos volumes Docker da VM | infra VM | ⚠️ Alto | VM já foi zerada uma vez; perdeu pareamento WhatsApp e dados. |
| Debug print temporário no webhook | `app/api/wa_webhook.py` | ⚠️ Médio | `print [WA_WEBHOOK]` nos logs — remover após confirmar evento send.message |
| Bot responses não confirmadas no CRM | fluxo n8n + Evolution | ⚠️ Alto | send.message pode não disparar; Log Outbound conectado mas não validado |
| Estado do bot em memória (debounce) | `app/api/bot.py:49-61` | Médio | Restart perde estado. Aguarda Redis. |
| Portas abertas ao mundo na VM | firewall GCP | Médio | 5678/8000/3000/8080 públicas; fechar após HTTPS. |
| `workflows.json` local diverge da VM | `workflows.json` | ⚠️ Alto | Exportar da VM antes de qualquer edição local. |
| SSE single-process: sse_broker em memória | `app/services/sse_broker.py` | Baixo | Não funciona com múltiplos workers. |
| Token JWT visível em query string do SSE | `GET /crm/stream?token=` | Baixo | Aceitável para MVP interno. Ver D-21. |
| 2 testes hardcoded na org 3 | `tests/` | Baixo | Fail ambiental; não são bugs (ver D-17). |
| Formato de telefone 8 vs 9 dígitos | DB + `normalize_phone` | Médio | conv_id=1 tem 8 dígitos; conv_id=10 tem 9 dígitos (mesmo número físico). Ver D-29. |
