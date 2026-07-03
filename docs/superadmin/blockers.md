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
- **Status:** conta Stripe **"BarbeariaPro"** (`acct_1Tp6TeGuBoJkIyFc`); Stripe CLI 1.43.6 instalado e PAREADO com o sandbox (2026-07-03); **fase teste validada ponta a ponta** — falta só a fase produção (bloqueada pelo HTTPS/domínio, abaixo).
- **⚠️ Pré-requisito descoberto:** a Stripe SÓ registra webhooks em **HTTPS** — a ativação
  em PRODUÇÃO depende de domínio+TLS para a API (mesmo bloqueio do B-01, ex.:
  `api.taylorethedy.com` atrás do nginx com certbot).

**Fase TESTE — ✅ CONCLUÍDA 2026-07-03 (sandbox "Área restrita de BarbeariaPro"):**
checkout real pago (R$49,90, cartão 4242) → 5 webhooks processados → fatura paga +
assinatura active com id Stripe no banco → pause/resume/cancel/reactivate 200 com
auditoria → convergência pós-webhooks-atrasados OK. Dois fixes reais saíram daqui
(commit `b020c36`): compat SDK 15.x (`_to_dict`) e refresh anti-out-of-order.
CLI pareado expira em ~90 dias. Passos originais (para repetir quando quiser):
1. `stripe login` (pairing no browser, uma vez).
2. Backend local com staging: `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY` = chave de
   teste do CLI (`stripe config --list`), `STRIPE_WEBHOOK_SECRET` = `stripe listen --print-secret`.
3. `stripe listen --forward-to localhost:8000/billing/webhooks/stripe` rodando.
4. Sync do plano (`POST /platform/billing/plans/{id}/sync`) → checkout via
   `POST /billing/checkout` (token de owner) → pagar a URL com cartão teste
   `4242 4242 4242 4242` → webhooks chegam → assinatura `active` + fatura `paid` no banco.

**Fase PRODUÇÃO (quando a API tiver HTTPS):**
1. Dashboard → API keys: criar **restricted key LIVE** (`rk_live_`) com permissões
   mínimas de ESCRITA: Customers, Checkout Sessions, Subscriptions, Products, Prices,
   Billing Portal (Customer portal), Refunds; LEITURA: Invoices, Charges.
2. Dashboard → Webhooks: endpoint `https://<api>/billing/webhooks/stripe` com os eventos:
   `checkout.session.completed`, `customer.subscription.created|updated|deleted`,
   `invoice.paid`, `invoice.payment_failed`, `invoice.finalized`, `invoice.voided`,
   `invoice.marked_uncollectible`, `charge.refunded` → copiar o `whsec_`.
3. Na VM (sem ecoar segredos — digite os valores no prompt):
   `read -s SK && read -s WH && sudo tee -a /opt/barbeariapro/.env >/dev/null <<<"BILLING_PROVIDER=stripe
STRIPE_SECRET_KEY=$SK
STRIPE_WEBHOOK_SECRET=$WH" && unset SK WH`
4. `sudo docker compose -f docker-compose.app.yml up -d backend` (restart) →
   sync dos planos no painel (Configurações → Sync) → teste real.
- **Contorno até lá:** `BILLING_PROVIDER=mock` (default fail-safe) segue em prod.

## Resolvidos

_(nenhum ainda)_
