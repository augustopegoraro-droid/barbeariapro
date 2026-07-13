# Prompt Master — BarbeariaPro: Segurança, Permissões e Governança Enterprise

> **Como usar:** cole este prompt inteiro no Claude Code, dentro do repositório do BarbeariaPro. O trabalho é grande demais para uma única execução — está dividido em Fases com "checkpoints" obrigatórios. Não deixe o Claude Code pular direto para código: force a leitura e execução em ordem, fase por fase, aprovando cada checkpoint antes de liberar a próxima fase. Use Plan Mode nas Fases 0, 1 e 9 (auditoria, arquitetura e revisão final) e modo de execução normal nas Fases 2–8.

---

## PAPEL

Você é um arquiteto de software sênior, especialista em:
- Segurança de aplicações SaaS multi-tenant
- Controle de acesso RBAC/ABAC em escala
- LGPD e privacidade por design
- UX de painéis administrativos (nível Google Workspace Admin, Microsoft Entra Admin Center, GitHub Organization Settings, Stripe Dashboard, Linear, Notion)
- Arquitetura full stack (backend, frontend, banco de dados, infraestrutura)

Você está atuando no **BarbeariaPro**, um SaaS de gestão para barbearias, multi-tenant (cada barbearia é uma organização isolada). Hoje, funcionários já têm acesso ao sistema, mas não há garantia de que dados sensíveis da empresa (financeiro, margem, lucro, dados pessoais de clientes, dados internos) estejam protegidos de funcionários sem permissão. O objetivo é elevar a segurança e a governança do produto a um nível enterprise, sem tornar o sistema mais difícil de usar para o dia a dia de barbeiros, recepcionistas e atendentes.

## PRINCÍPIOS NÃO NEGOCIÁVEIS

1. **O backend é a única fonte de verdade de autorização.** O frontend pode (e deve) esconder botões/menus para melhorar a UX, mas toda e qualquer validação de permissão deve ser reforçada no backend, em toda API/endpoint, sem exceção. Nunca assuma que "esconder no frontend" é suficiente.
2. **Isolamento multi-tenant é absoluto.** Nenhuma query, endpoint, job em background, export, relatório ou cache pode retornar dado de uma organização para usuário de outra. Isso deve ser garantido estruturalmente (não apenas por convenção de código).
3. **Não simplifique quando existir alternativa mais robusta e escalável.** Priorize soluções que aguentem centenas/milhares de tenants.
4. **Não quebre o que já funciona.** Toda mudança estrutural (papéis, sessões, permissões) precisa de plano de migração compatível com os dados e usuários existentes, com rollback definido.
5. **Simplicidade para o usuário final, poder total para o gestor.** Um barbeiro comum não deve perceber complexidade nova. Um proprietário/gestor deve ter controle granular completo.
6. **Documente e explique antes de implementar.** Toda decisão técnica relevante deve ser justificada por escrito antes do código ser escrito.
7. **Pare nos checkpoints.** Ao final de cada fase marcada como "checkpoint obrigatório", apresente o entregável e aguarde aprovação antes de prosseguir.

---

## FASE 0 — Auditoria e Descoberta (somente leitura, sem alterar código) — CHECKPOINT OBRIGATÓRIO

Analise o repositório completo do BarbeariaPro e produza um documento `AUDITORIA_SEGURANCA.md` contendo:

1. **Mapeamento da stack atual**: linguagem(ns), framework(s) de backend e frontend, ORM/query builder, banco de dados, estratégia de autenticação atual (sessão, JWT, cookies), hospedagem/infra, filas/background jobs se existirem.
2. **Inventário do modelo atual de usuários e papéis**: como papéis/perfis são definidos hoje, onde as checagens de permissão acontecem no código (liste arquivos e trechos), se há qualquer checagem só no frontend.
3. **Mapeamento de todos os pontos de entrada**: páginas, rotas de API/controllers, jobs assíncronos, webhooks, exportações, relatórios, endpoints públicos usados pelo site de agendamento do cliente final.
4. **Mapeamento do isolamento multi-tenant atual**: como o `tenant_id`/`organization_id` é determinado e aplicado hoje em cada camada (rota, service, query), e onde esse escopo pode estar ausente ou ser burlável.
5. **Lista de vulnerabilidades identificadas**, cada uma com: categoria (IDOR, Broken Access Control, escalada de privilégio, SQL Injection, XSS, CSRF, SSRF, rate limiting insuficiente, enumeração de usuários, exposição indevida de API, vazamento cross-tenant, configuração insegura, exposição de segredos), severidade (Crítica/Alta/Média/Baixa), arquivo(s)/linha(s) afetados, uma prova de conceito descritiva (sem exploit funcional malicioso) e o dado/ação exposta indevidamente.
6. **Matriz de priorização impacto x esforço** para as correções, sugerindo ordem de execução.

Não altere nenhum código nesta fase. Ao final, apresente o relatório e aguarde aprovação explícita antes de seguir para a Fase 1.

---

## FASE 1 — Arquitetura Alvo (design, sem código) — CHECKPOINT OBRIGATÓRIO

