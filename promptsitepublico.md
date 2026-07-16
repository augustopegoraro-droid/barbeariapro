# Prompt Master — BarbeariaPro: Site Público de Agendamento + Login Persistente do Cliente Final

> **Como usar:** cole este prompt inteiro no Claude Code, dentro do repositório do BarbeariaPro. Assim como
> `promptseguranca.md`, o trabalho é grande demais para uma única execução — está dividido em Fases com
> "checkpoints" obrigatórios. Não deixe o Claude Code pular direto para código: force a leitura e execução em
> ordem, fase por fase, aprovando cada checkpoint antes de liberar a próxima. Use Plan Mode nas Fases 0, 1 e 8
> (descoberta, arquitetura e revisão final) e modo de execução normal nas Fases 2–7.

---

## PAPEL

Você é um arquiteto de produto e engenharia sênior, especialista em:
- Sites/PWAs de agendamento voltados a consumidor final (mobile-first), no estilo Booksy/Trinks/Fresha
- Autenticação passwordless e sessão de longuíssima duração em navegador móvel (iOS Safari e Android Chrome têm
  comportamentos diferentes de persistência — isso é o núcleo técnico deste projeto, não um detalhe)
- Multi-tenant por subdomínio
- LGPD aplicada a dado de cliente final (não de funcionário)

Você está atuando no **BarbeariaPro**, o mesmo SaaS multi-tenant do `promptseguranca.md` (Segurança/Governança,
já com Fases 0–6 prontas — RBAC por permissões, auditoria, painel de segurança, configuração de visibilidade do
site público). **Este prompt constrói o site em si.**

## PRINCÍPIO CENTRAL — LOGIN PERSISTENTE (não negociável, é o motivo deste documento existir)

> O cliente final autentica **uma única vez**, no primeiro acesso, sem senha. A partir daí, ele **nunca mais
> digita login/senha no mesmo aparelho** — a sessão sobrevive indefinidamente (dias, meses, anos). Só é pedido
> para autenticar de novo se: (a) trocar de aparelho/navegador, (b) limpar os dados do navegador/desinstalar o
> app, ou (c) fizer logout explícito. Isso vale mais do que qualquer outro requisito de UX deste site — se uma
> decisão técnica colocar em risco esse comportamento, pare e pergunte antes de prosseguir.

Implicações técnicas que a Fase 0/1 precisam resolver de verdade (não assumir):
- **Sem senha.** Identidade é o telefone (já é a chave natural do `Client.phone_e164` no backend). Primeiro
  acesso = telefone → código de verificação (OTP) via WhatsApp (a barbearia já tem WhatsApp Cloud API, D-49) →
  sessão emitida.
- **Sessão de vida longuíssima**, não os 15 minutos do JWT do painel administrativo (D-68) — este é um domínio de
  identidade **separado** do `User`/`sessions` da equipe. Modelar `client_sessions`/`client_auth_otp` própria,
  não reaproveitar as tabelas de staff.
- **iOS Safari tem ITP** (Intelligent Tracking Prevention) que historicamente limita a vida de cookies/
  localStorage em site aberto pelo Safari "solto" (fora de tela inicial) a poucos dias. A saída conhecida do
  mercado é **PWA instalável** (`Adicionar à Tela de Início`) — dados de um PWA instalado não sofrem esse cap.
  A Fase 0 precisa confirmar o comportamento atual (isso muda de versão em versão do iOS) e a Fase 1 precisa
  decidir a estratégia (forçar instalação como PWA no primeiro acesso? aceitar re-login ocasional no Safari não
  instalado como fallback tolerável?). **Não assuma que "salvar num cookie" resolve — pesquise antes.**
- **Revogação remota é o contrapeso de segurança de uma sessão que nunca expira sozinha**: o cliente precisa de
  uma tela "meus dispositivos" (autoatendimento) para encerrar sessões de aparelhos perdidos/trocados — mesmo
  espírito da tela de sessões da equipe (D-68), mas para o próprio cliente.

