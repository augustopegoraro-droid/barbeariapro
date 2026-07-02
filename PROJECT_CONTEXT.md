# PROJECT_CONTEXT.md
> Fonte de verdade para novas sessões de desenvolvimento.
> Verificado contra o código E contra a VM de produção em **2026-06-26** (auditoria + segurança + incidente WhatsApp + **rearquitetura de frontend F1–F3**).
> **Leia também `CLAUDE.md`** (raiz) e **`barbearia-frontend/AGENTS.md`** (fonte de verdade do **frontend**: Design System, convenções, roadmap F1–F4).

---

## 0.00000 SESSÃO 2026-07-02 (2ª) — Deploy Kernel IA (D-57) + agente financeiro (D-58) em produção

> ✅ **DEPLOYADO em produção 2026-07-02** (containers `app-backend`/`app-frontend` healthy).
> ⚠️ **Bloqueado por chave OpenAI:** `OPENAI_API_KEY` da VM inválida/expirada (401) — Kernel IA
> degrada com graça, mas ninguém consegue usar o chat até rotacionar a chave.

- **Backend** `652fc2a` (merge do PR #15): `git pull origin main` na VM com **stash/pop do
  `docker-compose.yml`** (preserva o pin sha256 da Evolution, mesmo padrão de sempre); rebuild
  `docker compose -f docker-compose.app.yml up -d --build backend`. **Sem migration nova** — head
  já era `0025` (aplicada numa sessão anterior, só o código do D-58 estava faltando).
- **Frontend** `5f35099` (merge do PR #4 em `barbearia-frontend`): a VM já tinha a **deploy key SSH**
  configurada (D-54) — dessa vez bastou `git pull origin main` dentro do submódulo (sem precisar do
  fluxo antigo `git archive`+scp+tar) + rebuild `--build frontend`.
- **Descoberta na auditoria pré-deploy:** o backend já tinha `/kernel-ia/query` no ar (build de
  22:16 do mesmo dia, de uma sessão anterior), mas o **frontend nunca tinha sido deployado com o
  FAB do Kernel IA** (`kernel-ia-launcher.tsx` ausente do bundle `.next` antes deste deploy) — ou
  seja, esta sessão foi a **1ª exposição real do Kernel IA a usuários de produção**, não só um
  incremento do D-58. `CLAUDE.md`/`DECISIONS.md` tinham uma nota desatualizada dizendo D-57
  "prod pendente" quando na verdade só o front é que faltava — corrigido nesta sessão.
- **Verificado:** ambos containers `healthy`; `/kernel-ia/query` no `openapi.json`; bundle do
  frontend contém `kernel-ia-launcher` (`grep -rl "Kernel IA" .next` no container); `docker exec`
  chamando `kernel_ia.answer()` direto contra a org 1 real confirma o fail-closed gracioso
  (`action=config`) quando a chave OpenAI é inválida — **não** um 500.
- **Pendente:** rotacionar `OPENAI_API_KEY` em `/opt/barbeariapro/.env` (segredo — coordenar com o
  usuário, não é algo pra uma sessão automatizada decidir sozinha); depois disso, repetir a
  validação manual "LLM real" do D-58 (perguntas tipo *"a receita recorrente cobre a folha?"*)
  como smoke test final.

---

## 0.0000 SESSÃO 2026-06-30 — Deploy D-54 (multi-tenant) + D-55 (superadmin) em produção

> ✅ **DEPLOYADO e verificado em produção 2026-06-30.** Migration head agora **`0021`**. Backend, bot e painel da Raquel intactos.

**O que entrou (PRs #12/#13/#2 mergeados em `main`):**
- **Migrations `0020`+`0021`** aplicadas (head era `0019` → agora **`0021`**). `0020` = resolução de tenant (`organizations.subdomain` + `wa_instance_name` + funções `SECURITY DEFINER` `app_org_id_by_*`); `0021` = painel de plataforma (`platform_admins` + funções `app_platform_*`).
- **Backfill org 1:** `subdomain='taylor'`, `wa_instance_name='Barbearia'` (instância Evolution real). `app_org_id_by_subdomain('taylor')` e `app_org_id_by_wa_instance('Barbearia')` → `1`.
- **Superadmin criado:** `augustopegoraro.apl@gmail.com` (senha é **segredo**, não documentar). Login `POST /platform/auth/login` → token; `/platform/orgs` e `/platform/dashboard` OK; token de tenant em `/platform/*` → 401.
- **Submódulo frontend reparado** (estava sem `.git`) + **frontend rebuildado** com o fix `x-forwarded-host`.

**⚙️ COMO rodar migrations/scripts admin em prod (IMPORTANTE — difere do antigo `Dockerfile.migrate`):**
A imagem do backend **NÃO** copia `alembic/` nem `scripts/` (só `app/`+`models/`). Então monta-se o repo do host no container (que tem as libs), como root, com a `DATABASE_URL` do **superuser `postgres`** inline:
```bash
cd /opt/barbeariapro
PGPW=$(docker exec barbeariapro-postgres printenv POSTGRES_PASSWORD)
ENC=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=chr(0)))" "$PGPW")
URL="postgresql+psycopg://postgres:${ENC}@host.docker.internal:5432/barbeariapro"
sudo docker compose -f docker-compose.app.yml run --rm --user root -v /opt/barbeariapro:/repo:ro -w /repo \
  -e DATABASE_URL="$URL" backend python -m alembic upgrade head
# superadmin: idem, com -e ADMIN_DATABASE_URL="$URL" -e PLATFORM_ADMIN_EMAIL=.. -e PLATFORM_ADMIN_PASSWORD=.. ... python scripts/seed_platform_admin.py
```
`pg_dump` pré-deploy: `backups/predeploy_d54_d55_20260630_002430.sql`.

**🔑 Git/credenciais na VM (descoberto nesta sessão):**
- O repo **`barbeariapro` é PÚBLICO** (por isso `git pull` do super-projeto funciona sem credencial); **`barbearia-frontend` é PRIVADO**.
- A VM **não tinha** credencial GitHub → criada **deploy key SSH** read-only: `/root/.ssh/bfrontend_deploy` + alias em `/root/.ssh/config` (`Host github-bfrontend`); a URL do submódulo foi sobrescrita p/ SSH no `.git/config` (`git@github-bfrontend:augustopegoraro-droid/barbearia-frontend.git`). **`git submodule update` e deploys futuros do frontend funcionam.** (Pull do super-projeto: `git -c submodule.recurse=false merge --ff-only origin/main` evita travar no submódulo.)
- `.env` da VM (build-args do frontend): `NEXT_PUBLIC_ORG_ID=1`, `NEXT_PUBLIC_API_URL=http://34.95.199.134:8000`. `NEXT_PUBLIC_*` são **inlinadas no build** (runtime `printenv` vem vazio — normal).

**Verificado:** `/auth/tenant?subdomain=taylor` → org 1; `/bot/services`/`/bot/barbers` → 200 (bot usa fallback `settings.bot_organization_id=1`/`bot_unit_id=1`, **sem 503** apesar do novo fail-fast de unidade); frontend `/login` → 200 com `34.95.199.134:8000` inlinado (sem `localhost:8000`).

**Pendente (não bloqueia nada do que está no ar):**
- **DNS de subdomínios** — *no registrador* (domínio ainda não registrado; dívida conhecida). Sem isso o login segue por IP + `NEXT_PUBLIC_ORG_ID=1`.
- **n8n enviar header `X-Instance`** — só necessário quando entrar a **2ª barbearia** (hoje a instância `Barbearia` mapeia org 1 = idêntico ao fallback).
- **Frontend `/superadmin`** (app separado) — painel de plataforma é **API-only** por ora.
- Limpeza opcional na VM: `barbearia-frontend.bak.20260626-164038/`, `barbearia-frontend.predeploy-bak.*`, `barbearia-frontend.stale.*`.

---

## 0.000 SESSÃO 2026-06-29 — Deploy do Agente Gestor (D-52) em produção

> ✅ **DEPLOYADO em produção 2026-06-29** (containers `app-backend`/`app-frontend` healthy).

- **Backend** `fefd316`: `git pull origin main` na VM com **stash/pop do `docker-compose.yml`** (preserva o
  pin sha256 da Evolution); rebuild `docker compose -f docker-compose.app.yml up -d --build backend`.
- **Migration `0019`** aplicada: `docker build -f Dockerfile.migrate` + `docker run` com
  `DATABASE_URL` admin inline (`postgres@host.docker.internal:5432`, senha do container `barbeariapro-postgres`)
  — `.env` da VM **não** tem `ADMIN_DATABASE_URL`. `pg_dump` pré-deploy em `backups/predeploy_0019_20260629_154543.sql`.
- **Frontend**: `git archive HEAD` (do `main` do repo `augustopegoraro-droid/barbearia-frontend`) → scp → `tar -x`
  sobre `/opt/barbeariapro/barbearia-frontend` → rebuild `--build frontend`. `/admin/gestor` responde 307 (≠404).
- **Telefones** dos gestores gravados (org 1): Taylor `+5563984566177`, Thedy `+5563999663695`.
- **Pendente:** smoke visual logado (precisa do login do gestor); meta de faturamento; 2 crons n8n (`docs/GESTOR_CRON_N8N.md`).

---

## 0.00 SESSÃO 2026-06-27 (5ª) — Deploy `/admin/empresa` (D-45) + `/admin/assinaturas` em produção

> ✅ **DEPLOYADO em produção 2026-06-27 ~01:40** (containers `app-backend`/`app-frontend` healthy).

**Auditoria revelou divergências dos docs (corrigidas abaixo):**
- Produção já estava em **migration `0013`** (não `0011`): `0012`/`0013` (memberships) **já tinham sido
  aplicadas**. Backend mensalidade (D-44) **já estava live** (`/memberships` no openapi). Só faltava o
  **frontend `/admin/assinaturas`** (a VM rodava só F1–F3, sem a tela).
- VM backend estava em **`4b87e2f`** (merge mensalidade PR #3), não `469f784`.

**O que foi feito nesta sessão:**
- **Commit + merge de D-45** (empresa): backend PR #4 → **`9b945c7`** em `main`; frontend commit
  **`1e39857`** (branch `feat/mensalidade-cliente-final`). `next build` limpo (21 rotas), suíte
  **232 pass / 3 fail ambientais / 1 skip**.
- **Migration `0014_organization_profile`** aplicada em prod via imagem `Dockerfile.migrate` com
  `DATABASE_URL=postgres://postgres:***@host.docker.internal:5432/...` (admin; `barber_app` não tem DDL).
  **Head agora `0014`**; 7 colunas em `organizations`; GRANT SELECT/UPDATE ao `barber_app` OK.
- **Frontend** copiado via `git archive HEAD` → tar → scp → extração sobre `/opt/barbeariapro/barbearia-frontend`
  (backup em `backups/frontend_src_*.tgz`), depois `docker compose -f docker-compose.app.yml up -d --build`
  reconstruiu **backend (empresa) + frontend (assinaturas+empresa)**.
- **Verificado (API/infra):** `/empresa` (3 endpoints) e `/memberships` no openapi live; `/empresa` sem auth → 401
  (router são, sem 500); rotas `assinaturas`/`empresa` compiladas no container; backup pré-deploy do DB em
  `backups/barbeariapro_predeploy_0014_*.sql`.
- **✅ Smoke test no browser (prod, org 1):** `/admin/empresa` renderiza e carrega dados reais (org, unidade,
  horários Seg–Sáb, plano MVP + uso 5/20 profissionais); `/admin/assinaturas` renderiza (abas Planos|Assinaturas,
  empty state do backend). **Write round-trip validado**: PATCH em `legal_name` persistiu no DB e foi **revertido p/ NULL**.
- **Pendente:** higiene dos `.md` untracked na raiz (docs CRM superados).

---

## 0.0 SESSÃO 2026-06-26 (3ª) — Rearquitetura de Frontend (F1–F3) + backend reagendar

> ✅ **DEPLOYADO em produção em 2026-06-26 ~16:43** (containers `app-backend`/`app-frontend` rebuildados, healthy).
> - **Backend:** VM em `469f784` (reagendar + Fase 1.1 + CLAUDE.md). `AppointmentOut`/`AgendaReagendar` com
>   `barber_id` confirmados no schema **em execução**.
> - **Frontend:** F1–F3 **rodando** na VM (Inbox em `/admin/conversas`, Agenda do dia, etc.) — os arquivos foram
>   copiados para a VM e o container foi buildado a partir deles (backup do antigo: `barbearia-frontend.bak.20260626-164038`).
>
> ⚠️ **Pendência de higiene git (não de deploy):** o frontend F1–F3 está **só no branch local**
> `feat/design-system-react-query-f1-f3` (`3399587`) — **NÃO mergeado no `main` do repo frontend** (`main`=`f5397a8`,
> remote morto). Para continuar localmente: `cd barbearia-frontend && git checkout feat/design-system-react-query-f1-f3`.
> **Mergear esse branch no `main` do frontend** para o git refletir o que já está em produção.

**Frontend — rearquitetura completa (validada no browser contra o staging, org 1):**
- **F1 Fundação:** tokens (sombra/movimento/z-index) em `app/globals.css`; `components/patterns/`
  (Loading/Skeleton/EmptyState/ErrorState/**AsyncState**); **React Query** ligado (`components/providers.tsx`,
  `lib/queryClient.ts`, hook `hooks/use-authed-query.ts`).
- **F2 Data fetching:** 6 telas migradas de `useEffect+axios` para **React Query** + componentes de domínio +
  página enxuta: clientes, serviços, equipe, financeiro, dashboard, barbeiro/agenda. + polimento (KPIs com ícone, subtítulos).
- **F3 Monólitos quebrados:**
  - CRM (1389 ln) → **Inbox real em `/admin/conversas`** (SSE atualiza o cache do React Query) +
    `/admin/crm` vira **só o funil Kanban** (DnD optimistic). `app/admin/conversas/page.tsx` deixou de ser redirect.
  - Agenda admin (720 ln) → **grade do dia com 1 coluna por profissional** (eixo de horas, encaixe em 1 clique,
    ações no bloco, atalhos ←/→/T/N, filtro de profissionais, resumo do dia) + **drag-and-drop para reagendar,
    inclusive entre profissionais**.
- **Primitivos `ui/` novos** (reusados): `segmented-control.tsx`, `stat-card.tsx`, `section.tsx` (`Panel`+`SectionTitle`),
  `avatar.tsx` (`InitialAvatar`). Sidebar: badges falsos (Agenda:2, Conversas:5) **removidos**.
- **Hooks de dados:** `hooks/use-{clientes,servicos,equipe,financeiro,dashboard,agenda,agenda-barbeiro,conversas,crm}.ts`.
- `tsc`/`eslint`/`build` limpos (20 rotas) em cada etapa.

**Backend — reagendar pode trocar de profissional (D-43):**
- `PATCH /agenda/{id}/reagendar` aceita `barber_id` opcional → revalida vínculo serviço↔profissional + conflito
  no novo barbeiro + atualiza `AppointmentItem.barber_id`. `AppointmentOut` expõe `barber_id`. Sem migração de DB.
- **Mergeado em `main`** (PR #2 `469f784`); testes em `tests/test_e2e_flow.py`. **Falta deploy na VM.**

**Migrations staging:** subido de `0009` → **`0011`** (aplicadas `0010_conversations`+`0011_grant_crm_tables`
para validar o Inbox localmente). Produção já estava em `0011`.

**Como rodar a stack localmente (para validar o frontend):**
```bash
# backend (staging):  set -a; . ./.env.staging; set +a; export SEED_ORG_ID=1
#                     .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# frontend (staging): cd barbearia-frontend && NEXT_PUBLIC_ORG_ID=1 npm run dev -- --port 3000
# login: taylor@barbeariapro.com / senha123  (staging = org 1)
```
> O `.env.local` do frontend tem `NEXT_PUBLIC_ORG_ID=3` (não tocar); para o staging override-se p/ `1`.

---

## 0. LEIA PRIMEIRO — o que mudou em 2026-06-26

### 🔴 BLOQUEIO CRÍTICO ATIVO — Bot WhatsApp NÃO ENTREGA respostas
O bot **recebe** mensagens (CRM/Inbox OK) mas **não entrega** as respostas no WhatsApp.
Diagnóstico **exaustivo e conclusivo** (ver `DECISIONS.md` D-41): descartado TODO o software —
OpenAI, CRM, n8n, webhook, firewall, sessão Signal (instância recriada do zero) e **versão da Evolution**
(testado upgrade até `2.4.0-rc2` com suporte a LID + licença ativada → mesmo erro `Closing
session/pendingPreKey` → `status: ERROR`, **global** em 2 números distintos).
**Causa raiz: o número do bot `5563920001734` está RESTRITO pelo WhatsApp** (recebe, descarta a saída).
**Nenhuma mudança de código resolve.** Decisão: **migrar para a WhatsApp Cloud API oficial (Meta)** com
um **número DEDICADO novo**. Evolução = projeto à parte (pré-requisitos Meta + reescrever
`app/services/whatsapp.py` p/ Graph API + novo parser de webhook + templates). NÃO insistir em Evolution/Baileys.

**ATUALIZAÇÃO 2026-06-29 (refina o diagnóstico — D-53):** a restrição é mais específica: **envio bloqueado por
aparelho conectado (companion/linked device)**. O **app do WhatsApp no celular do número envia normal** (conta
NÃO banida), mas Evolution/WhatsApp-Web/**Baileys** (todos companion) não enviam. **Re-pareamento limpo testado
2026-06-29** (logout → QR novo → `state:open`): recebimento voltou, envio **continua** com
`pendingPreKey/status:ERROR` na sessão nova. Logo **Baileys também não resolve neste número**. **Decisão do gestor:**
usar `5563920001734` **só para receber** por ora (Evolution religada, Inbox/CRM recebendo); plano Baileys PAUSADO;
retomar **só com número novo** (Cloud API recomendado sobre Baileys). Gestor (D-52): dashboard web funciona; bot
WhatsApp + push só com número novo.

### 🟢 Segurança — Fase 1 (parcial)
1. **`CLAUDE.md` criado** (commit `15692b4`) = memória técnica viva.
2. **Fase 1.1 commitada** (`13822a1`): helper `secrets_match()` (`app/core/security.py`, comparação
   tempo-constante) usado em `app/deps.py` (X-Bot-Token) e `app/api/wa_webhook.py` (X-Webhook-Secret);
   `print` de debug do webhook → `_logger.debug`. **✅ DEPLOYADO** (VM em `469f784`, build 16:43 de 2026-06-26).
3. **Firewall GCP endurecido** (D-40): removidas `allow-n8n` (5678) e `allow-evolution` (8080); 5432 já
   estava fechada. **n8n e Evolution Manager agora só por SSH tunnel** (ver §12). Restam abertas 8000/3000.
4. **`SECRET_KEY` de produção verificado: FORTE** (256 bits) — NÃO rotacionar (placeholder estava só no `.env` local).
5. **Chave OpenAI rotacionada** — a antiga (vazada em `credentials.json` no histórico git) foi **revogada**;
   nova validada end-to-end. n8n usa OpenAI em 2 lugares (credencial `openAiApi` + `$env.OPENAI_API_KEY`).
6. **Pendente:** 1.3 limpar histórico git (`credentials.json` ainda no histórico, mas a chave que ele
   protegia já está revogada) · 1.4b HTTPS/domínio · deploy do 1.1 na VM.

### Evolution — estado após o incidente
- Rollback para **v2.3.7** concluído; instância `Barbearia` `open` (sobreviveu ao rollback).
- `docker-compose.yml` **da VM** agora fixa a imagem na **digest** `@sha256:966625532d90...` (NÃO `:latest`,
  para não puxar a 2.4 de novo). **Diverge do repo** (que ainda tem `:latest`).
- Backups do incidente em `/opt/barbeariapro/backups/` (`evolution_db_20260626_1221.sql` + `docker-compose.yml.bak-2.3.7`).

---

## 0.1 Sessão anterior — o que mudou em 2026-06-25 (2ª sessão)

1. **Bot corrigido** — system prompt do AI Agent atualizado: Marciana (id=3), Sandra (id=4) e Pablo (id=5)
   adicionados à seção `OS BARBEIROS`. O prompt anterior listava apenas Taylor e Thedy, causando o bot
   a negar que outros funcionários trabalhavam na barbearia. versionId n8n: `8ae50a30-49ac-4cd1-b290-e7e68bd89c25`.
2. **WhatsApp reconectado** — VM estava TERMINATED desde ~24/06. Religada. Instância Evolution deletada
   e recriada (nova sessão WA). QR escaneado. Estado: `open`.
3. **Webhook Evolution corrigido** — ao recriar instância, o webhook foi erroneamente apontado para o n8n.
   Corrigido de volta para `http://host.docker.internal:8000/bot/wa-webhook` (FastAPI). CRM inbox funcional.
4. **Página `/admin/integracoes` implementada** — substituiu placeholder "em desenvolvimento" por:
   - Card WhatsApp com status (verde/vermelho) + número conectado.
   - Botão "Conectar/Reconectar" que abre modal com QR code gerado pela Evolution API.
   - QR auto-atualiza a cada 30s; detecta conexão automaticamente e fecha o modal.
   - Backend: `GET /integracoes/whatsapp/status` + `GET /integracoes/whatsapp/qr`.
5. **Senha n8n resetada** — login estava falhando; senha redefinida para `Barbearia2026` (ver D-28 atualizado).
6. **Lembrete 24h** — confirmado saudável: 5 execuções bem-sucedidas em 2026-06-24. Parou porque VM
   estava desligada. Voltou a rodar automaticamente ao ligar a VM.

### O que mudou em 2026-06-25 (1ª sessão — frontend shell + nginx)

1. **Admin shell** — `AdminSidebar`, `AdminHeader`, `AdminShell` em `components/layout/`. Layout em `app/admin/layout.tsx`.
2. **shadcn/ui v4** com Tailwind v4.
3. **6 rotas admin novas**: `/admin/conversas` (redirect → `/admin/crm?view=inbox`), mais 5 placeholders.
4. **nginx** — proxy reverso porta 80 → `localhost:3000`. Config: `/etc/nginx/sites-available/barbeariapro`.

---

## 1. O que é o projeto

**BarbeariaPro** — plataforma SaaS de gestão para barbearias e salões.
Cliente âncora em produção: **Barbearia Taylor & Thedy** (Palmas/TO), clientes reais.
Objetivo comercial: vender para mais barbearias; concorre com Trinks.

---

## 2. Repositórios e estrutura de arquivos

| Repo / Diretório | Branch | Conteúdo |
|---|---|---|
| `/Users/apleandro/dev/barbeariapro` | `main` | Backend FastAPI + infra Docker + workflows n8n |
| `/Users/apleandro/dev/barbeariapro/barbearia-frontend` | `main` | Frontend Next.js (repo git **separado** dentro do diretório) |

> **Atenção:** `barbearia-frontend/` tem seu próprio `.git` com remote apontando para
> `https://github.com/DoctorDCombo/barbearia-frontend.git` — **este repo NÃO EXISTE mais**.
> Commits locais existem mas não têm push remoto funcional. Deploy é feito via scp+SSH+docker build na VM.

**Estado git (2026-06-26, 3ª sessão):**
- Backend repo (`main`): commit **`fa0857c`** (docs) ← `469f784` (PR #2 reagendar). `origin` vivo
  (`github.com/augustopegoraro-droid/barbeariapro`).
- Backend **na VM**: commit **`469f784`** — **deployado 16:43** (reagendar + Fase 1.1 + CLAUDE.md). Atrás do repo
  só pelo commit de **docs** `fa0857c` (sem código). `git pull` na VM é só doc-sync, sem rebuild.
- Frontend: branch **`feat/design-system-react-query-f1-f3`** (`3399587`) = **toda a F1–F3**, **já rodando na VM**
  (copiada + buildada 16:43). **NÃO mergeado no `main` do repo frontend** (`main`=`f5397a8`; remote `DoctorDCombo` morto)
  — pendência de higiene git. Continuar: `cd barbearia-frontend && git checkout feat/design-system-react-query-f1-f3`.

**Procedimento de deploy backend (sem mudança de dependências):**
```bash
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command=\
  "sudo git -C /opt/barbeariapro pull && \
   cd /opt/barbeariapro && sudo docker compose -f docker-compose.app.yml up -d --build backend"
```

**Procedimento de deploy frontend (scp + build):**
```bash
# 1. Copiar arquivo(s) modificado(s) para a VM:
gcloud compute scp /Users/apleandro/dev/barbeariapro/barbearia-frontend/app/admin/integracoes/page.tsx \
  barbeariapro:/tmp/page.tsx --project=barberiapro-app --zone=southamerica-east1-a
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command=\
  "sudo cp /tmp/page.tsx /opt/barbeariapro/barbearia-frontend/app/admin/integracoes/page.tsx"

# 2. Reconstruir e reiniciar container:
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command=\
  "cd /opt/barbeariapro && sudo docker compose -f docker-compose.app.yml up -d --build frontend"
```

---

## 3. Stack tecnológica

### Backend
- **Python 3.9**, FastAPI, SQLAlchemy async (psycopg3), Alembic
- **PostgreSQL 16** com Row Level Security (multi-tenant por `organization_id`)
- Auth: JWT Bearer (`app/core/security.py`) + header **`X-Bot-Token`** para o bot
  (`app/api/bot.py:109`, validado contra `settings.bot_api_key`)
- Criptografia de tokens OAuth: Fernet (`app/core/crypto.py`)

### Frontend
- **Next.js 16** App Router — leia `barbearia-frontend/AGENTS.md` antes de mexer
- **TypeScript** strict mode
- **Tailwind CSS v4** (`@import "tailwindcss"` — sem `tailwind.config.ts`)
- **shadcn/ui v4.11.0** com Tailwind v4 — usa `@base-ui/react` (não Radix UI)
- **next-auth v5** (beta) com `proxy.ts` (middleware de auth)
- **Inter font** via `next/font/google` (não Geist)
- `useSearchParams()` exige `<Suspense>` boundary — preferir `window.location.search` em client components
- Admin shell: `AdminSidebar` + `AdminHeader` em `components/layout/`; compostos por `AdminShell`
- **Padrão de chamada API:** `authedApi(token).get/post(...)` de `@/lib/api`

### Infraestrutura
- **Docker Compose** — dois arquivos:
  - `docker-compose.yml`: infra (Postgres prod `:5432`, n8n `:5678`, Evolution `:8080`,
    evolution-postgres, evolution-redis)
  - `docker-compose.app.yml`: app (backend `:8000`, frontend `:3000`)
- **nginx v1.22.1** instalado no host da VM — proxy reverso na porta 80 (ver §4)

---

## 4. PRODUÇÃO REAL — VM GCP (origem da verdade operacional)

| Item | Valor |
|---|---|
| Projeto GCP | `barberiapro-app` |
| VM | `barbeariapro` |
| Zona | `southamerica-east1-a` |
| IP externo | `34.95.199.134` |
| Acesso SSH | `gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a` |
| App na VM | `/opt/barbeariapro` |

> **Atenção:** A VM já foi desligada involuntariamente em 2026-06-25 (ficou TERMINATED).
> Verificar status antes de qualquer sessão: `gcloud compute instances describe barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --format="value(status)"`
> Para ligar: `gcloud compute instances start barbeariapro --project=barberiapro-app --zone=southamerica-east1-a`

### Containers em produção (verificado 2026-06-26, 3ª sessão)

```
barbeariapro-app-backend    :8000   healthy   FastAPI   — git 9b945c7 (build 2026-06-27 ~01:40, empresa D-45 + mensalidade D-44)
barbeariapro-app-frontend   :3000   healthy   Next.js   — F1–F3 + assinaturas + empresa (build 2026-06-27 ~01:40)
barbeariapro-postgres       :5432   healthy   Postgres  — migration HEAD: 0014_organization_profile
evolution_api               :8080   Up        Evolution API v2.3.7 — instância Barbearia (open)
evolution_postgres          (interno)
evolution_redis             (interno)
n8n                         :5678   Up        n8n v2.27.3
```

### nginx (host da VM, não container)
- Instalado em `/etc/nginx/` — `systemctl enable nginx` (inicia no boot)
- Config: `/etc/nginx/sites-available/barbeariapro` → link em `sites-enabled/`
- Porta 80: `default_server` → `localhost:3000` (frontend)
- Porta 80 + `Host: api.taylorethedy.com` → `localhost:8000` (backend)
- **SSL/HTTPS**: pendente — domínio `taylorethedy.app` não registrado

### Acessos
- **App frontend:** `http://34.95.199.134` (porta 80 via nginx) ou `:3000` direto
- **App backend:** `http://34.95.199.134:8000`
- **n8n editor:** **só via SSH tunnel** → `gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a -- -N -L 5678:localhost:5678` então `http://localhost:5678` — login: `admin@barbearia.com` / `Barbearia2026` (mantenha UM único túnel por porta)
- **Evolution manager:** **só via SSH tunnel** → `... -- -N -L 8080:localhost:8080` então `http://localhost:8080/manager`
- **Postgres (admin):** `docker exec barbeariapro-postgres psql -U postgres -d barbeariapro`
- **Página integrações (conectar WhatsApp):** `http://34.95.199.134:3000/admin/integracoes`

### Firewall (target-tag `http-server`) — endurecido em 2026-06-26 (D-40)
Abertas: `allow-backend` (8000), `allow-frontend` (3000), porta 80, 443, 22.
**FECHADAS:** `allow-n8n` (5678) e `allow-evolution` (8080) removidas; 5432 (Postgres) já estava fechada.
> ⚠️ n8n editor e Evolution Manager **NÃO são mais acessíveis pela internet** — só por **SSH tunnel** (ver §12).
> HTTPS ainda NÃO configurado (domínio não registrado). 8000/3000 ainda abertas (browser chama direto).

---

## 5. Ambientes

| Ambiente | Onde | Banco | Evolution/Bot |
|---|---|---|---|
| **Produção** | VM GCP `34.95.199.134` | `barbeariapro-postgres:5432` (org 1) | **ATIVO** — dispara WhatsApp real |
| **Staging** | local (Mac) | `barbeariapro-staging-postgres:5433` | **VAZIO** (dry-run) |

> D-01: `EVOLUTION_API_URL` e `EVOLUTION_INSTANCE_NAME` **VAZIOS** em staging.

---

## 6. Rotas da API (confirmadas no código)

| Prefixo | Arquivo | Auth |
|---|---|---|
| `/health` | `app/api/health.py` | público |
| `/auth` | `app/api/auth.py` | público (login) |
| `/bot` | `app/api/bot.py` | **`X-Bot-Token`** |
| `/bot/wa-webhook` | `app/api/wa_webhook.py` | `X-Webhook-Secret` (opcional) |
| `/crm` | `app/api/crm.py` | JWT |
| `/crm` (conversas) | `app/api/conversations.py` | JWT / token param (SSE) |
| `/integracoes` | `app/api/integracoes.py` | JWT + público (callback OAuth) |

### Endpoints `/integracoes/*` (completos)
```
GET  /integracoes/google/calendar/status          — Google Calendar conectado?
GET  /integracoes/google/calendar/authorize-url   — URL OAuth Google (JSON)
GET  /integracoes/google/calendar/callback        — público, callback OAuth Google
GET  /integracoes/whatsapp/status                 — { connected: bool, phone: str|null }
GET  /integracoes/whatsapp/qr                     — { qr: "data:image/png;base64,..." }
```

### Endpoint `/bot/wa-webhook` — webhook proxy Evolution→FastAPI
`POST /bot/wa-webhook` — recebe eventos Evolution API:
- **`messages.upsert`** (fromMe=false): grava mensagem do cliente (`sender_type=client`) → SSE imediato
- **`send.message`**: evento para msgs enviadas pelo bot; grava como `sender_type=bot`; NÃO encaminha ao n8n
- Outros eventos: encaminhados ao n8n em background (retry 3× com backoff)
- ~~Debug `print(f"[WA_WEBHOOK]...")`~~ → trocado por `_logger.debug` no repo (commit `13822a1`).
  ✅ Deployado (VM em `469f784`, build 16:43 de 2026-06-26) — o `print` não está mais em produção.

### Endpoints `/crm/*` (JWT, conversations.py) — Inbox em tempo real
`GET /crm/conversations`, `GET /crm/conversations/search?q=`,
`GET /crm/conversations/{id}`, `GET /crm/conversations/{id}/messages`,
`PATCH /crm/conversations/{id}/read`,
`POST /crm/conversations/{id}/send` — envia mensagem pelo Inbox (via Evolution),
`GET /crm/stream?token=<jwt>` — **SSE em tempo real**.

---

## 7. Páginas do frontend (16 rotas)

> ⚠️ **Duas realidades:** a tabela abaixo descreve o **branch `feat/design-system-react-query-f1-f3`**
> (estado atual do trabalho). O **`main`/produção (`f5397a8`)** ainda tem a versão antiga (CRM com toggle
> Kanban⇄Inbox, `/admin/conversas` = redirect, Agenda = lista linear). Convenções/arquitetura do frontend:
> **`barbearia-frontend/AGENTS.md`** (Design System, padrão página-enxuta + `components/<domínio>` + `hooks/use-<domínio>` + `AsyncState`).

| Rota | Arquivo | Observação |
|---|---|---|
| `/login` | `app/login/page.tsx` | público |
| `/admin/dashboard` | `app/admin/dashboard/page.tsx` | |
| `/admin/agenda` | `app/admin/agenda/page.tsx` | **grade do dia, 1 coluna/profissional** + DnD reagendar (branch). `components/agenda/*`, `hooks/use-agenda.ts` |
| `/admin/clientes` | `app/admin/clientes/page.tsx` | React Query (`components/clientes/*`, `hooks/use-clientes.ts`) |
| `/admin/crm` | `app/admin/crm/page.tsx` | **só funil Kanban** (DnD) — Inbox saiu p/ Conversas. `components/crm/*`, `hooks/use-crm.ts` |
| `/admin/conversas` | `app/admin/conversas/page.tsx` | **Inbox real** (SSE no cache RQ) — não é mais redirect. `components/conversas/*`, `hooks/use-conversas.ts` |
| `/admin/financeiro` | `app/admin/financeiro/page.tsx` | |
| `/admin/servicos` | `app/admin/servicos/page.tsx` | |
| `/admin/equipe` | `app/admin/equipe/page.tsx` | |
| `/admin/fidelidade` | `app/admin/fidelidade/page.tsx` | placeholder "Em breve" |
| `/admin/campanhas` | `app/admin/campanhas/page.tsx` | placeholder "Em breve" |
| `/admin/empresa` | `app/admin/empresa/page.tsx` | placeholder "Em breve" |
| `/admin/usuarios` | `app/admin/usuarios/page.tsx` | placeholder "Em breve" |
| `/admin/integracoes` | `app/admin/integracoes/page.tsx` | **FUNCIONAL** — WhatsApp status + QR modal |
| `/admin/configuracoes` | `app/admin/configuracoes/page.tsx` | Google Calendar OAuth |
| `/barbeiro/agenda` | `app/barbeiro/agenda/page.tsx` | |

### Layout do admin (`app/admin/layout.tsx`)
Todas as rotas `/admin/*` usam `AdminShell` (sidebar + header).
- `components/layout/AdminSidebar.tsx` — colapsável (240px↔64px), localStorage `sb_nav_v1_collapsed`, mobile overlay, badges estáticos (Agenda:2, Conversas:5)
- `components/layout/AdminHeader.tsx` — breadcrumb dinâmico via `ROUTE_META`, notificação bell amber
- `components/layout/AdminShell.tsx` — compõe os dois, controla estado `mobileOpen`

### Design tokens (dark theme fixo — classe `dark` no `<html>`)
```
body: #0a0a0a | sidebar: #111111 | header: #0d0d0d
brand amber: #f59e0b | borders: #1a1a1a
active nav: rgba(245,158,11,0.11) + border-l-2 border-amber-500
```

---

## 8. Migrations Alembic

Head atual: **`0014_organization_profile`** (prod **e** staging, verificado 2026-06-27).
> Prod: `0012`/`0013` (memberships) foram aplicadas antes da sessão 5ª; `0014` (empresa) aplicada em 2026-06-27.
> Migrations de DDL rodam como **admin** (`postgres`/`ADMIN_DATABASE_URL`) — `barber_app` não tem privilégio.

```
0001_initial → 0002_loyalty → 0002_client_last_photo → 0003_client_photo_description
→ 0005_barber_services → 0006_client_blocked → 0007_crm_leads
→ 0008_client_bot_paused → 0009_conversation_log → 0010_conversations
→ 0011_grant_crm_tables → 0012_memberships → 0013_grant_membership_tables
→ 0014_organization_profile  ← HEAD
```

> ⚠️ Migrations precisam de superuser postgres — `barber_app` não tem privilégio CREATE TYPE/TABLE.

---

## 9. Dados e usuários em PRODUÇÃO (VM, org_id = 1)

**Única organização:** `id=1` — "Barbearia Taylor e Thedy".

**Barbeiros ativos** (tabela `barbers`, `deleted_at IS NULL` — sem coluna `is_active`):

| id | name | specialty |
|---|---|---|
| 1 | Taylor | Cabeleireira e Barbeira |
| 2 | Thedy | Cabeleireiro e Barbeiro |
| 3 | Marciana | Cabeleireira e Manicure |
| 4 | Sandra | Cabeleireira e Designer de Sobrancelhas |
| 5 | Pablo | Barbeiro |

**Clientes reais:**
- `id=1` Augusto Pegoraro — `+556399368196` (8 dígitos — formato Evolution)
- `id=5` Reinaldo Viterbo — `+5563999789977`

> ⚠️ **Formato de telefone:** Evolution envia 8 dígitos (`556399368196@s.whatsapp.net`).
> `conv_id=1` tem `phone_e164 = '+556399368196'`. NÃO aplicar conversão 8→9 sem migrar o DB. Ver D-29.

**Roles do Postgres:** `barber_app` (RLS, senha `senha123`). Admin via `postgres`.

---

## 10. Variáveis de ambiente

### Produção VM — `/opt/barbeariapro/.env`
```
BOT_ORGANIZATION_ID=1
BOT_UNIT_ID=1
NEXT_PUBLIC_ORG_ID=1
EVOLUTION_INSTANCE_NAME=Barbearia      # B MAIÚSCULO, case-sensitive
EVOLUTION_SERVER_URL=http://34.95.199.134:8080
CORS_ORIGINS=http://34.95.199.134:3000
NEXT_PUBLIC_API_URL=http://34.95.199.134:8000
TZ=America/Sao_Paulo
# + BOT_API_KEY, EVOLUTION_API_KEY, EVOLUTION_API_URL, OPENAI_API_KEY, POSTGRES_PASSWORD, SECRET_KEY
```

### Produção VM — `/opt/barbeariapro/.env.docker`
```
DATABASE_URL=postgresql+psycopg://barber_app:senha123@host.docker.internal:5432/barbeariapro
EVOLUTION_API_URL=http://host.docker.internal:8080
N8N_WEBHOOK_URL=http://host.docker.internal:5678
API_URL_INTERNAL=http://host.docker.internal:8000
AUTH_SECRET=<segredo>   AUTH_TRUST_HOST=true
```

---

## 11. Trava de disparo WhatsApp (crítica)

`app/services/whatsapp.py:15-21` — `send_text()` retorna `False` sem enviar nada
se `EVOLUTION_API_URL` **ou** `EVOLUTION_INSTANCE_NAME` estiverem vazios.

---

## 12. Bot WhatsApp / n8n (produção)

> 🔴 **ENVIO BLOQUEADO (2026-06-26):** o bot **recebe** mas **não entrega** respostas — número
> `5563920001734` restrito pelo WhatsApp (ver §0 e D-41). IA gera a resposta e grava no CRM, mas a
> Evolution emite `send.message` com `status: ERROR` (`Closing session/pendingPreKey`). Confirmado global
> (não é versão/LID/sessão). **Correção = migrar p/ WhatsApp Cloud API com número novo dedicado.**

- **Evolution:** **v2.3.7** fixada na **digest** `@sha256:966625532d90...` no `docker-compose.yml` da VM
  (após rollback do upgrade 2.4.0-rc2 que NÃO resolveu). Instância **`Barbearia`** (B maiúsculo), número `5563920001734`.
- **instanceId Evolution:** recriado em 2026-06-26 (a instância foi deletada e recriada do zero durante o
  diagnóstico; o id muda a cada recriação — consultar via `GET /instance/fetchInstances`).
- **Acesso à Evolution/n8n:** só por **SSH tunnel** (portas 8080/5678 fechadas no firewall — D-40/D-35).
- **Webhook Evolution:** `http://host.docker.internal:8000/bot/wa-webhook` ← FASTAPI, não n8n
- **Eventos webhook:** `MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `SEND_MESSAGE`, `CONNECTION_UPDATE`, `QRCODE_UPDATED`
- **n8n v2.27.3** — login: `admin@barbearia.com` / `Barbearia2026`
  - Campo de login: `emailOrLdapLoginId` (não `email`)
  - Atualizar workflow: `PATCH /rest/workflows/{id}` (não PUT — retorna 404)
- **Workflows ativos:** `BarbeariaPro Bot - WhatsApp Chatbot` (id `25QZQ664N6hrIg59`), `CronReminder24h01`, `CronReactivation1`
- **n8n workflow versionId:** `8ae50a30-49ac-4cd1-b290-e7e68bd89c25`
- **Persona:** "Raquel", GPT-4o-mini. Tools: `obter_perfil_cliente`, `cadastrar_cliente`, `listar_servicos`, `listar_barbeiros`, etc.
- **Barbeiros no system prompt:** Taylor(1), Thedy(2), Marciana(3), Sandra(4), Pablo(5)

### ⚠️ WhatsApp cai ao reiniciar a VM
A sessão WhatsApp se perde toda vez que a VM é reiniciada (ou fica TERMINATED).
Para reconectar: acessar `http://34.95.199.134:3000/admin/integracoes` e clicar em "Conectar WhatsApp".
Alternativa: `http://34.95.199.134:8080/manager` (Evolution Manager, QR auto-refresh).

### Reconectar via API (se a página não estiver acessível):
```bash
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command="
curl -s -X GET 'http://localhost:8080/instance/connect/Barbearia' \
  -H 'apikey: 6BCBCA57CE49-4E10-9C21-5B9FECAE40B2' | python3 -c '
import sys,json,base64; d=json.load(sys.stdin)
b64=d.get(\"base64\",\"\")
if b64:
    data=b64.replace(\"data:image/png;base64,\",\"\")
    open(\"/tmp/qr.png\",\"wb\").write(base64.b64decode(data))
    print(\"QR salvo em /tmp/qr.png\")
'"
# Copiar para local:
gcloud compute scp barbeariapro:/tmp/qr.png /tmp/qr_wa.png --project=barberiapro-app --zone=southamerica-east1-a
open /tmp/qr_wa.png
```

### Atualizar webhook Evolution após recriar instância:
```bash
curl -s -X POST http://localhost:8080/webhook/set/Barbearia \
  -H 'apikey: 6BCBCA57CE49-4E10-9C21-5B9FECAE40B2' \
  -H 'Content-Type: application/json' \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://host.docker.internal:8000/bot/wa-webhook",
      "byEvents": false, "base64": false,
      "events": ["MESSAGES_UPSERT","MESSAGES_UPDATE","SEND_MESSAGE","CONNECTION_UPDATE","QRCODE_UPDATED"]
    }
  }'
```

### Fluxo do bot (verificado na VM)
```
Webhook → Block List → Set Phone → IF Audio/Individual/Image
→ HTTP Debounce → IF Controller → Wait 5s → HTTP Flush Buffer
→ Code Horário Comercial  (Log Inbound DESABILITADO — ver D-30)
→ IF Horário Aberto → Send Composing → Wait → Composing Active
→ HTTP Check Bot Pause → IF Bot Paused
→ Memory → AI Agent → Send Response → Log Outbound Message
```

### Autenticação n8n (API REST)
```bash
curl -s -c /tmp/n8n_cookies -X POST 'http://localhost:5678/rest/login' \
  -H 'Content-Type: application/json' \
  -d '{"emailOrLdapLoginId":"admin@barbearia.com","password":"Barbearia2026"}'

# Atualizar workflow (PATCH, não PUT):
curl -sb /tmp/n8n_cookies -X PATCH \
  'http://localhost:5678/rest/workflows/25QZQ664N6hrIg59' \
  -H 'Content-Type: application/json' -d @/tmp/wf_payload.json
```

> ⚠️ D-14: NUNCA editar SQLite do n8n para workflows. SEMPRE via API REST.
> ⚠️ D-18: NUNCA conectar nós em paralelo. SEMPRE em série.
> ⚠️ D-35: Ao recriar instância Evolution, SEMPRE reconfigurar webhook para FastAPI (não n8n).

---

## 13. CRM Conversacional — arquitetura

### Fluxo completo de uma mensagem
```
WhatsApp → Evolution → POST /bot/wa-webhook → record_message(sender=client) → SSE → Inbox
                     ↓ (background, retry 3×)
                     n8n → debounce → AI Agent → Send Response (Evolution)
                                               → Log Outbound Message
                                                 → POST /bot/messages → record_message(sender=bot) → SSE → Inbox
```

> ⚠️ **Bot responses ainda não confirmadas no Inbox** (pendente desde 2026-06-24):
> debug `print [WA_WEBHOOK]` ativo nos logs do backend — remover após confirmar.

### Modelo de dados
- `conversations` — `UNIQUE(organization_id, phone_e164, channel)`
- `messages` — `sender_type`: `client|bot|human|system`; idempotência por `(conv_id, wa_message_id, sender_type)`
- `attachments` — FK `message_id` CASCADE

### Porta única de escrita: `app/services/conversation.py`
- `record_message` — idempotente; atualiza preview/unread; chama `_publish` após `flush()`
- SSE broker: `app/services/sse_broker.py` — single-process (asyncio)

---

## 14. Suíte de testes

```bash
docker start barbeariapro-staging-postgres
set -a; . ./.env.staging; set +a
export SEED_ORG_ID=1
.venv/bin/python -m pytest tests/ -q
```

**Baseline (verificado 2026-06-26, 3ª):** **211 pass / 3 fail ambientais / 1 skip**.
As 3 falhas são pré-existentes e **não são bugs**: `test_bypass_hours_is_false_in_workflow` (config n8n),
`test_me_isola_tenant_via_rls` (isolamento RLS), `test_login_cria_cliente_cria_agendamento` (par barbeiro/serviço
`1/6` hardcoded não vinculado na org 1). Os testes novos de `reagendar` (em `tests/test_e2e_flow.py`) **passam**.