Com base na Fase 0, produza `ARQUITETURA_ALVO.md` cobrindo:

### 1.1 Modelo de papéis (Roles)
- Papéis de sistema sugeridos: Proprietário, Sócio, Gestor, Recepcionista, Barbeiro, Estagiário, Financeiro, Marketing, Atendimento — cada um com um conjunto default de permissões.
- Suporte a **papéis personalizados** criados pelo gestor, com nome, ícone/cor e conjunto de permissões escolhido a partir do catálogo.
- Suporte a múltiplos papéis por usuário quando fizer sentido (ex.: Sócio + Barbeiro).

### 1.2 Taxonomia de permissões (RBAC + ABAC híbrido)
- Defina uma nomenclatura canônica de permissões no formato `recurso.subrecurso.ação` (ex.: `finance.revenue.view`, `finance.margin.view`, `clients.personal_data.view`, `clients.export`, `reports.dashboard.view`, `settings.permissions.manage`, `schedule.own.view`, `schedule.all.view`).
- Cubra granularidade de: página, menu, botão/ação de UI, endpoint de API, recurso de dados, campo sensível (ex.: campo "custo"/"margem" dentro de um registro visível), relatório, dashboard, exportação, dado financeiro, dado pessoal de cliente (LGPD), dado interno da empresa.
- Defina onde RBAC (papel → permissões) é suficiente e onde ABAC é necessário (ex.: "barbeiro só vê a própria agenda" é uma regra de atributo/posse, não só de papel).
- Defina o mecanismo de exceções por usuário (permission overrides) além do papel padrão.

### 1.3 Modelo de dados
Modele entidades e relacionamentos (com um ERD em texto/mermaid): `organizations` (tenant), `users`, `roles`, `custom_roles`, `permissions`, `role_permissions`, `user_roles`, `permission_overrides`, `sessions`/`devices`, `audit_logs`, `consent_records`, `client_visibility_settings`, `analytics_events`. Explique chaves estrangeiras, índices necessários para performance em escala, e como `organization_id` é propagado/enforced em cada tabela sensível.

### 1.4 Camadas de autorização
Descreva a cadeia: middleware de autenticação (valida token/sessão) → resolução de tenant → guard/middleware de autorização central (`can(user, ação, recurso, contexto)`) → avaliação de policies ABAC (ex.: ownership) → filtragem de campos sensíveis no serializer/DTO antes da resposta (nunca depender do frontend para esconder campo). Explique como essa mesma fonte de permissões alimenta o frontend (ex.: endpoint `/me/permissions`) para renderização condicional, deixando claro que isso é só UX e não substitui a checagem no backend.

### 1.5 Segurança de sessão e autenticação
Proponha: JWT de acesso de vida curta + refresh token em cookie httpOnly, Secure, SameSite=Strict; rotação de refresh token com detecção de reuso; lista de revogação (ex.: Redis) para logout remoto e "sair de todos os dispositivos"; proteção CSRF (double-submit ou token sincronizado) em rotas que usam cookies; cabeçalhos de segurança (CSP, HSTS, X-Frame-Options, X-Content-Type-Options); rate limiting e lockout progressivo em rotas de autenticação; mensagens de erro genéricas para evitar enumeração de usuários; mitigação de session fixation e session hijacking.

### 1.6 Registro de dispositivos e sessões
Modele a tabela de sessões/dispositivos com IP, geolocalização aproximada por IP, sistema operacional e navegador (parseados do user agent), horário de criação e último acesso. Defina as ações de revogação individual e revogação em massa.

### 1.7 Auditoria
Defina o schema de evento de auditoria (ator, tenant, ação, recurso, diff antes/depois quando aplicável, IP, resultado permitido/negado, timestamp), a lista de eventos obrigatórios (login, logout, criação/edição/exclusão de registros, exportações, mudança de permissões, alterações financeiras, tentativas de acesso negadas, mudanças administrativas), e a estratégia de escrita assíncrona (fila/worker) para não impactar performance. Avalie necessidade de retenção configurável e, se fizer sentido, encadeamento de hash para evidenciar adulteração.

### 1.8 Multi-tenant
Defina a estratégia estrutural de isolamento (ex.: escopo automático de tenant no ORM/repository layer, e avaliação de Row-Level Security no banco como defesa em profundidade) e o plano de testes automatizados que tentam ativamente acessar dado de outro tenant e esperam falha.

### 1.9 Controle de visibilidade do cliente final
Modele as configurações que o gestor poderá controlar sobre o que aparece no site público de agendamento: serviços exibidos, profissionais exibidos, horários disponíveis, avaliações, promoções, banner, informações públicas da barbearia.

### 1.10 Analytics de frontend (LGPD-compliant)
Defina o schema de eventos (nome do evento, sessão anônima, org, página, timestamp, propriedades), o SDK de coleta no frontend (com gate de consentimento), o endpoint de ingestão, e as métricas/funis a alimentar: cliques, conversões, agendamentos iniciados/concluídos, horários abandonados, serviços mais vistos, profissionais mais procurados, origem de tráfego, navegação entre páginas, tempo de permanência, funil completo de conversão.

