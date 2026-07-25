# Auditoria técnica do front-end — `barbearia-public/`

> **Fase 1 do redesign do site público** (equipe UX + UI + Front-end).
> Estado do código em 2026-07-22, pós D-80 (hero cinematográfico deployado).
> Nenhuma mudança visual foi feita nesta fase — só levantamento + limpeza de código morto.

## 1. Estado geral

- **Stack:** Next.js 16.2.9 (App Router, Turbopack) · React 19.2.4 · TypeScript strict · Tailwind v4
  (tokens via `@theme inline` em `app/globals.css`). Zero dependências de runtime além de next/react —
  bundle enxuto por construção.
- **Build:** `npm run build` ✅ passa limpo (0 erros, 0 avisos). `npx tsc --noEmit` ✅ limpo.
  Não há ESLint configurado (`next lint` existe no script, mas sem `.eslintrc`/flat config no app —
  o `eslint-disable` em `hero-cinematic.tsx:143` é decorativo hoje).
- **Rotas (todas estáticas/ISR):** `/` (ISR 5min) · `/agendar` (ISR 1min) · `/meus-agendamentos`
  (client-side puro) · `/_not-found`.
- **PWA:** `public/manifest.webmanifest` + `public/sw.js` (SW mínimo, network-only, sem cache) +
  `components/register-sw.tsx`.

## 2. Inventário de componentes

| Arquivo | Tipo | Responsabilidade |
|---|---|---|
| `app/layout.tsx` | server | Fontes (Tenor Sans/Quicksand via `next/font`), metadata/OG, viewport, `<RegisterSW/>`, listra `.stripe` de topo |
| `app/page.tsx` | server (ISR 300s) | Home: JSON-LD LocalBusiness, `<HeroCinematic/>`, seções Serviços/Quem atende/Horários/Contato (WhatsApp/Instagram/tel) — tudo de `fetchInfo()` |
| `app/agendar/page.tsx` | server (ISR 60s) | Casca fina: busca `info` e delega a `<BookingFlow/>`; estado de erro próprio |
| `app/meus-agendamentos/page.tsx` | client | Lista `api.myAppointments()`, cancelamento com estado `canceling`, estados 401 ("sem sessão") / vazio / erro |
| `components/booking-flow.tsx` (463 linhas) | client | **Monólito do fluxo em 4 passos**: stepper, escolha de serviço, profissional, dia+slots (agrupados Manhã/Tarde/Noite), identificação (nome+telefone → `createSession`), confirmação, tela de sucesso, tratamento de 401/409 |
| `components/hero-cinematic.tsx` | client | Hero D-80: vídeo drone com scroll-scrubbing (rAF + `currentTime`), overlay/parallax/cue via refs, CTA `.cta-agendar`, logo `<img>` (`logo_url` \|\| `/logo-lockup.webp`), respeita `prefers-reduced-motion` |
| `components/install-banner.tsx` | client | Incentivo a instalar PWA (iOS: instrução manual; Android: `beforeinstallprompt`), dismiss em localStorage — usado só na tela de sucesso do booking |
| `components/register-sw.tsx` | client | Registro do service worker |
| `lib/api.ts` | isomórfico | Cliente da API `/public/{tenant}/*`: tipos, `ApiError`, `request()` com `credentials:'include'`, `fetchInfo()` (SSR c/ cache Next), objeto `api` |
| `lib/format.ts` | puro | Formatação pt-BR/`America/Sao_Paulo`: `money`, `timeHM`, `dateLong`, `localDayISO`, `maskPhone`, `WEEKDAYS_PT` |

**Gestão de estado:** 100% `useState`/`useEffect` locais — sem React Query/Context/store. Sessão =
cookie HttpOnly (invisível ao JS); o front guarda só o nome em `localStorage` (`tt_client_name`)
como memória de UX. Aceitável no tamanho atual; ver §6 para o redesign.

## 3. Mapa rota × endpoint (contrato consumido)

Backend: `app/api/public.py` (router `/public/{subdomain}`, sem auth de staff, RLS por org via
`org_id_by_subdomain` + `set_current_org`). O front usa `NEXT_PUBLIC_TENANT_SLUG` (prod: `app`).

| Endpoint | Método | Rate limit | Usado por | Resposta |
|---|---|---|---|---|
| `/info` | GET | 60/min (+cache Redis 60s) | `/` e `/agendar` (SSR, `fetchInfo`) | `{name, services[{id,name,category,duration_min,price,barber_ids}], professionals[{id,name,specialty}], hours[{weekday,open_time,close_time}], banner{}, public_info{}}` |
| `/slots?service_id&barber_id&day` | GET | 60/min | `booking-flow.tsx` passo 3 | `{slots: string[]}` (ISO UTC; grade 30min, respeita horário/antecedência/conflitos) |
| `/auth/session` | POST | 5/min | `booking-flow.tsx` passo 4 | `201 {client_name, is_new_client}` + cookie `tt_session` (400 dias). 403 genérico p/ cliente bloqueado; 422 telefone inválido |
| `/appointments` | POST | 10/min | `booking-flow.tsx` confirmar | `201 PublicAppointmentOut {public_id, service_name, barber_name, start_at, end_at, status, total_amount, cancelable}`. 401 sem sessão · 409 slot ocupado (front trata os dois) · 422 sem tz |
| `/me/appointments` | GET | 60/min | `/meus-agendamentos` | `PublicAppointmentOut[]` (≤50, só da própria sessão) |
| `/me/appointments/{public_id}/cancel` | POST | 10/min | `/meus-agendamentos` | `PublicAppointmentOut`; 422 se <2h (`public_cancel_min_hours`) ou status ≠ agendado |
| `/auth/logout` | POST | — | **ninguém** (existe em `lib/api.ts:127`, nunca chamado — não há UI de logout) | 204 + limpa cookie |

