# CRM via Chatwoot + WhatsApp Cloud API — Arquitetura e Roadmap

> Decisão de arquitetura para a camada de **comunicação/atendimento** do Taylor & Thedy:
> adotar **Chatwoot** (inbox omnichannel + atendimento humano multi-operador) sobre
> **WhatsApp Cloud API oficial (Meta)**, mantendo o **backend FastAPI/Postgres como
> sistema de registro** (funil, agenda, financeiro, clientes, assinaturas).
>
> Data: 2026-06-27 · Branch: `main` · Produção: `org_id = 1` · Status: **PLANO — nada implementado.**
>
> Origem das decisões: conversa de 2026-06-27 (esta sessão) + `DECISIONS.md` D-41 (migração
> Cloud API já decidida por causa de número restrito). Complementa/supera as **Fases 4/5/6**
> de `CRM_WHATSAPP_EVOLUCAO_ROADMAP.md` (Inbox/SSE/envio humano passam a ser entregues pelo Chatwoot).

---

## 1. Decisões tomadas (premissas deste plano)

| # | Decisão | Justificativa |
|---|---|---|
| 1 | **Chatwoot** assume Inbox conversacional + atendimento humano (multi-operador, atribuição, transferência) + omnichannel (WhatsApp, Instagram, e-mail, chat do site). | Pronto e maduro; evita construir as Fases 4/5/6 do roadmap do zero. |
| 2 | **Chatwoot self-hosted em VM nova** (Rails + Postgres + Redis + Sidekiq via Docker). | Não sobrecarrega a VM de produção; dados no nosso ambiente (LGPD). |
| 3 | **WhatsApp via Cloud API oficial (Meta) + número novo dedicado.** Abandona Evolution/Baileys no fluxo do bot. | **D-41**: número atual `5563920001734` está **restrito pelo WhatsApp** (recebe, descarta saída); conserto da Evolution **já esgotado** (testado até 2.4.0-rc2). Cloud API é nativo no Chatwoot. |
| 4 | **Backend FastAPI/Postgres permanece o sistema de registro.** Funil/Kanban, agenda, financeiro, clientes, assinaturas **não** migram para o Chatwoot. | É a propriedade intelectual do produto e está acoplada a tudo. "Evoluir, não reescrever." |
| 5 | **Raquel (IA) vira Agent Bot do Chatwoot.** n8n continua com o AI Agent, mas acionado por webhook do Chatwoot e respondendo pela API dele. | Reaproveita o investimento no n8n; usa o handoff bot↔humano nativo do Chatwoot. |
| 6 | **Supabase fora do escopo.** "Postgres gerenciado" é decisão de infra separada (avaliar depois: Supabase vs Cloud SQL vs Neon, com LGPD). | Não tem relação com a criação do CRM; não se "integra ao Chatwoot". |

---

## 2. Arquitetura-alvo

```
   Instagram / e-mail / chat do site ──┐
                                        │  (canais nativos do Chatwoot)
   WhatsApp Cloud API (Meta) ───────────┤        número novo dedicado
   (webhook + Graph API)                ▼
                                   ┌──────────────────────────────┐
   atendentes (Raquel humana, ───► │   CHATWOOT (VM nova)          │
   multi-operador, atribuição)     │   inbox omnichannel + agentes │
                                   └──────────────────────────────┘
                                        │  ▲
                          Agent Bot     │  │  resposta via API Chatwoot
                          (webhook)     ▼  │
                                   ┌──────────────┐   tools REST /bot/*
                                   │  n8n (Raquel) │ ─────────────────────┐
                                   │  AI Agent     │                      │
                                   └──────────────┘                      ▼
   webhook Chatwoot (conversa/msg)                          ┌───────────────────────────┐
   ──────────────────────────────────────────────────────► │  FastAPI + Postgres (RLS)  │
        upsert lead/cliente + avança funil                  │  funil • agenda • finance  │
                                                            │  clientes • assinaturas    │
                                                            └───────────────────────────┘
```

### Fluxos principais
- **Cliente → empresa:** WhatsApp Cloud API → Chatwoot (mensagem armazenada no inbox) →
  Agent Bot dispara webhook → n8n (Raquel) chama tools `/bot/*` e responde **pela API do
  Chatwoot** → Chatwoot envia pela Cloud API. O **"Assumir/Devolver ao bot"** passa a ser o
  handoff nativo do Chatwoot (status `open`/`pending` + atribuição a humano).
- **Funil:** webhook do Chatwoot (`conversation_created`, `message_created`) → endpoint novo no
  FastAPI → upsert de `lead`/`client` + avanço de estágio. Agendamento criado (`/bot/appointments`)
  continua avançando para `agendado` exatamente como hoje.
- **Mensagens proativas (>24h):** lembrete 24h e reativação exigem **templates aprovados pela
  Meta** (regra da Cloud API). Passam a ser enviados via Chatwoot API (ou Graph API direto) com
  o template correspondente.

---

## 3. O que muda, o que fica, o que se aposenta

### Permanece (não tocar)
- Backend de **funil/Kanban** (`app/api/crm.py`, `models/lead.py`), agenda, financeiro,
  clientes, assinaturas. RLS multi-tenant. RBAC.
- **Tools do bot** `/bot/*` (serviços, disponibilidade, criar/consultar/cancelar agendamento,
  perfil do cliente). A Raquel continua chamando-as.
- Os **3 pontos de avanço de estágio** do funil (inbound, upsert cliente, agendamento) — a
  Regra de Ouro do CRM segue valendo: a captura de mensagem não duplica transição.

### Muda
- **Saída de WhatsApp:** `app/services/whatsapp.py::send_text` (hoje POST à Evolution
  `/message/sendText`) → Graph API da Meta **ou** API do Chatwoot. Usado por
  `reminders.py`/`reactivation.py`.