## OUTROS PRINCÍPIOS NÃO NEGOCIÁVEIS

1. **Multi-tenant por subdomínio**, reaproveitando `app_org_id_by_subdomain` (D-54). **Hosts decididos pelo dono
   (D-78, 2026-07-16 — substitui o `org.taylorethedy.com` do D-66):** `taylorethedy.com` (apex) = **este site
   público**, com a logo da Taylor & Thedy em destaque; `app.taylorethedy.com` = portal dos profissionais/
   gestores (o painel que hoje responde em `taylor.taylorethedy.com`, com redirect 301 na transição). Plano de
   migração de domínios (DNS/banco/nginx/CORS) detalhado na D-78 do `DECISIONS.md` — pode ser executado antes
   e independentemente do site.
2. **`client_visibility_settings` (D-73) já existe e é a fonte de verdade do que aparece** — serviços,
   profissionais, horários, avaliações, promoções, banner, dados públicos. Este site **consome** essa
   configuração via um endpoint público novo (read-only, sem autenticação, escopado por subdomínio) — não
   duplique essa configuração em lugar nenhum.
3. **O backend segue sendo a única fonte de verdade** de agenda/conflito/preço — o site público chama a mesma
   camada de validação de agendamento já usada pelo painel (`app/services/scheduling.py`), nunca reimplementa
   regra de negócio no frontend.
4. **Mobile-first de verdade** — a maioria dos clientes vai abrir pelo celular, boa parte pelo link que a
   própria Raquel manda no WhatsApp. Teste real em viewport de celular antes de considerar pronto.
5. **LGPD desde o primeiro commit**: coleta mínima (telefone, nome — nada além do que o agendamento exige),
   consentimento explícito no primeiro acesso, e a sessão de longa duração precisa de política de retenção e
   revogação claras (ver Fase 8 do `promptseguranca.md`, que ainda não foi feita e este site vai alimentar com
   dado real de titular externo).
6. **Não quebrar o painel administrativo existente** — este é código novo, isolado (`app/api/public.py` ou
   equivalente + app frontend novo, provavelmente outro projeto Next.js como `barbearia-frontend`/
   `barbearia-superadmin` já são), não um retrofit do admin.
7. **Documente e explique antes de implementar.** Toda decisão técnica relevante (em especial a estratégia de
   sessão persistente) precisa ser justificada por escrito antes do código.
8. **Pare nos checkpoints.**

---

## FASE 0 — Descoberta e Auditoria (leitura/pesquisa, sem código) — CHECKPOINT OBRIGATÓRIO

Produza `AUDITORIA_SITE_PUBLICO.md`:

1. **Estado atual real:** confirme que não existe nenhum site público hoje (a auditoria de segurança já
   confirmou isso na Fase 0 do `promptseguranca.md` — revalide, código muda). Mapeie o que já existe e pode ser
   reaproveitado: `client_visibility_settings` (D-73), `Client`/`phone_e164`, `app/services/scheduling.py`,
   WhatsApp Cloud API (D-49), resolução de subdomínio (D-54).
2. **Pesquisa técnica de sessão persistente em mobile web** (é o item de maior risco do projeto): comportamento
   atual de iOS Safari (PWA instalado vs. aba solta) e Android Chrome quanto a `localStorage`/cookies/
   `IndexedDB` de longa duração; como apps do mercado (Booksy, iFood, Uber) resolvem "fica logado para sempre no
   celular"; viabilidade de refresh token de vida longa com rotação silenciosa (mesmo espírito do D-68, adaptado
   para sessão de meses/anos em vez de dias).
3. **Fluxo de OTP via WhatsApp:** confirme com a infra atual (Evolution/Cloud API, D-41/D-49) se dá para enviar
   um código de verificação pelo número da própria barbearia, custo por envio, limites de taxa da Meta.
4. **Benchmark de UX** de 2–3 concorrentes (ex.: Booksy, Trinks) focado especificamente no fluxo de primeiro
   acesso e nos dias seguintes (será que pedem login de novo?).
