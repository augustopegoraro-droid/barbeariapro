# Chatwoot — Especificação Fase 1 (VM + deploy) e Fase 4 (glue com o backend)

> Detalhamento técnico das fases marcadas em `CHATWOOT_CLOUD_API_ARQUITETURA.md`.
> **Status: especificação para revisão — nada aplicado.** Os blocos de config/código são o alvo proposto.
>
> Pré-requisito de ambas: **Fase 0** concluída (Meta Business verificado + número novo + templates).
> Data: 2026-06-27 · Decisão: D-49.

---

## FASE 1 — Provisionar VM nova + Chatwoot self-hosted (com HTTPS desde o início)

### 1.1 VM (GCP, mesmo projeto/zona da atual)

Chatwoot (Rails + Sidekiq + Postgres + Redis) é mais pesado que a app atual. Dimensionamento inicial:

| Item | Recomendação inicial | Observação |
|---|---|---|
| Tipo | `e2-standard-2` (2 vCPU / 8 GB) | Sidekiq + Rails + Postgres + Redis num só host. Subir para `e2-standard-4` se a fila atrasar. |
| Disco | 30–50 GB SSD | Anexos de conversa crescem; avaliar bucket externo depois. |
| Projeto / zona | `barberiapro-app` / `southamerica-east1-a` | Mesma da VM atual (`PROJECT_CONTEXT §14`). |
| Nome sugerido | `chatwoot` | Distinto de `barbeariapro`. |
| Firewall | abrir **só 80/443** ao mundo; 22 restrito (IAP/SSH); nada de Postgres/Redis expostos | Não repetir o erro de portas abertas da VM atual. |

> **LGPD:** dados de clientes reais ficam no Chatwoot. Manter no nosso GCP (não Cloud), backup do volume
> Postgres do Chatwoot, e tratar como dado pessoal (retenção/consentimento já existem no backend).

### 1.2 Domínio + TLS (pré-condição, não débito)

- Subdomínio dedicado, ex.: `atendimento.taylorethedy.com.br` (ou similar) apontando para a VM nova.
- TLS via **nginx + Let's Encrypt** no host (mesmo padrão da VM atual, que usa nginx no host), **ou**
  `caddy` no compose (TLS automático). Chatwoot **exige HTTPS** para webhooks da Meta e cookies seguros.
- `FRONTEND_URL=https://atendimento.taylorethedy.com.br` no `.env` do Chatwoot (usado em links/webhooks).

### 1.3 docker-compose (base oficial do Chatwoot, enxuta)

> Partir do `docker-compose.production.yaml` oficial do Chatwoot e ajustar. Esqueleto-alvo:

```yaml
# chatwoot/docker-compose.yml  (VM nova)
x-base: &base
  image: chatwoot/chatwoot:latest          # PINAR numa tag/digest antes de produção
  env_file: .env
  restart: unless-stopped
  volumes:
    - chatwoot_storage:/app/storage

services:
  base_db_check: &dbcheck { }               # (placeholder; usar o do compose oficial)

  rails:
    <<: *base
    depends_on: [postgres, redis]
    ports:
      - "127.0.0.1:3000:3000"               # NÃO expor ao mundo; nginx/caddy faz o TLS na frente
    entrypoint: docker/entrypoints/rails.sh
    command: ["bundle","exec","rails","s","-p","3000","-b","0.0.0.0"]

  sidekiq:                                   # processador de filas (essencial)
    <<: *base
    depends_on: [postgres, redis]
    command: ["bundle","exec","sidekiq","-C","config/sidekiq.yml"]

  postgres:
    image: pgvector/pgvector:pg16            # Chatwoot usa pgvector p/ features de IA
    restart: unless-stopped
    environment:
      POSTGRES_DB: chatwoot_production
      POSTGRES_USER: chatwoot
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - chatwoot_pg:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server","--requirepass","${REDIS_PASSWORD}"]
    volumes:
      - chatwoot_redis:/data

volumes:
  chatwoot_pg:
  chatwoot_redis:
  chatwoot_storage:
```

`.env` mínimo (segredos via `.env`, **nunca** no compose):
```
SECRET_KEY_BASE=<openssl rand -hex 64>
FRONTEND_URL=https://atendimento.taylorethedy.com.br
RAILS_ENV=production
POSTGRES_HOST=postgres
POSTGRES_USERNAME=chatwoot
POSTGRES_PASSWORD=<forte>
REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379
REDIS_PASSWORD=<forte>
# SMTP p/ convites/notificações de agente:
SMTP_ADDRESS=... SMTP_PORT=587 SMTP_USERNAME=... SMTP_PASSWORD=...
```

### 1.4 Bootstrap

```bash
# preparar o banco (primeira vez)
docker compose run --rm rails bundle exec rails db:chatwoot_prepare
docker compose up -d
# criar a conta/admin pelo onboarding em https://<dominio> (ou rails console)
```

### 1.5 Aceite da Fase 1
- [ ] HTTPS válido no domínio; redirect 80→443.
- [ ] Login de admin; 1 conta ("Taylor & Thedy") + 1 agente de teste.
- [ ] Sidekiq processando (fila sem backlog); Postgres/Redis **não** acessíveis de fora.
- [ ] Backup do volume `chatwoot_pg` agendado.

