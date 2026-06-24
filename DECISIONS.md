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
`EVOLUTION_API_URL` vazio). Regra documentada em `MANUAL-OPERACIONAL.md` Seção 2.

### D-02 — State JWT no fluxo OAuth (sem sessão server-side)
**Data:** 2026-06-21  
**Decisão:** O parâmetro `state` do OAuth é um JWT assinado com `SECRET_KEY`, TTL
5 minutos, contendo `org_id`. Verificado no callback sem precisar de armazenamento
em Redis ou banco.  
**Motivo:** Evita dependência de armazenamento de sessão no servidor para um fluxo
que dura segundos. CSRF-safe porque o state é assinado.  
**Arquivo:** `app/api/integracoes.py:52-70` (`_build_state`, `_verify_state`).

### D-03 — Tokens OAuth cifrados em repouso (Fernet/AES-128)
**Data:** 2026-06-21  
**Decisão:** `access_token` e `refresh_token` do Google são cifrados com Fernet
antes de persistir em `integration_accounts.token_encrypted` (LargeBinary).  
**Motivo:** Tokens OAuth dão acesso à agenda Google do usuário — não podem ser
armazenados em plaintext mesmo num banco com RLS.  
**Implementação:** `app/core/crypto.py`. Chave via `TOKEN_ENCRYPTION_KEY` (env var,
nunca no código). Falha explícita se chave ausente.

---

## Arquitetura e escopo

### D-04 — Fase 2 sem contato com n8n/bot
**Data:** 2026-06-16  
**Decisão:** A integração Google Calendar não toca o workflow n8n, a Evolution API
nem o bot WhatsApp. O sync é direto: `appointments → Google Calendar` via
BackgroundTask FastAPI.  
**Motivo:** O bot em produção é o core do produto. Qualquer mudança no n8n/Evolution
requer chip de teste isolado + janela de manutenção.  
**Consequência:** Fase 3 (disponibilidade via Calendar, status CRM automático) fica
bloqueada até staging n8n/Evolution ser montado.

### D-05 — Sync Calendar como BackgroundTask (não fila/worker)
**Data:** 2026-06-21  
**Decisão:** `push_appointment()` é chamado como `fastapi.BackgroundTasks` nos
endpoints de criação, reagendamento, conclusão, cancelamento e faltou.  
**Motivo:** MVP com instância única — adicionar Redis/Celery seria
over-engineering. BackgroundTask não bloqueia o response do barbeiro.  
**Trade-off:** Se o processo do FastAPI reiniciar durante o background task, a
sincronização é perdida (sem retry automático). Aceitável no MVP; para HA futura,
migrar para fila.  
**Arquivo:** `app/services/calendar_sync.py`. Hooks em `app/api/agenda.py` e
`app/api/barbeiro.py`.

### D-06 — Sem migration nova para a Fase 2
**Data:** 2026-06-21  
**Decisão:** Tabelas `integration_accounts` e `calendar_sync` já existiam desde
`0001_initial`. A Fase 2 apenas as utiliza — sem ALTER TABLE, sem nova migration.  
**Motivo:** Reduz risco de deploy; a migration `0007_crm_leads` já está em
produção e é o head atual.

### D-07 — Callback OAuth redireciona para o frontend
**Data:** 2026-06-21  
**Decisão:** O callback `/integracoes/google/calendar/callback` redireciona para
`GOOGLE_FRONTEND_SUCCESS_URL?calendar=connected` quando essa variável estiver
configurada; caso contrário retorna JSON (útil para testes de API).  
**Motivo:** O usuário não deve ver um JSON cru após autorizar o Calendar; deve
voltar para o painel com feedback visual.  
**Implementação:** `config.py:53` (`google_frontend_success_url`). Frontend
exibe banner verde quando detecta `?calendar=connected` na URL.

---

## Frontend

### D-08 — Frontend é repositório git separado
**Data:** descoberto em 2026-06-21  
**Decisão:** `barbearia-frontend/` tem seu próprio `.git`. Commits de frontend
e backend são feitos em repos separados.  
**Consequência prática:** Sempre fazer `git -C barbearia-frontend/ add/commit`
para mudanças de frontend. O `.gitignore` do backend ignora o diretório inteiro.