5. **Matriz de risco:** o que pode dar errado na promessa "nunca mais loga" (ex.: Safari mudar comportamento de
   ITP numa atualização, usuário limpar cache) e qual o fallback aceitável em cada caso.

Não escreva código nesta fase. Apresente e aguarde aprovação.

## FASE 1 — Arquitetura (design, sem código) — CHECKPOINT OBRIGATÓRIO

Produza `ARQUITETURA_SITE_PUBLICO.md`:

1. **Fluxo de autenticação completo:** telefone → OTP (WhatsApp) → verificação → emissão de sessão. Diagrama do
   ciclo de vida do token (emissão, rotação silenciosa, expiração real se houver, revogação).
2. **Modelo de dados:** `client_sessions` (device_label, user_agent, ip, criado_em, último_acesso, revogado_em —
   mesmo espírito de `sessions`/D-68, mas para `Client`), `client_auth_otp` (código hasheado, expiração curta,
   tentativas, rate limit). RLS por org como todo o resto do schema.
3. **Endpoints públicos** (sem JWT de staff, escopados por subdomínio via `app_org_id_by_subdomain`):
   `GET /public/{subdomain}/info` (consome `client_visibility_settings`), `POST /public/{subdomain}/auth/
   request-otp`, `POST /public/{subdomain}/auth/verify-otp`, listagem de horários disponíveis, criação de
   agendamento, `GET/DELETE` de "meus agendamentos" e "meus dispositivos" autenticados pela sessão do cliente.
4. **Estratégia de PWA:** manifest, ícone, `Adicionar à Tela de Início`, se e como incentivar/forçar a instalação
   no primeiro acesso para mitigar o cap do iOS (Fase 0, item 2).
5. **Design/UX:** wireframe das telas principais (home da barbearia, escolha de serviço/profissional/horário,
   confirmação, "meus agendamentos", "meus dispositivos"), inspirado no benchmark da Fase 0. Reusa
   `client_visibility_settings.banner`/`public_info` para a identidade visual básica.
6. **Segurança do OTP:** rate limit por telefone+IP, anti-enumeração, expiração curta (minutos), backoff
   progressivo — mesmo rigor do `login_max_attempts` do D-68, adaptado.
7. **LGPD:** o que é coletado, banner de consentimento no primeiro acesso, como isso alimenta a Fase 8 do
   `promptseguranca.md` (`consent_records`).

Apresente e aguarde aprovação explícita antes de qualquer código.

## FASE 2 — Núcleo de autenticação do cliente final (backend)

- `client_sessions` + `client_auth_otp` (migration), envio de OTP via WhatsApp, verificação, emissão/rotação de
  sessão de longa duração, revogação (individual + "sair de todos os dispositivos").
- Testes: fluxo completo de OTP, rate limit, isolamento entre orgs, revogação.

## FASE 3 — Endpoint público de leitura (consumo do `client_visibility_settings`)

- `GET /public/{subdomain}/info` — serviços/profissionais/horários/banner/dados públicos, respeitando
  exatamente o que o D-73 configura. Cache razoável (não é dado que muda a cada segundo).

## FASE 4 — Fluxo de agendamento pelo cliente

- Listagem de horários disponíveis (reusa a validação de conflito do `scheduling.py`), criação de agendamento
  autenticado pela sessão do cliente, confirmação, cancelamento/remarcação dentro das regras que o gestor
  definir.

## FASE 5 — Frontend PWA

- App novo (mobile-first), fluxo de OTP, agendamento, "meus agendamentos", "meus dispositivos". Instalação como
  PWA. Visual a partir de `client_visibility_settings` (banner, cores básicas se vier a existir esse campo).

## FASE 6 — Notificações ao cliente

- Confirmação/lembrete de agendamento pelo mesmo canal WhatsApp já usado pelo bot "Raquel" (D-49) — reaproveitar,
  não duplicar a camada de envio.

## FASE 7 — LGPD do cliente final