- **Entrada de WhatsApp:** o parser Evolution-específico de `app/api/wa_webhook.py`
  (`data.key.remoteJid`, `data.message.conversation`...) deixa de ser a porta de entrada — o
  Chatwoot passa a receber via Cloud API. Surge um **webhook novo do Chatwoot → FastAPI**.
- **Raquel/n8n:** acionada por webhook do Chatwoot (não mais pela Evolution); responde pela
  API do Chatwoot. Nó "Send Response" (Evolution) é substituído.

### Aposenta (substituído pelo Chatwoot)
- A **Inbox custom** (UI `/admin/conversas`, SSE, `conversations.py`, `sse_broker.py`) e as
  Fases 4/5/6 do roadmap (Inbox 3 painéis, tempo real SSE, envio humano). O Chatwoot entrega
  tudo isso pronto + multi-operador + omnichannel.
- A **Evolution API** no fluxo do bot (containers `evolution_api`/`evolution_postgres`/
  `evolution_redis`). Manter desligada/arquivada após cutover.
- O mecanismo `clients.bot_paused` como controle de handoff (vira status do Chatwoot) — avaliar
  manter como espelho para compatibilidade durante a transição.

> **Tabelas `conversations`/`messages`/`attachments` + `record_message`:** decidir na Fase 4 se
> viram apenas espelho/integração (alimentadas pelo webhook do Chatwoot, p/ relatórios e funil)
> ou se são aposentadas. Não destruir antes do cutover validado.

---

## 4. Roadmap em fases (cada uma entregável e reversível)

### Fase 0 — Pré-requisitos Meta (Cloud API) · bloqueante, sem código
- Conta **Meta Business verificada**; **número novo dedicado** (não reusar o `5563...` restrito);
  WhatsApp Business API ativada (via Meta direto ou BSP — 360dialog/Gupshup/Twilio).
- Cadastrar **templates** para lembrete 24h e reativação (mensagens proativas >24h).
- **Aceite:** número aprovado, capaz de enviar/receber via Cloud API (teste fora do sistema).
- **Risco:** prazo de verificação Meta é externo (dias). **Começar por aqui.**

### Fase 1 — Provisionar VM nova + Chatwoot (HTTPS desde o início)
- VM nova (GCP), Docker, Chatwoot self-hosted (app + Postgres + Redis + Sidekiq). Domínio + TLS
  **desde o início** (aqui a Fase 1 de segurança do projeto vira pré-condição, não débito).
- **Aceite:** Chatwoot acessível por HTTPS, login de admin, 1 agente de teste.

### Fase 2 — Canal WhatsApp Cloud API no Chatwoot
- Configurar inbox WhatsApp (Cloud API) no Chatwoot com o número da Fase 0. Validar
  recebimento e envio de texto/mídia ponta a ponta (sem o bot ainda).
- **Aceite:** mensagem real entra e sai pelo inbox do Chatwoot.

### Fase 3 — Raquel como Agent Bot do Chatwoot
- Criar Agent Bot no Chatwoot → webhook → n8n. Adaptar o workflow: gatilho via Chatwoot,
  resposta via API do Chatwoot; preservar as tools `/bot/*` e o AI Agent. Handoff bot↔humano
  nativo (atribuir a humano = pausa o bot).
- **Aceite:** cliente conversa, Raquel responde, atendente assume e o bot silencia.

### Fase 4 — Glue Chatwoot ↔ backend (funil)
- Endpoint novo no FastAPI: webhook do Chatwoot (`conversation_created`/`message_created`) →
  upsert `lead`/`client` + avanço de funil; sincronizar contato Chatwoot ↔ `clients`.
- Repontar `send_text` (lembrete/reativação) para Cloud API/Chatwoot com templates.
- Decidir destino das tabelas de conversa (espelho vs aposentar).
- **Aceite:** conversa nova no Chatwoot cria/atualiza lead no Kanban; lembrete/reativação chegam
  via template; suíte `tests/` verde (regressão do funil).

### Fase 5 — Cutover + operação
- Treinar a recepção na inbox do Chatwoot; cutover do número; desligar Evolution; aposentar a
  Inbox custom; ajustar dashboards (métricas de atendimento agora no Chatwoot).
- **Aceite:** operação real rodando no Chatwoot; Evolution arquivada; rollback documentado.

---

## 5. Riscos e pontos de atenção
- **Janela de 24h da Cloud API:** fora dela só templates aprovados — impacta lembrete/reativação
  e qualquer disparo proativo. Mapear todos os envios proativos atuais para templates.
- **Custo por conversa** (Cloud API) + custo da VM nova (Chatwoot self-hosted).
- **LGPD:** dados de clientes reais no Chatwoot self-hosted — RLS não existe no Chatwoot; o
  isolamento multi-tenant continua sendo do **backend**. Chatwoot, por ora, é single-tenant (org 1).
- **Integração funil:** garantir que o avanço de estágio não duplique (Regra de Ouro do CRM).
- **Multi-tenant futuro:** Chatwoot tem o conceito de "Account"; mapear 1 org = 1 account quando
  o SaaS for multi-tenant de verdade (hoje produção é org 1). Não resolver agora.

---

## 6. Próximos passos
1. **Fase 0 já** — iniciar a verificação Meta Business + aquisição do número novo (é o gargalo
   de prazo e independe de tudo).
2. Em paralelo, **especificar a Fase 1** (provisionamento da VM + compose do Chatwoot) e a
   **Fase 4** (contrato do webhook Chatwoot→FastAPI e os campos do funil).
3. Registrar a decisão em `DECISIONS.md` (próximo: **D-49**) e referenciar este doc no `CLAUDE.md`.
```