### D-09 — Agenda do barbeiro mobile-first
**Data:** 2026-06-21  
**Decisão:** `/barbeiro/agenda` foi refatorada para uso primário em celular:
header sticky, modal de conclusão como bottom-sheet, ações com touch targets
≥44px, skeleton de loading, auto-reload via `visibilitychange`.  
**Motivo:** O barbeiro usa a página no próprio celular durante o dia de trabalho,
não num desktop.  
**Arquivo:** `barbearia-frontend/app/barbeiro/agenda/page.tsx` (commit `205e43f`).

### D-10 — Botão "Conectar Calendar" usa endpoint `/authorize-url` (não redirect direto)
**Data:** 2026-06-21  
**Decisão:** O frontend chama `GET /integracoes/google/calendar/authorize-url`
(que retorna `{"url": "..."}`) e depois faz `window.location.href = url`.
Não chama `/authorize` diretamente.  
**Motivo:** Axios/fetch seguem redirects automaticamente, mas o redirect vai para
`accounts.google.com` que bloqueia pela política CORS. A abordagem JSON resolve
isso: o frontend recebe a URL e o browser navega nativamente.  
**Arquivo:** `app/api/integracoes.py:188-210` (`authorize_url_json`).

---

## Produto e priorização

### D-11 — Lembrete 24h é a próxima feature de maior ROI
**Data:** 2026-06-21 (análise do ROADMAP_IMPLEMENTACAO.md)  
**Decisão:** Após o merge da Fase 2, a próxima feature prioritária é o lembrete
24h antes via WhatsApp.  
**Motivo:** A infraestrutura já está 100% pronta (`message_log`, Evolution API,
n8n, `app/api/reminders.py`, telefones E.164, consentimentos LGPD). É o argumento
de venda nº 1 (redução de no-show). Só precisa de 1 workflow cron no n8n.  
**Requisito prévio:** Fase 3 exige staging de n8n/Evolution com chip de teste.
O lembrete também toca o Evolution — portanto é Fase 3.

### D-12 — Google Calendar sync é ROI baixo (mas foi pedido)
**Data:** 2026-06-21  
**Decisão:** O sync Calendar foi implementado mesmo com ROI baixo no ranking do
ROADMAP (posição 28 de 30).  
**Motivo:** Pedido direto do usuário como feature da Fase 2. Não atrapalha o
roadmap comercial — foi feito de forma isolada sem tocar o bot.

---

## Infraestrutura e produção (sessão 2026-06-23)

### D-13 — Produção roda na VM via docker-compose, NÃO no Cloud Run
**Data:** 2026-06-23
**Decisão:** A produção real é a VM GCP `barbeariapro` (`34.95.199.134`, projeto
`barberiapro-app`), com toda a stack em containers via `docker-compose.yml` +
`docker-compose.app.yml`. O Cloud Run não é usado.
**Motivo:** A Run Admin API nem está habilitada no projeto; `deploy/gcp-cloud-run.sh`
nunca rodou com sucesso. O bot/Evolution precisa de estado persistente e webhooks
estáveis, o que o VM com volumes Docker já entrega.
**Consequência:** O acesso operacional é por SSH
(`gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a`).
O app vive em `/opt/barbeariapro` na VM. **Não há backup automatizado dos volumes** —
a VM já foi encontrada zerada uma vez (perdeu pareamento WhatsApp + dados).

### D-14 — n8n: SEMPRE via API REST, NUNCA editar o SQLite direto
**Data:** 2026-06-23
**Decisão:** Qualquer alteração de credencial ou workflow no n8n é feita pela API
REST (`/rest/login`, `/rest/credentials`, `PATCH /rest/workflows/:id`,
`POST /rest/workflows/:id/activate`), nunca por `UPDATE` no `database.sqlite`.
**Motivo (aprendido na marra):** Várias horas foram perdidas tentando injetar a
credencial OpenAI direto no SQLite. Problemas encontrados:
- A criptografia do n8n v2.x é **formato OpenSSL** (`U2FsdGVkX1...`), não o JSON
  `{iv, content}` que tentei gerar manualmente → erro "Credentials could not be decrypted".
