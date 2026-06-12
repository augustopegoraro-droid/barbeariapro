# ROADMAP_IMPLEMENTACAO.md — Gap Analysis: BarbeariaPro × Trinks

**Data:** 11/06/2026
**Base de comparação:** `~/TRINKS ANALISE/FEATURES_MASTER.md` (auditoria funcional da Trinks)
**Escopo auditado:** backend FastAPI (`app/`, `models/`, `schema.sql`, `alembic/`), frontend Next.js (`barbearia-frontend/`), workflows n8n (`workflows.json` + backups), seed e testes.

**Legenda de status:**
- ✅ IMPLEMENTADA
- 🟡 PARCIALMENTE IMPLEMENTADA
- ❌ NÃO IMPLEMENTADA
- 🚨 IMPLEMENTADA MAS COM PROBLEMAS

---

## 1. Estado atual do BarbeariaPro (inventário verificado no código)

### Backend (FastAPI + PostgreSQL/RLS)
| Módulo | Endpoints | Arquivo |
|---|---|---|
| Auth JWT | `POST /auth/login`, `GET /auth/me` | `app/api/auth.py` |
| Bot WhatsApp | 12 endpoints `/bot/*` (debounce, services, barbers, clients, profile, photo, availability, appointments CRUD, cancel, complete) | `app/api/bot.py` |
| Agenda admin | `GET/POST /agenda`, `PATCH /agenda/{id}/reagendar`, `GET /agenda/barbers`, `GET /agenda/services` | `app/api/agenda.py` |
| Atendimento | `PATCH /barbeiro/atendimento/{id}/concluir\|faltou\|cancelar` | `app/api/barbeiro.py` |
| Financeiro | `GET /financeiro?date=` (dia: receita, por método, por barbeiro c/ comissão) | `app/api/financeiro.py` |
| Clientes | `GET/POST /clientes`, `PATCH /clientes/{id}`, `DELETE`, `PATCH /{id}/bloquear` | `app/api/clientes.py` |
| Equipe | `GET /equipe` (somente leitura) | `app/api/equipe.py` |
| Dashboard | `GET /dashboard?period=` (receita, ticket, série diária, rankings, fidelidade) | `app/api/dashboard.py` |
| Serviços | `GET/POST /servicos`, `PATCH /{id}`, `arquivar`, `reativar` | `app/api/servicos.py` |
| Fidelidade | `GET /loyalty/clients/{id}`, `POST /internal/loyalty/reactivation/run` | `app/api/loyalty.py` |

### Frontend (Next.js)
Páginas: `/login`, `/admin/agenda`, `/admin/clientes`, `/admin/dashboard`, `/admin/equipe`, `/admin/financeiro`, `/barbeiro/agenda`. **Não existe** página de serviços, configurações, relatórios ou cadastro de unidade.

### n8n (automação)
**1 único workflow ativo:** "BarbeariaPro Bot - WhatsApp Chatbot" (AI Agent GPT-4o com 9 tools, Whisper p/ áudio, Vision p/ foto de referência, FAQ, debounce server-side, detecção de sessão, horário comercial, blocklist). **Não existe** nenhum workflow de cron (lembretes, reativação, aniversário).

### Schema sem código por cima (capacidade latente)
`integration_accounts` + `calendar_sync` (Google Calendar), `message_log` (retry/idempotência prontos), `expenses` + `expense_categories` (sem endpoint), `plans` + `subscriptions` (billing SaaS), `appointments.rating` (nada escreve), estrutura `organizations → units` (multi-unidade).

---

## 2. Classificação funcionalidade a funcionalidade

### ✅ IMPLEMENTADAS

