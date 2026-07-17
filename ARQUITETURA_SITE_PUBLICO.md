# Arquitetura — Site Público de Agendamento do Cliente Final (v1)

> Fase 1 do `promptsitepublico.md`. Baseada na auditoria aprovada (`AUDITORIA_SITE_PUBLICO.md`) e nas
> decisões do dono (2026-07-17): **lançar sem OTP** (WhatsApp restrito, D-41), **escopo v1 = agendamento
> completo**, **D-78 executado junto** (apex = site público; `taylor.` → `app.` com 301).
>
> Data: 2026-07-17.

## 1. Autenticação e sessão (v1 sem OTP + caminho de upgrade)

**v1:** o cliente informa **nome + telefone** no primeiro agendamento. O backend normaliza o telefone
(`normalize_phone`, +55), casa por `(organization_id, phone_e164)` com a base existente (~2.913 clientes da
Trinks — **merge, nunca duplica**) ou cria o `Client`. Emite uma sessão de longa duração: token opaco de 256
bits, **só o hash SHA-256 persiste** em `client_sessions`, entregue num cookie `tt_session` **HttpOnly +
Secure + SameSite=Lax + Domain=.taylorethedy.com + Max-Age=400 dias** (máximo aceito pelo Safari para cookie
de servidor — achado da Fase 0).

**Consequência de segurança central (decisão consciente):** sem verificação do telefone, a sessão
**enxerga apenas os agendamentos que ela mesma criou** (`appointments.created_by_client_session_id`) —
nunca o histórico completo do telefone. Isso impede que alguém digite o telefone de outra pessoa e veja os
agendamentos dela. Sem rotação de token nesta v1 (sem identidade verificada, rotação não agrega; o molde
D-68 de rotação + reuse-detection entra junto com o OTP).

**Upgrade path (quando a WhatsApp Cloud API estiver ativa):** `client_sessions.verified_at` já nasce na
tabela. O fluxo OTP (solicitar código → verificar) só preenche `verified_at`; sessões verificadas passam a
ver o histórico completo do cliente e ganham rotação de token. Nenhuma migração ou quebra de contrato.

**Persistência no aparelho (Fase 0):** cookie de servidor de 400 dias cobre Android e Safari em uso ativo;
a garantia forte no iOS é o **PWA instalado** — o site instrui ativamente "Adicionar à Tela de Início" após
o primeiro agendamento. Re-login (redigitar nome+telefone) é o fallback tolerado.

## 2. Modelo de dados (migration `0044_public_site`)

- **`client_sessions`** (RLS + FORCE, molde `0042`): `id`, `organization_id`, `client_id`, `token_hash`
  (unique), `device_label`, `user_agent`, `ip`, `created_at`, `last_seen_at`, `verified_at` (NULL até o
  OTP), `revoked_at`.
- **`appointments.created_by_client_session_id`** (nullable, FK SET NULL): delimita "meus agendamentos".
- **`contact_channel` += `'site'`**: agendamentos do site nascem com `booking_channel='site'` (rastreio de
  canal; o painel/relatórios distinguem site × recepção × bot).

## 3. Endpoints públicos (`app/api/public.py`, prefixo `/public/{subdomain}`)

Resolução de tenant pelo **subdomínio no path** via `org_id_by_subdomain` (SECURITY DEFINER, molde
`GET /auth/tenant`) → `set_current_org` → tudo sob RLS. Rate limit por rota (slowapi/Redis, molde D-68).

| Rota | Auth | Limite | Função |
|---|---|---|---|
| `GET /info` | — | 60/min | Vitrine: nome, banner/`public_info`, serviços+preços, profissionais, horários — **exatamente o que `client_visibility_settings` (D-73) permite**. Cache Redis 60 s. |
| `GET /slots` | — | 60/min | Horários livres por serviço×profissional×dia (serviço novo `app/services/availability.py`). |
| `POST /auth/session` | — | 5/min | Nome+telefone → merge/cria `Client` → cookie de sessão. |
| `POST /appointments` | cookie | 10/min | Cria agendamento (mesma cadeia de validação do painel + `barber_has_conflict` + advisory lock; preço sempre o do catálogo). Sync Google Calendar; lembrete 24h entra de graça. |
| `GET /me/appointments` | cookie | 60/min | Agendamentos **desta sessão**. |
| `POST /me/appointments/{public_id}/cancel` | cookie | 10/min | Cancela se `agendado` e faltam >2 h (fixo na v1). |
| `POST /auth/logout` | cookie | — | Revoga sessão + limpa cookie. |

Tudo auditado em `audit_logs` (D-70) com `actor_kind="client"`: `public.session_created`,
`public.appointment_created`, `public.appointment_canceled`.

## 4. Slots livres (`app/services/availability.py` — novo, reusável por painel/bot)

Grade = `business_hours` da unidade (fuso `unit.timezone`), passo 30 min; slot válido se
`[início, início+duração do serviço)` cabe na faixa, não colide com `Appointment` ativo nem `TimeOff` do
profissional (semântica idêntica a `barber_has_conflict`, computada em lote para o dia), e começa a pelo
menos 30 min de agora.

## 5. Frontend (`barbearia-public/`, Next.js 16, :3200)

- `/` — home SSR (SEO: JSON-LD `LocalBusiness`, Open Graph) consumindo `GET /info` server-side.
- `/agendar` — stepper mobile-first: serviço → profissional → dia/horário → identificação → confirmação.
- `/meus-agendamentos` — lista + cancelamento.
- **PWA**: manifest + service worker + incentivo ativo à instalação (mitigação ITP, Fase 0).
- Tenant fixo por env `NEXT_PUBLIC_TENANT_SLUG` (v1 = org 1; multi-tenant por host fica para v2).
- Sem next-auth; chamadas autenticadas com `credentials: 'include'` (cookie cross-subdomínio
  apex ↔ `api.` é same-site, CORS já coberto pelo `CORS_ORIGIN_REGEX`/D-66).

## 6. Domínios (execução do D-78)

`taylorethedy.com` (apex, block nginx exato) → :3200 (site público) · `app.taylorethedy.com` → :3000
(painel; `UPDATE organizations SET subdomain='app'`) · `taylor.taylorethedy.com` → 301 para `app.` ·
`api.`/`admin.` inalterados. Cert coringa (D-64) e CORS já cobrem tudo.

## 7. Fora do escopo da v1 (registrado)

OTP (bloqueado pela Cloud API), rotação de sessão, "meus dispositivos", fidelidade/assinatura no site,
regras configuráveis de cancelamento (fixo 2 h), multi-tenant por host no site, avaliações/promoções
(flags existem no D-73; render entra quando houver conteúdo), upload de logo (usa `public_info.logo_url`
se existir; senão logotipo textual).