---

## FASE 4 — Glue Chatwoot ↔ backend FastAPI (funil + contato + proativos)

Objetivo: o Chatwoot é a camada de conversa; o **backend continua dono do funil**. A integração é por
**webhook do Chatwoot → FastAPI** (entrada) e **API do Chatwoot ← backend/n8n** (quando precisar agir).

### 4.1 Webhook do Chatwoot → FastAPI (novo endpoint)

Chatwoot dispara webhooks de conta (Settings → Integrations → Webhooks) com eventos como
`conversation_created`, `conversation_status_changed`, `message_created`, `contact_created`.

Novo router `app/api/chatwoot.py`, prefixo `/chatwoot`:

```python
# app/api/chatwoot.py (novo)
# POST /chatwoot/webhook  — autenticado por X-Chatwoot-Token (secrets_match, igual ao padrão do bot)
#
# event = message_created (incoming):
#   → resolve/upsert Client por phone (E.164 do contato Chatwoot)
#   → garante Lead ativo (mesma regra do bot: novo_contato; recorrente sem lead<7d = novo lead)
#   → se Lead em novo_contato e mensagem é do cliente → avança para "conversando"
#   → (NÃO duplica: reusa o caminho de avanço de estágio já existente, não cria um 4º ponto)
#
# event = conversation_status_changed (status=open por humano / pending):
#   → opcional: refletir handoff (espelhar em clients.bot_paused durante a transição)
```

**Contrato (resumo do payload Chatwoot relevante):**
```
POST /chatwoot/webhook   (header X-Chatwoot-Token: <segredo compartilhado>)
{
  "event": "message_created",
  "message_type": "incoming" | "outgoing",
  "conversation": { "id": 123, "status": "open"|"pending", "meta": {...} },
  "sender":  { "phone_number": "+556399...", "name": "..." },   // contato
  "content": "texto da mensagem",
  "account": { "id": 1 }
}
```

**Regras (Regra de Ouro do CRM preservada):**
- O avanço de estágio **não ganha um novo ponto**: o endpoint chama o **mesmo** helper que o bot já usa
  (extrair de `app/api/bot.py` se necessário) — `novo_contato → conversando` no inbound; `→ agendado`
  continua via `/bot/appointments`.
- `incoming` (cliente) avança/atualiza `last_contact_at`; `outgoing` (bot/humano) **não** mexe no estágio.
- Idempotência: ignorar reentrega usando o id da mensagem do Chatwoot (campo único por mensagem).
- Tudo sob `set_current_org(bot_organization_id)` (org 1) — Chatwoot é single-tenant por ora.

### 4.2 Mapeamento de identidade (contato Chatwoot ↔ `clients`)

- **Chave:** `phone_e164` (já é único por org em `clients`). O contato do Chatwoot traz `phone_number`.
- Guardar o `chatwoot_contact_id`/`chatwoot_conversation_id` para chamadas reversas (responder, anexar
  nota). Opções: coluna nova **nullable** em `clients`/`leads` (aditivo, segue o padrão das migrations) —
  decidir na implementação se vale ou se basta resolver por telefone a cada evento.

### 4.3 Saída/proativos — `app/services/whatsapp.py`

Hoje `send_text` faz POST à Evolution. Passa a ter **duas opções** (decidir na implementação):
- **(a) Via Chatwoot API** — cria/relança mensagem na conversa do contato (mantém histórico unificado no
  Chatwoot). Bom para mensagens dentro da janela de 24h.
- **(b) Via Graph API direto (Meta)** — necessário para **templates** (lembrete 24h / reativação são
  proativos >24h e exigem template aprovado). 

Recomendação: lembrete/reativação usam **template via Graph API (ou via Chatwoot template message)**; o
helper `send_text` ganha um parâmetro de template + parâmetros. Manter a **trava de disparo** (não enviar
se credenciais vazias — protege staging).

### 4.4 Raquel (n8n) — Agent Bot (resumo; detalhe na Fase 3)
- Chatwoot Agent Bot → webhook → n8n; n8n responde via `POST /api/v1/accounts/{id}/conversations/{cid}/messages`.
- Handoff: atribuir a humano (ou status `open` por humano) silencia o bot — substitui `clients.bot_paused`.

### 4.5 Aceite da Fase 4
- [ ] Conversa nova no Chatwoot cria/atualiza Lead no Kanban (org 1), no estágio correto.
- [ ] Mensagem do cliente avança `novo_contato → conversando` **sem** duplicar transição (suíte de
      regressão do funil verde).
- [ ] Lembrete/reativação chegam via **template** aprovado (fora da janela de 24h).
- [ ] Webhook autenticado (`X-Chatwoot-Token`, comparação tempo-constante) + idempotente.
- [ ] Nenhum endpoint/regra de `leads`/`lead_events`/`clients` alterado de forma destrutiva.

---

## Ordem de execução sugerida
**F0 (Meta) em paralelo →** F1 (VM+Chatwoot) → F2 (canal WhatsApp) → F3 (Raquel Agent Bot) →
**F4 (este glue)** → F5 (cutover). F4 depende de F1–F3 prontos para testar ponta a ponta, mas o
**contrato do webhook (4.1) e o mapeamento (4.2)** podem ser especificados/implementados em paralelo.