- **Apagar os arquivos `-wal`/`-shm`** após copiar o `.sqlite` descarta mudanças
  não checkpointed → reverteu correções feitas via API.
- O n8n v2.27.3 separa **`versionId`** (rascunho) de **`activeVersionId`** (versão
  que os webhooks realmente executam, vinda de `workflow_history`). Editar só os
  `nodes` do `workflow_entity` não muda o que o webhook roda.
**Como fazer certo:**
- Criar/atualizar credencial: `POST`/`PATCH /rest/credentials/:id` com
  `{name, type, data:{apiKey:...}}` — o n8n cifra corretamente.
- Ativar workflow: `POST /rest/workflows/:id/activate` com body
  `{"versionId":"<uuid existente em workflow_history>"}` (o `versionId` é obrigatório).
- Login n8n: `admin@barbeariapro.com` / `Barbearia2026`. Chave de cripto em
  `/home/node/.n8n/config`. `N8N_SECURE_COOKIE=false` (acesso HTTP).

### D-15 — Bot usa GPT-4o-mini + regra explícita de interpretação de slots
**Data:** 2026-06-23
**Decisão:** O bot roda em `gpt-4o-mini`. Foi adicionada uma seção
"INTERPRETAÇÃO DE SLOTS" no system prompt do node `AI Agent` deixando explícito que
os horários retornados por `verificar_disponibilidade` ESTÃO disponíveis.
**Motivo:** O GPT-4o-mini alucinou dizendo que um horário livre (11h com o Thedy)
"já estava reservado", embora a API tivesse retornado o slot como disponível.
**Trade-off:** GPT-4o seria mais confiável em raciocínio com listas, mas ~10× mais
caro por token. Optou-se por reforçar o prompt mantendo o mini.
**Alternativa se reincidir:** trocar o node para `gpt-4o`.

### D-16 — `toolHttpRequest` do n8n não avalia `$env` em `fieldValue`
**Data:** 2026-06-23
**Decisão:** Nos 8 nodes `toolHttpRequest`, o header `X-Bot-Token` recebe a
`BOT_API_KEY` **hardcoded**, não `={{ $env.BOT_API_KEY }}`.
**Motivo:** Com `valueProvider: "fieldValue"`, o n8n envia a string literal
`={{ $env.BOT_API_KEY }}` em vez de avaliar a expressão → backend respondia 401.
**Arquivo:** `workflows.json` (e versão ativa na VM via n8n).

---

## Correções de premissas dos docs antigos (2026-06-23)

### D-17 — Produção é `organization_id = 1` (supersede a premissa de org 3)
**Data:** 2026-06-23
**Contexto:** Docs anteriores afirmavam "produção usa org_id=3".
**Realidade verificada:** A VM foi re-semeada do zero e a única organização é
`id=1` ("Barbearia Taylor e Thedy"). `BOT_ORGANIZATION_ID=1`, `BOT_UNIT_ID=1`,
`NEXT_PUBLIC_ORG_ID=1`. Barbeiros: Taylor(1), Thedy(2), Marciana(3), Sandra(4), Pablo(5).
**Consequência:** Os 2 testes hardcoded em `organization_id == 3` falham contra
produção também (não só staging) — continuam sendo fails ambientais, não bugs.
O item da dívida técnica sobre "`NEXT_PUBLIC_ORG_ID` mudou de 3 para 1" está
**RESOLVIDO**: 1 é o valor correto para esta produção.

---

### D-18 — n8n v2.27.3: fanout paralelo não executa os nós secundários
**Data:** 2026-06-23 (parte 5)
**Decisão:** Qualquer nó de log/efeito-colateral no workflow n8n DEVE ser conectado
em SÉRIE, nunca em paralelo (fanout `main[0]: [nodeA, nodeB]`).
**Motivo (verificado empiricamente em 9 execuções):** Quando um nó conecta à saída
de outro em paralelo com outros nós, apenas o primeiro nó da lista (`nodeA`) é
executado. O segundo (`nodeB`) nunca aparece no `runData` e nunca é chamado.
Não há erro visível — o workflow termina como `success` e silenciosamente ignora
o nó secundário. Suspeita: bug ou limitação do n8n v2.27.3 com fanout.
**Solução aplicada para os nós de log:**
```
ANTES (paralelo — não funciona):
  HTTP Flush Buffer → [Code Horário Comercial, Log Inbound Message]  ← Log nunca roda
  AI Agent → [Send Response, Log Outbound Message]                   ← Log nunca roda

DEPOIS (série — funciona):
  HTTP Flush Buffer → Log Inbound Message → Code Horário Comercial
  AI Agent → Send Response → Log Outbound Message
```
**Consequência para Code Horário Comercial:** como agora recebe a saída do Log Inbound
(não do Flush Buffer), foi atualizado para referenciar o Flush Buffer explicitamente:
`$('HTTP Flush Buffer').first().json.message` em vez de `$json.message`.
**Atenção:** ao adicionar novos nós ao workflow, NUNCA conectar em paralelo —
sempre encadear em série ou usar sub-workflows.