| Funcionalidade | Evidências | Arquivos | Complexidade p/ chegar aqui | Impacto comercial |
|---|---|---|---|---|
| **Chatbot WhatsApp de agendamento com IA** (agenda, cancela, consulta, perfil, áudio, foto, FAQ) | Workflow ativo c/ 37 nós + 12 endpoints `/bot/*` autenticados por `X-Bot-Token` via `get_bot_db` | `app/api/bot.py`, `workflows.json` | — | **Crítico — é o diferencial vs Trinks (item #2 do ranking, lá é add-on pago)** |
| **Agenda administrativa** (visão do dia, criar c/ preço variável, reagendar, concluir c/ pagamento, faltou, cancelar) | UI completa + validação de conflito, grade 30min, advisory lock | `app/api/agenda.py`, `app/admin/agenda/page.tsx` | — | Crítico (item #1 do ranking — núcleo) |
| **Disponibilidade real** (BusinessHours, TimeOff, conflitos, fuso da unidade) | `GET /bot/availability` com slots filtrados | `app/api/bot.py:575` | — | Crítico |
| **Gestão de clientes** (CRUD, bloqueio, soft-delete, consentimento LGPD, telefone E.164 único por org) | `app/api/clientes.py` + página com busca/kebab menu | `app/api/clientes.py`, `models/client.py` | — | Alto |
| **CRM/Segmentação de fidelidade** (nível novo/ativo/fiel/VIP + categoria bronze→diamante + status ativo/em risco/inativo, benefício, próximo marco) | Cálculo puro + snapshot persistido; exibido em `/clientes` e dashboard | `app/services/loyalty.py`, `models/loyalty.py` | — | Alto (item #5 do ranking) |
| **Dashboard de indicadores** (receita, ticket médio, série diária, ranking de barbeiros c/ comissão e taxa de conversão, top serviços, pizza de fidelidade, períodos hoje/7d/30d/mês) | `GET /dashboard` + página com gráficos | `app/api/dashboard.py`, `app/admin/dashboard/page.tsx` | — | Alto (na Trinks é 🟡 provável — aqui já supera) |
| **RBAC com enforcement** (owner/manager/reception/barber; recepção sem financeiro; barbeiro só age no próprio atendimento) | Guards usados em todos os endpoints autenticados + testes e2e de RBAC | `app/core/rbac.py`, `e2e/02-rbac.spec.ts` | — | Alto (na Trinks é ⚪ não confirmado) |
| **Multi-tenant com RLS no PostgreSQL** | `set_current_org` por request; role não-dona das tabelas | `app/db/session.py`, `app/deps.py` | — | Alto (fundação SaaS) |
| **Visão do profissional** (agenda própria no navegador, concluir/faltou/cancelar) | `/barbeiro/agenda` mobile-friendly | `app/barbeiro/agenda/page.tsx` | — | Médio (item #10 — PWA basta no MVP) |

### 🟡 PARCIALMENTE IMPLEMENTADAS

| Funcionalidade | O que existe | O que falta | Arquivos | Complexidade | Impacto |
|---|---|---|---|---|---|
| **Financeiro / fluxo de caixa** | Resumo do dia: receita, por método, por barbeiro, comissões | Despesas (modelo `Expense` existe, **zero endpoints/UI**), visão mensal/período, fluxo de caixa líquido, export | `app/api/financeiro.py`, `models/payment.py` | Baixa-Média | **Crítico** (item #3) |
| **Comissões** | `% único por barbeiro` calculado em dashboard/financeiro | Regras por serviço, relatório de fechamento/repasse por período, histórico | `models/barber.py` (`commission_pct`), `dashboard.py` | Média | Alto (item #4) |
| **Checkout/comanda** | Concluir atendimento com método + gorjeta → grava `Payment` | Comanda multi-item (serviços extras + produtos), desconto, pagamento dividido | `app/api/barbeiro.py:61` | Média | Crítico (item #3) |
| **Catálogo de serviços** | CRUD completo na API (criar, editar, arquivar, reativar) | **Página no frontend — a API está inacessível pela interface** | `app/api/servicos.py` (sem page.tsx) | **Baixa** | Alto |
| **Gestão de equipe** | `GET /equipe` (leitura: barbeiro, comissão, horários, folgas) | CRUD de barbeiro, folgas (TimeOff) e horários (BusinessHours) — hoje só via seed/SQL | `app/api/equipe.py` | Baixa-Média | Alto |
| **Reativação de inativos (convite de retorno)** | Serviço completo: alvos em risco/inativos, cooldown 60d, mensagem personalizada c/ barbeiro favorito e benefício, envio Evolution API | **Nenhum cron chama `POST /internal/loyalty/reactivation/run`** — o código nunca roda | `app/services/reactivation.py`, `app/api/loyalty.py:76` | **Baixa (criar 1 workflow n8n cron)** | Alto (item #5) |
| **Infra de mensageria** | `message_log` com direção, template, status de entrega, retry, idempotência | Dispatcher/worker; o bot não loga mensagens no `message_log` | `models/integration.py:130` | Média | Alto (base p/ lembretes) |
| **Multi-unidade** | Schema `organizations→units`, `barber_units`, timezone por unidade | API e UI fixam unidade única (`BOT_UNIT_ID`); sem seletor/consolidação | `models/unit.py`, `app/core/config.py` | Alta | Baixo agora (decisão correta do FEATURES_MASTER §12.3: não construir UI agora) |
| **Billing do SaaS** (cobrar o barbeiro-cliente) | `plans`, `subscriptions` (trial/active/past_due/canceled) no schema | Gateway de cobrança, gestão de assinatura, gating por plano, onboarding self-service | `models/organization.py` | Alta | Crítico p/ escalar venda (não p/ 1º cliente) |

### 🚨 IMPLEMENTADAS MAS COM PROBLEMAS

| Problema | Evidência | Arquivos | Esforço de correção | Impacto |
|---|---|---|---|---|
| **Fidelidade não recalcula no fluxo principal**: `PATCH /barbeiro/atendimento/{id}/concluir` (usado pelo painel admin e pelo barbeiro) **não chama** `loyalty.recalculate()` — só o `/bot/appointments/{id}/complete` chama. Visitas concluídas pelo painel não atualizam nível/status/contagem | `barbeiro.py` não importa `app.services.loyalty`; `bot.py:937` chama | `app/api/barbeiro.py` | **Trivial (1 linha + teste)** | Alto — corrompe o CRM/segmentação silenciosamente |
| **Filtros de data em UTC**: dashboard, financeiro e agenda fazem `cast(start_at, Date)` em UTC. Em Palmas (UTC-3), atendimentos de 21h–23h59 caem no dia seguinte; o "hoje" do dashboard vira às 21h local | `dashboard.py:35` (`datetime.now(timezone.utc).date()`), `financeiro.py:92`, `agenda.py:105` | os 3 arquivos | Baixa | Médio-Alto — números financeiros do dia errados |
| **Avaliações**: coluna `appointments.rating` existe com constraint 1–5, **nada escreve nem lê** | grep: nenhum endpoint usa `rating` | `models/appointment.py:82` | Baixa (já tem coluna) | Médio (item #13 — prova social) |
| **Estado do bot em memória de processo**: debounce, dedup e sessões em dicts Python — restart do FastAPI perde rajadas em andamento; impossibilita 2ª instância | `bot.py:49-61` | `app/api/bot.py` | Média (Redis) | Médio (aceitável p/ MVP single-instance; risco documentado) |
| **Endpoint de debug em produção**: `POST /bot/debounce/debug-set-session` (autenticado, mas é ferramenta de teste) | `bot.py:188` | `app/api/bot.py` | Trivial | Baixo |
| **CORS hardcoded em localhost** + URL da API default localhost no frontend — bloqueia qualquer deploy | `main.py:25`, `lib/api.ts:3` | `app/main.py` | Trivial (env var) | Crítico p/ vender (não dá pra hospedar) |

### ❌ NÃO IMPLEMENTADAS (na ordem do ranking comercial do FEATURES_MASTER §12.2)

| # rank | Funcionalidade | Estado no código | Dependências | Complexidade | Impacto |
|---|---|---|---|---|---|
| 1 | **Página pública de agendamento** (link/hotsite p/ Instagram, Google) | Nada. Único canal de cliente final é o WhatsApp | Endpoint público + página + anti-abuso | Média-Alta | **Crítico** — Trinks tabela de aposta mínima |
| 2 | **Lembrete 24h + confirmação de presença via WhatsApp** | ❌ worker inexistente. Infra 90% pronta: `message_log`, Evolution API, n8n, telefones E.164, consents | 1 cron n8n (ou APScheduler) + 1 endpoint interno | **Baixa** | **Crítico** — maior dor (no-show); na Trinks é add-on pago |
| 5b | **Mensagem de aniversário** | ❌ — `clients` **nem tem campo de data de nascimento** | migration + captura pelo bot/painel + cron | Baixa | Médio-Alto |
| 6 | **Clube de assinaturas** (recorrência cliente final) | ❌ nada (as `subscriptions` existentes são do SaaS, não do cliente final) | gateway recorrência (PIX/cartão), controle de uso | **Alta** | Alto (caso Trinks: triplicou faturamento de barbearia) |
| 7 | **Relatórios essenciais exportáveis** (CSV/PDF: faturamento, comissões p/ repasse, clientes) | ❌ só dashboard on-screen | dados já existem | Baixa-Média | Alto |
| 8 | **Pagamento de sinal anti no-show (PIX)** | ❌ nada | gateway PIX (Mercado Pago/Pagar.me), reconciliação, política de cancelamento | Alta | Médio-Alto (monetizável) |
| 9 | **Fila de espera digital (walk-in)** | ❌ nada | tabela + endpoints + UI/bot | Média | Médio |
| 11 | **Estoque/produtos com alertas** | ❌ sem tabelas `products`/`stock_movements` | comanda multi-item (venda de produto) | Média-Alta | Médio |
| 12 | **Fidelidade com resgate** (registrar uso do benefício, pontos) | Tiers e benefícios são só informativos; sem registro de resgate | tabela de resgates + UI/bot | Baixa-Média | Médio (lógica já existe) |
| 13 | **Avaliação pós-atendimento + pesquisa de satisfação** | ❌ (coluna `rating` órfã) | cron pós-conclusão via bot WhatsApp | Baixa | Médio |
| 14 | **Notas fiscais (NFS-e)** | ❌ nada | parceiro (Focus NFe/eNotas) | Alta | Baixo no MVP (per FEATURES_MASTER) |
| 15 | **Mapa de calor de ocupação** | ❌ (dados de agendamento já permitem) | dashboard | Baixa | Baixo-Médio |
| — | **Pacotes e promoções** | ❌ nada | tabelas + checkout | Média | Médio |
| — | **Agendamentos recorrentes** | ❌ nada | regra de recorrência + geração | Média | Baixo-Médio |
| — | **Google Calendar sync** | Só scaffolding (`integration_accounts`, `calendar_sync` sem código) | OAuth Google + worker | Média-Alta | Baixo (nem a Trinks tem) |
| — | **Despesas (CRUD)** | Modelo `Expense` pronto, zero endpoint/UI | — | **Baixa** | Alto (fecha o fluxo de caixa) |
| — | **Configurações pela UI** (horários da unidade, dados do estabelecimento, formas de pagamento) | ❌ tudo via seed/SQL | endpoints + página | Média | Alto p/ onboarding |
| — | **Onboarding self-service de novo tenant** | ❌ (seed manual) | signup + provisioning + billing | Alta | Crítico p/ escalar (não p/ 1º cliente) |
| — | **Marketing/campanhas segmentadas** (além da reativação) | ❌ | segmentos de loyalty já existem | Média | Médio |

### Ignoráveis no estágio atual (alinhado ao FEATURES_MASTER §12.3)
Marketplace B2C, app white-label nas stores, 130+ relatórios, maquininha/conta digital própria, totem, fichas de anamnese, comunidade/academia, Reserve with Google (longo prazo).

---

## 3. Sínteses

### MVP Comercial (mínimo para vender a 1ª assinatura)
1. Corrigir os 🚨 (loyalty no concluir, timezone, CORS/deploy) — sem isso os números mentem e não há como hospedar.
2. **Lembrete 24h + confirmação** — argumento de venda nº 1 (no-show) e a infra já está pronta.
3. Ativar reativação (cron n8n — o código já existe).
4. Página `/admin/servicos` (API pronta) + CRUD de equipe/folgas — sem isso o dono depende de você p/ mudar preço ou dar folga.
5. Despesas + financeiro mensal — fecha o ciclo "agendamento → receita → lucro".
6. Deploy real (VPS + domínio + HTTPS + backups).

### Funcionalidades Críticas (ausências que impedem competir)
- Página pública de agendamento (todo concorrente tem; hoje o cliente final só agenda por WhatsApp).
- Relatório de comissões p/ repasse (dor citada em todos os depoimentos de barbearia da Trinks).
- Configuração self-service (horários, serviços, profissionais) — sem isso não escala além de 1–2 clientes operados à mão.

### Quick Wins (esforço baixo × valor alto)
| Quick win | Esforço | Por quê |
|---|---|---|
| Fix: recalcular loyalty no `/barbeiro/concluir` | ~1 linha | Bug que corrompe o CRM |
| Cron n8n de reativação | ~1h | Código 100% pronto, nunca roda |
| Lembrete 24h via n8n + `message_log` | dias | Infra pronta; maior ROI do produto |
| Página de serviços no admin | dias | API completa já existe |
| Campo aniversário + automação | dias | Bot pode capturar conversacionalmente |
| Export CSV (financeiro/comissões/clientes) | dias | Queries já existem no dashboard |
| Pesquisa de avaliação pós-atendimento via bot | dias | Coluna `rating` já existe; bot já conversa com o cliente |
| Mapa de calor | dias | Dados já no banco |

### Funcionalidades Complexas (exigem mudança arquitetural / integração externa)
- Clube de assinaturas e pagamento de sinal → exigem **gateway de pagamento** (decisão estrutural: Mercado Pago vs Pagar.me vs Stripe) e reconciliação.
- Página pública de agendamento → primeiro endpoint não-autenticado voltado ao público (rate limit, abuse, captcha) + identidade visual por tenant.
- Onboarding self-service + billing → provisioning multi-tenant automatizado.
- Estoque + comanda multi-item → remodelagem do checkout (comanda como agregado).
- Redis para estado do bot → pré-requisito para alta disponibilidade/multi-instância.

---

## 4. Roadmap

### Fase 1 — Venda Imediata (maior ROI, menor esforço; ~2–4 semanas de trabalho)
| Ordem | Item | Tipo |
|---|---|---|
| 1.1 | Fix loyalty no `concluir` + fix timezone (America/Sao_Paulo nos filtros de data) + remover endpoint debug | 🚨 correção |
| 1.2 | CORS/URLs por env var + deploy (VPS, HTTPS, backup automatizado do Postgres) | infra |
| 1.3 | **Lembrete 24h antes + pedido de confirmação via WhatsApp** (cron n8n → `message_log`) | feature |
| 1.4 | Cron diário de reativação (chama `/internal/loyalty/reactivation/run`) | ativação |
| 1.5 | Página `/admin/servicos` (consumir CRUD existente) | UI |
| 1.6 | CRUD de equipe: criar/editar barbeiro, folgas, horários da unidade | feature |
| 1.7 | Despesas (CRUD sobre modelo existente) + visão financeira mensal com fluxo de caixa | feature |
| 1.8 | Export CSV: comissões para repasse + faturamento | feature |

**Resultado:** produto vendável para a barbearia âncora com o pitch "WhatsApp-first, lembrete e reativação inclusos no preço" (ataca o gap #1 e #3 da Trinks — add-ons pagos).

### Fase 2 — Paridade com Concorrentes (~1–2 meses)
| Ordem | Item |
|---|---|
| 2.1 | **Página pública de agendamento** (link compartilhável por barbearia, mobile-first, visual moderno — ataca o hotsite datado da Trinks) |
| 2.2 | Avaliação pós-atendimento via bot (grava `rating`) + exibição de média |
| 2.3 | Aniversário: campo + captura via bot + mensagem automática |
| 2.4 | Comissões por serviço + relatório de fechamento por período |
| 2.5 | Comanda multi-item (vários serviços + desconto) no checkout |
| 2.6 | Fila de espera digital (walk-in) gerenciada pelo bot e pelo painel |
| 2.7 | Pagamento de sinal via PIX (gateway) para horários de pico |
| 2.8 | Relatórios essenciais (10–15 bem feitos: faturamento, serviços, profissionais, clientes, no-show) |
| 2.9 | Configurações da unidade pela UI (horários, dados, formas de pagamento) |

### Fase 3 — Diferenciais (~3+ meses)
| Ordem | Item |
|---|---|
| 3.1 | **Clube de assinaturas** (recorrência PIX/cartão — maior alavanca de receita do nicho) |
| 3.2 | Fidelidade com resgate de benefícios (registro de uso; tiers já existem) |
| 3.3 | Pacotes e promoções |
| 3.4 | Mapa de calor + insights de IA no dashboard ("terças 14h estão vazias — sugerir promoção via WhatsApp") |
| 3.5 | Campanhas segmentadas (VIP/Fiel/Em risco) disparadas pelo painel via bot |
| 3.6 | Estoque/produtos com baixa na comanda + alertas |
| 3.7 | Onboarding self-service + billing do SaaS (escala comercial) |
| 3.8 | Redis p/ estado do bot (multi-instância), Google Calendar sync, NF via parceiro |

---

## 5. Tabela mestra ordenada por Valor Comercial → Facilidade → ROI

| Pos | Funcionalidade | Status atual | Valor comercial | Facilidade | ROI |
|---|---|---|---|---|---|
| 1 | Lembrete 24h + confirmação WhatsApp | ❌ (infra pronta) | Crítico | Alta | ⭐⭐⭐⭐⭐ |
| 2 | Fix loyalty no concluir do painel | 🚨 | Alto (integridade) | Trivial | ⭐⭐⭐⭐⭐ |
| 3 | Cron de reativação (já codificado) | 🟡 | Alto | Trivial | ⭐⭐⭐⭐⭐ |
| 4 | Deploy + CORS/env (vendabilidade) | 🚨 | Crítico | Alta | ⭐⭐⭐⭐⭐ |
| 5 | Fix timezone nos filtros de data | 🚨 | Alto (números certos) | Alta | ⭐⭐⭐⭐ |
| 6 | Página admin de serviços | 🟡 (API pronta) | Alto | Alta | ⭐⭐⭐⭐ |
| 7 | CRUD equipe/folgas/horários | 🟡 | Alto | Média | ⭐⭐⭐⭐ |
| 8 | Despesas + financeiro mensal | 🟡 (modelo pronto) | Crítico | Média | ⭐⭐⭐⭐ |
| 9 | Export CSV (comissões/faturamento) | ❌ | Alto | Alta | ⭐⭐⭐⭐ |
| 10 | Página pública de agendamento | ❌ | Crítico | Média-Baixa | ⭐⭐⭐⭐ |
| 11 | Avaliação pós-atendimento via bot | 🚨 (coluna órfã) | Médio | Alta | ⭐⭐⭐ |
| 12 | Aniversário (campo + automação) | ❌ | Médio-Alto | Alta | ⭐⭐⭐ |
| 13 | Comissões por serviço + fechamento | 🟡 | Alto | Média | ⭐⭐⭐ |
| 14 | Comanda multi-item + desconto | 🟡 | Alto | Média | ⭐⭐⭐ |
| 15 | Relatórios essenciais (10–15) | ❌ | Alto | Média | ⭐⭐⭐ |
| 16 | Fila de espera digital | ❌ | Médio | Média | ⭐⭐⭐ |
| 17 | Sinal via PIX | ❌ | Médio-Alto | Baixa | ⭐⭐⭐ |
| 18 | Configurações via UI | ❌ | Alto (escala) | Média | ⭐⭐⭐ |
| 19 | Clube de assinaturas | ❌ | Alto | Baixa | ⭐⭐⭐ |
| 20 | Fidelidade com resgate | 🟡 | Médio | Alta | ⭐⭐⭐ |
| 21 | Mapa de calor | ❌ | Baixo-Médio | Alta | ⭐⭐ |
| 22 | Pacotes/promoções | ❌ | Médio | Média | ⭐⭐ |
| 23 | Campanhas segmentadas | ❌ | Médio | Média | ⭐⭐ |
| 24 | Estoque + alertas | ❌ | Médio | Baixa | ⭐⭐ |
| 25 | Onboarding self-service + billing | ❌ | Crítico p/ escala | Baixa | ⭐⭐ (no momento) |
| 26 | Redis p/ bot (HA) | 🚨 (in-memory) | Baixo agora | Média | ⭐⭐ |
| 27 | Recorrência de agendamentos | ❌ | Baixo-Médio | Média | ⭐⭐ |
| 28 | Google Calendar sync | ❌ (scaffolding) | Baixo | Baixa | ⭐ |
| 29 | NF (NFS-e via parceiro) | ❌ | Baixo no MVP | Baixa | ⭐ |
| 30 | Multi-unidade (UI) | 🟡 (schema pronto) | Baixo agora | Baixa | ⭐ |

---

*Documento gerado por gap analysis automatizado — nenhum código foi alterado. Fontes: leitura integral de `FEATURES_MASTER.md` e auditoria de todos os arquivos de `app/`, `models/`, `barbearia-frontend/`, `workflows.json` e `schema.sql`.*