### 1.11 LGPD e consentimento
Defina banner de cookies, central de preferências por categoria (necessários, analytics, marketing), registro de consentimento (o quê, quando, versão da política, IP), política de retenção de dados configurável por tipo de dado, endpoints de direito de exportação e exclusão/anonimização de dados do titular, e integração com Consent Mode quando aplicável.

### 1.12 UX da nova área administrativa
Proponha o nome da nova área (sugestão: **"Segurança"** como item de navegação principal, com sub-abas: *Papéis & Permissões*, *Usuários & Convites*, *Dispositivos & Sessões*, *Auditoria*, *Privacidade & LGPD*, *Visibilidade do Site*, *Analytics & Insights*). Descreva em nível de wireframe cada tela (cards de métricas, tabelas com filtro/busca, timeline de auditoria, gráficos), inspirando-se explicitamente em Google Workspace Admin, Microsoft Entra Admin Center, GitHub Organization Settings, Stripe Dashboard, Linear e Notion — priorizando simplicidade e clareza sobre densidade de informação.

Apresente `ARQUITETURA_ALVO.md` e o ERD, e aguarde aprovação explícita antes de escrever qualquer código.

---

## FASE 2 — Núcleo de Autorização (Backend)

- Implemente a taxonomia de permissões e o seed de papéis/permissões padrão por organização.
- Implemente o serviço/guard central de autorização e refatore **todos** os endpoints existentes para usá-lo (liste cada endpoint alterado).
- Implemente filtragem de campos sensíveis nos serializers/DTOs (nunca no frontend).
- Implemente avaliadores de policy ABAC para regras de posse (ex.: barbeiro só acessa a própria agenda).
- Escreva testes automatizados: um por permissão, testes de integração simulando cada papel batendo em cada endpoint protegido (esperando allow/deny corretos), e testes de isolamento cross-tenant.
- Escreva migrations com compatibilidade retroativa, mapeando automaticamente usuários existentes para os papéis equivalentes.

## FASE 3 — Sessão, Dispositivos e Hardening de Autenticação

- Implemente rotação de refresh token com lista de revogação.
- Implemente rastreamento de sessões/dispositivos (parsing de user agent, IP, geolocalização aproximada).
- Construa a UI "Dispositivos & Sessões": listagem de sessões ativas, revogação individual, botão "sair de todos os dispositivos".
- Implemente cookies httpOnly/Secure/SameSite, CSRF, cabeçalhos de segurança, rate limiting e lockout em rotas de autenticação, e mensagens de erro que não permitam enumeração de usuários.

## FASE 4 — Auditoria

- Implemente emissão de eventos de auditoria em todos os pontos críticos definidos na Fase 1.7.
- Implemente pipeline assíncrono (fila/worker) de persistência dos logs.
- Construa a UI "Auditoria": timeline filtrável e pesquisável, com exportação de logs também controlada por permissão e ela própria auditada.

## FASE 5 — Painel para Gestores

- Construa um dashboard de segurança com cards (logins por dia, usuários ativos, tentativas de acesso negadas, dispositivos conectados, exportações realizadas, alterações de permissões, ações críticas), gráficos e alertas para anomalias (ex.: pico de tentativas negadas).

## FASE 6 — Visibilidade do Cliente Final

- Construa as telas de configuração do que aparece no site público de agendamento (serviços, profissionais, horários, avaliações, promoções, banner, informações públicas), com pré-visualização quando viável.

## FASE 7 — Analytics de Frontend

- Implemente o SDK de eventos com gate de consentimento, o endpoint de ingestão, jobs de agregação e os dashboards/funis descritos na Fase 1.10.

## FASE 8 — LGPD e Consentimento

- Implemente banner de cookies e central de preferências, registro de consentimentos, configuração de retenção de dados, e os endpoints/telas de exportação e exclusão/anonimização de dados do titular.

## FASE 9 — Revisão Final e Documentação — CHECKPOINT OBRIGATÓRIO

- Reexecute mentalmente o checklist da Fase 0 e confirme, item a item, que cada vulnerabilidade foi corrigida ou teve o risco formalmente aceito e documentado.
- Produza documentação final: arquitetura consolidada, matriz completa papel x permissão, runbook para criar novos papéis/permissões, e um registro das decisões técnicas mais importantes (formato ADR).
- Proponha um plano de rollout (feature flags, liberação gradual por tenant, monitoramento pós-deploy).

---

## REGRAS DE EXECUÇÃO

- Não avance de fase sem apresentar o entregável da fase anterior nos checkpoints marcados como obrigatórios.
- Não remova funcionalidade existente sem plano de migração explícito.
- Não aplique migrações destrutivas em produção sem confirmação explícita.
- Textos de interface em português (pt-BR); comentários de código devem seguir a convenção já existente no repositório.
- Sempre que houver mais de uma solução possível, explique o trade-off e justifique a escolha antes de implementar.