- Banner de consentimento, central de preferências, exportação/exclusão dos próprios dados — alimenta e reusa a
  Fase 8 do `promptseguranca.md` (`consent_records`), não cria um sistema de consentimento paralelo.

## FASE 8 — Revisão final e rollout — CHECKPOINT OBRIGATÓRIO

- Revalide a promessa central (login persistente) com teste manual real em iPhone e Android, não só teoria.
- Plano de rollout (piloto com uma unidade/organização antes de abrir para todas).

---

## MELHORIAS INCORPORADAS (análise de 2026-07-16, cruzada com a logística atual do sistema — ver D-78)

As fases acima devem absorver os pontos abaixo (cada um indica a fase dona):

1. **[Fase 0 — DEPENDÊNCIA DE CAMINHO CRÍTICO] OTP via WhatsApp está bloqueado hoje.** O princípio central
   assume "a barbearia já tem WhatsApp Cloud API (D-49)", mas o D-49 é só plano: o número atual está **restrito**
   (D-41) e não entrega mensagens. Ou a Fase 0 do Chatwoot/Cloud API vira pré-requisito deste site, ou a Fase 1
   especifica um fallback de OTP por **SMS** (Twilio/Zenvia, ~R$0,10/envio). Não iniciar a Fase 2 sem esse
   destravamento resolvido.
2. **[Fase 1/4] Não existe endpoint de "horários disponíveis".** `scheduling.py` só detecta conflito na criação;
   o site precisa de listagem de slots livres (serviço × profissional × dia, considerando `TimeOff` e horário de
   funcionamento do D-45). Construir como serviço novo em `app/services/` para reúso pelo painel e pelo bot.
3. **[Fases 2/3] Reusar o Redis do D-68**: rate limit do OTP (telefone+IP) e cache do
   `GET /public/{subdomain}/info` — não inventar outra camada.
4. **[Fases 2/4] Auditar ações do cliente final no `audit_logs` (D-70):** OTP solicitado/verificado, agendamento
   criado/cancelado, sessão revogada — alimenta de graça o painel de segurança (D-71).
5. **[Fases 2/5] Merge com a base existente:** o cliente que verificar o telefone deve casar por `phone_e164`
   (mesmo `normalize_phone` do import da Trinks — ~2.913 clientes reais na org 1) e enxergar histórico, **pontos
   de fidelidade (D-50/D-62) e assinatura (D-44/D-48)** — nunca nascer duplicado. Exibir fidelidade/vouchers no
   site é diferencial de retenção já pronto no backend.
6. **[Fase 5] SEO/conversão no apex:** SSR/ISR (não SPA pura), dados estruturados `LocalBusiness`, Open Graph
   com a logo, página rápida (link aberto do WhatsApp em 4G).
7. **[Fase 1] Regras de cancelamento/remarcação configuráveis** (antecedência mínima, limite de remarcações)
   precisam de um lugar definido: `client_visibility_settings` ou tabela irmã — decidir na arquitetura.
8. **[Fase 6] Estender `reminders.py`**, que já faz o lembrete 24h, para agendamentos nascidos no site — não
   criar canal paralelo de notificação.
9. **[Fase 5] Logo por org:** não existe asset de logo no repo; adicionar `logo_url` ao `public_info` (JSONB do
   `client_visibility_settings`, sem migration) + upload na tela `/admin/seguranca/visibilidade`. Para a Taylor
   & Thedy, começar com arquivo estático fornecido pelo dono e evoluir para upload.

---

## REGRAS DE EXECUÇÃO

- Não avance de fase sem apresentar o entregável da fase anterior nos checkpoints obrigatórios.
- Se a pesquisa da Fase 0 mostrar que "nunca mais loga" é tecnicamente impossível de garantir 100% (ex.: Safari
  sem PWA instalado), não finja que resolveu — apresente o trade-off real e a UX de fallback antes de seguir.
- Textos de interface em português (pt-BR); comentários de código seguem a convenção já existente no repositório.
- Sempre que houver mais de uma solução possível, explique o trade-off e justifique a escolha antes de implementar.
