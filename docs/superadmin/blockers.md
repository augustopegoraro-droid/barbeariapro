# Bloqueios externos — SuperAdmin/Billing

> Só entram aqui dependências que exigem ação humana fora do código.
> Nada aqui interrompe o desenvolvimento: tudo tem contorno implementado.

## Ativos

### B-01 · Domínio `admin.taylorethedy.com` (pré-existente, D-56)
- **O que falta:** comprar/apontar DNS → `34.95.199.134`; ativar `docker compose --profile superadmin up` + certbot na VM.
- **Contorno:** deploy já preparado (`docker-compose.app.yml` profile `superadmin`, `deploy/nginx.conf`); painel roda 100% em localhost:3100 contra a API de prod.

### B-03 · Crons de billing no n8n (após deploy do backend)
- **O que falta (ação do Augusto, 5 min):** criar cron diário no n8n chamando
  `POST /internal/billing/run-lifecycle` com header `X-Bot-Token` (mesmo molde dos
  crons do gestor, `docs/GESTOR_CRON_N8N.md`). Sem ele, assinaturas `manual` não
  transicionam trial→past_due→canceled automaticamente.
- **Contorno:** endpoint pode ser chamado manualmente.

### B-02 · Chaves Stripe no ambiente (para operação real)
- **Status:** conta Stripe **"BarbeariaPro"** existe e está conectada ao MCP (`acct_1Tp6TeGuBoJkIyFc`).
- **O que falta (ação do Augusto):** criar **restricted key** (prefixo `rk_`, permissões mínimas: Customers, Checkout Sessions, Subscriptions, Invoices, Billing Portal, Webhook Endpoints — write) em https://dashboard.stripe.com/acct_1Tp6TeGuBoJkIyFc/apikeys e definir `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` no `.env` da VM (`/opt/barbeariapro/.env`). Nunca versionar.
- **Webhook em prod:** exige URL pública HTTPS (depende de B-01 ou do domínio da API). Em dev: `stripe listen --forward-to localhost:8000/billing/webhooks/stripe`.
- **Contorno:** `MockBillingProvider` cobre dev/testes; `BILLING_PROVIDER=mock` é o default sem chave (fail-safe).

## Resolvidos

_(nenhum ainda)_