**Existe no contrato mas o front NÃO usa (ganchos para o redesign):**
- `info.banner` (JSONB livre configurado em `/admin/seguranca/visibilidade`, D-73) — hoje ignorado;
  candidato natural a faixa de aviso/promoção na home.
- `info.public_info.website` (tipado em `lib/api.ts:49`, nunca renderizado).
- `info.services[].category` (tipado em `lib/api.ts:20`, nunca usado — permitiria agrupar serviços).
- `public_info.logo_url` — já plugado no hero (fallback `/logo-lockup.webp`), mas nunca cadastrado no banco.
- **Backend-only, sem endpoint de leitura ainda:** `client_visibility_settings.show_reviews` e
  `show_promotions` (`models/client_visibility.py:30-31`) existem no banco/config do gestor, mas o
  `GET /info` **não devolve** avaliações nem promoções (as features não existem no produto). Se o
  redesign quiser seções de avaliações/promoções, exigirá trabalho de backend primeiro.
- `SessionOut.is_new_client` — recebido e descartado (`booking-flow.tsx:158`); daria boas-vindas
  diferenciada a cliente novo.

## 4. Débitos encontrados (arquivo:linha)

**Código morto (confirmado por grep — zero referências):**
- ✅ REMOVIDO nesta fase: `components/logo.tsx` (o `LogoLockup`/`LogoMark` SVG do D-79, órfão desde
  que o D-80 trocou o hero para `<img src="/logo-lockup.webp">` — confirmando a suspeita do CLAUDE.md)
  e `components/logo-paths.ts` (outlines vetoriais, só importado pelo logo.tsx).
- `public/logo-mark.svg` e `public/icon.svg` — sem referência em código nem no manifest
  (que usa `icon-192.png`/`icon-512.png`). Mantidos por serem assets públicos (URLs podem estar
  salvas externamente); decidir remoção junto com o redesign.
- `lib/api.ts:127` `api.logout` — sem chamador (não há UI de logout). Mantido: é contrato real do
  backend e o redesign provavelmente ganhará um "sair".

**Duplicações:**
- Cartão de resumo do agendamento (serviço + data + profissional + preço em `rounded-xl bg-aco p-5`)
  aparece 3×: `booking-flow.tsx:192-199` (sucesso), `booking-flow.tsx:363-370` (confirmar),
  `meus-agendamentos/page.tsx:91-124` (variação com status/cancelar).
- Linha/botão de serviço (nome + duração + preço) duplicada entre `app/page.tsx:77-84` (li estático)
  e `booking-flow.tsx:225-243` (button).
- Chip de profissional (avatar-inicial + nome + specialty) duplicado entre `app/page.tsx:96-113` e
  `booking-flow.tsx:253-276`.
- Botão CTA cheio (`rounded-xl bg-destaque px-6 py-3/4 font-semibold text-grafite`) repetido ≥5×
  (`booking-flow.tsx:204,414-420,438-444`; `meus-agendamentos/page.tsx:62-67,80-85`).
- Empty/error state centralizado (min-h-[80dvh] + título + texto) duplicado entre `app/page.tsx:44-51`
  e `app/agendar/page.tsx:19-29`.
- Fallback `"https://taylorethedy.com"` do `NEXT_PUBLIC_SITE_URL` duplicado em `app/layout.tsx:20` e
  `app/page.tsx:55`.

**Tipagem:**
- `lib/api.ts:43` `banner: Record<string, unknown>` e `public_info` sem tipo nomeado exportado —
  ok hoje, mas o redesign que consumir `banner` deve tipá-lo.
- `install-banner.tsx:10-12` `BeforeInstallPromptEvent` local minimalista (sem `userChoice`) — funcional.
- Sem problemas reais: `tsc --noEmit` limpo em strict.

**Acessibilidade:**
- `booking-flow.tsx:295-313` usa `role="tablist"`/`role="tab"` no seletor de dia **sem** `tabpanel`
  associado nem navegação por setas — semântica ARIA incorreta (melhor `radiogroup` ou botões simples
  com `aria-pressed`).
- `booking-flow.tsx:316-330` estados "Buscando horários…"/erro sem `aria-live` — leitor de tela não
  percebe a troca.