### D-19 — jsonBody de HTTP Request n8n: usar expressão de objeto, não JSON.stringify
**Data:** 2026-06-23 (parte 5)
**Decisão:** Com `specifyBody: "json"`, o campo `jsonBody` deve conter uma expressão
n8n que retorna um **objeto JavaScript**, no formato `={{ {chave: valor, ...} }}`.
Não usar `JSON.stringify({...})` — retorna string, não objeto, e pode causar
comportamento imprevisível dependendo da versão do nó.
**Exemplo correto:**
```json
"jsonBody": "={{ {\"phone\": \"+\" + $('Set Phone').item.json.phone, \"direction\": \"inbound\", \"body\": $('HTTP Flush Buffer').item.json.message} }}"
```
**Comparação:** o nó `HTTP Flush Buffer` (que funciona) usa formato diferente:
`={\n  \"phone\": \"+{{ ... }}\"\n}` — template literal com `{{ }}` dentro.
Ambos funcionam; o formato `={{ {} }}` é mais flexível para valores que contêm
caracteres especiais (não quebra o JSON ao interpolar strings com aspas).

### D-20 — `POST /bot/messages` não cria cliente: silencia se cliente não existe
**Data:** 2026-06-23 (parte 5)
**Decisão:** Se o cliente não existe no DB, `POST /bot/messages` retorna
`{"ok": false, "reason": "client_not_found"}` sem criar o cliente nem o lead.
**Motivo:** Separação de responsabilidades. Criação de cliente/lead é responsabilidade
do AI Agent via `cadastrar_cliente`. Log de mensagem é secundário.
**Consequência prática:** A primeira mensagem de um **novo** número não é gravada no
histórico de conversa — apenas a partir da segunda (após o AI Agent criar o cliente).
**Futura melhoria (não urgente):** `log_message` poderia criar o cliente automaticamente
se não existir, ou o `Log Inbound Message` poderia chamar `POST /bot/clients` primeiro.

---

## Dívida técnica conhecida (não resolver sem discussão)

| Item | Arquivo | Severidade | Observação |
|---|---|---|---|
| Sem backup dos volumes Docker da VM | infra VM | ⚠️ Alto | VM já foi zerada uma vez; perdeu pareamento WhatsApp e dados. |
| Estado do bot em memória (debounce, dedup, sessões) | `app/api/bot.py:49-61` | Médio | Restart perde estado; impossibilita 2ª instância. Aguarda Redis. |
| Portas abertas ao mundo na VM | firewall GCP | Médio | 5678/8000/3000/8080 públicas; fechar após HTTPS. |
| `workflows.json` local diverge da VM | `workflows.json` | ⚠️ Alto | VM tem série; local tem paralelo. Exportar da VM antes de qualquer edição. |
| VM 1 commit atrás do main local | git VM | Médio | VM em `a11e0be`; local em `4d4ed5e`. `git pull` agora funciona na VM. |
| Primeira mensagem de novo número não é logada | `app/api/bot.py:264` | Baixo | `client_not_found` silencia. Ver D-20. |
| N+1 nos crons de reativação e lembrete | `app/services/reactivation.py`, `reminders.py` | Baixo | 3-4 queries por alvo; aceitável no volume atual. |
| 2 testes hardcoded na org 3 | `tests/test_clientes_integration.py`, `test_e2e_flow.py` | Baixo | Fail ambiental; não são bugs (ver D-17). |
