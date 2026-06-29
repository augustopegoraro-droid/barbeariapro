# Crons do Agente Gestor (D-52, Fase C)

Dois workflows de cron no n8n disparam o **push proativo** do Gestor, no mesmo
molde do "BarbeariaPro Cron - Lembrete 24h". **Não** editar `workflows.json` local
(diverge da VM); criar os workflows direto no n8n da VM.

> Pré-requisitos: `users.phone_e164` populado para o(s) gestor(es) (senão não há
> destinatário e nada é enviado) e — para o alerta de meta — `organizations.monthly_revenue_goal`
> cadastrado (tela `/admin/empresa`). A trava de envio do WhatsApp protege staging:
> sem Evolution/Cloud API configurada, o endpoint roda mas não entrega.

## 1) Resumo diário

- **Schedule Trigger (cron):** `0 20 * * *` (todo dia ~20h, fim do expediente).
- **HTTP Request:**
  - Method: `POST`
  - URL: `http://host.docker.internal:8000/internal/gestor/resumo-diario`
  - Headers: `X-Bot-Token: {{ $env.BOT_API_KEY }}`, `Content-Type: application/json`
- Resposta: `{ recipients, sent, digest }`.

## 2) Alertas de meta / queda

- **Schedule Trigger (cron):** `0 9-19/2 * * *` (a cada 2h em horário comercial).
- **HTTP Request:**
  - Method: `POST`
  - URL: `http://host.docker.internal:8000/internal/gestor/alertas`
  - Headers: `X-Bot-Token: {{ $env.BOT_API_KEY }}`, `Content-Type: application/json`
- Resposta: `{ alerts, recipients, sent }`. Só envia se `alerts > 0`.

## Tools pull (AI Agent "Raquel")

Para o Gestor **perguntar** por linguagem natural, o AI Agent deve, ao receber uma
pergunta de gestão, primeiro chamar `GET /bot/gestor/whoami?phone={{remetente}}`
e só prosseguir se `is_manager=true`. Demais tools (todas exigem `requester_phone`
e `X-Bot-Token`): `/bot/gestor/financeiro`, `/ranking`, `/inativos`,
`/inativos/disparar`, `/buracos`, `/ia-faturamento`, `/mrr`.