- Transições de passo não movem o foco (o usuário de teclado/leitor fica perdido ao trocar de step).
- `hero-cinematic.tsx:194` cue "Role para ver" ok (`aria-hidden`); contraste geral bom (prata sobre grafite).
- `app/page.tsx:187` emoji ✂️ como decoração com `aria-hidden` ✅.

**Performance:**
- `public/hero-drone.mp4` **2,5 MB** com `preload="auto"` (`hero-cinematic.tsx:115`) — baixa inteiro
  no first load de QUALQUER visita à home, mesmo em rede móvel. Mitigável com `preload="metadata"` +
  kick de load no primeiro scroll (mudança de comportamento → decidir com UX na Fase 2).
- `public/hero-poster.jpg` ~100 KB ok; `logo-lockup.webp` 70 KB ok (mas `<img>` cru sem `next/image`
  — deliberado, eslint-disable; dimensões declaradas evitam CLS ✅).
- 2 famílias Google via `next/font` (self-hosted, com `variable`) ✅.
- `booking-flow.tsx:94-101` `days` gerado com `new Date()` dentro de `useMemo([])` — congela os 14 dias
  no mount; num PWA que fica aberto dias, a lista envelhece (baixo risco, anotar).
- SW network-only (`public/sw.js`) — sem cache de estáticos; ok para dados vivos, mas o vídeo de 2,5 MB
  re-baixa a cada visita não-HTTP-cacheada.

**Higiene do repo:**
- `barbearia-public/VideoTa&TheDRONE.mp4` (1,1 GB) segue no working dir — coberto pelo `.gitignore` ✅,
  mas incha o context do Docker build (o `Dockerfile` faz `COPY . .` sem `.dockerignore` → **o build da
  VM copia 1,1 GB à toa se o arquivo existir lá**). Criar `.dockerignore` é refactor seguro recomendado.
- `tsconfig.tsbuildinfo` e `.DS_Store` no dir (ignorados pelo git ✅).

## 5. Oportunidades de refactor seguras (sem mudar pixel)

1. ✅ (feito) Remover `components/logo.tsx` + `components/logo-paths.ts`.
2. Extrair constante `SITE_URL` única (`lib/site.ts` ou reexport de `lib/api.ts`).
3. Adicionar `.dockerignore` (node_modules, .next, *.mp4 cru, .DS_Store) — corta o context de build.
4. Tipar `banner`/`public_info` como interfaces nomeadas exportadas em `lib/api.ts`.
5. Configurar ESLint (`eslint-config-next`) — o script `lint` hoje é inócuo.

## 6. Proposta de estrutura de componentes para o redesign (NÃO executada)

Objetivo: quebrar `booking-flow.tsx` (463 linhas) e desduplicar as UIs de cartão/CTA antes do novo
visual, para que UX/UI specs plugem em componentes pequenos.

```
components/
  ui/                        ← primitivos de apresentação (puros, sem fetch)
    cta-button.tsx           ← botão cheio destaque (variantes: solid | link) — 5 usos hoje
    card.tsx                 ← superfície `rounded-xl bg-aco p-5`
    appointment-summary.tsx  ← serviço + data/hora + profissional + preço (3 usos)
    service-row.tsx          ← nome + duração + preço (li estático e button)
    professional-chip.tsx    ← avatar-inicial + nome + specialty (2 usos)
    status-badge.tsx         ← pill de status (meus-agendamentos)
    empty-state.tsx          ← estado centralizado de erro/vazio (2 usos)
    stripe.tsx               ← a listra assinatura (hoje classe CSS; pode continuar CSS)
  booking/                   ← o fluxo, 1 arquivo por passo
    booking-flow.tsx         ← orquestrador: máquina de passos + estado (ou useReducer)
    use-booking.ts           ← hook com o estado/efeitos (slots, sessão, confirm) hoje inline
    step-header.tsx          ← stepper (já é função interna — só mover)
    step-service.tsx
    step-professional.tsx
    step-schedule.tsx        ← seletor de dia + grade de slots (day-picker.tsx + slot-grid.tsx se crescer)
    step-confirm.tsx         ← resumo + identify-form.tsx (nome/telefone)
    booking-success.tsx      ← tela "Horário marcado!" + InstallBanner
  hero-cinematic.tsx         ← mantém (isolado e recente); só extrair use-scroll-scrub.ts se o
                                redesign mexer no hero
```

Regras da migração (quando a Fase 2 começar): mover JSX 1:1 sem alterar classes; estado permanece no
orquestrador (props para baixo, callbacks para cima); `lib/api.ts` e `lib/format.ts` intocados;
cada extração validada com `npm run build` + diff visual.

## 7. Variáveis de ambiente

| Var | Onde | Uso |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | browser (inlinada) | base da API pública |
| `API_URL_INTERNAL` | SSR (compose) | `http://backend:8000` |
| `NEXT_PUBLIC_TENANT_SLUG` | browser | slug no path (`app` em prod; fallback `taylor` em `lib/api.ts:13` e no `Dockerfile` ARG — **divergem do `.env.example` (`app`)**, inofensivo mas vale alinhar) |
| `NEXT_PUBLIC_SITE_URL` | ambos | metadataBase/JSON-LD |
