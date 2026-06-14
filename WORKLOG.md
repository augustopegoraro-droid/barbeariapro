# WORKLOG — BarbeariaPro

Registro de evolução autônoma (dev sênior). Datas em fuso local (America/Araguaina).

## 2026-06-13

### Concluído
- **Code review Fase 1 (commit 3b144ff, main)** — 12 fixes de correctness: flush antes do recálculo de loyalty; filtros LGPD na reativação; validações no booking do bot (bloqueado/deletado/BarberService); normalização de telefone unificada (`app/core/phone.py`); idempotency_key de lembrete com start_at; TimeOff nos checks de conflito (`app/services/scheduling.py`); serviço novo vinculado a barbeiros; price_charged alinhado com loyalty; seed commission_pct; timezone local no bot; contadores excluindo deletados; higiene de segredos. **99 testes backend passando.**
- **Frontend tipagem (commit dadc7e3, barbearia-frontend/main)** — elimina `any` em auth/middleware via augmentation de `User`/`JWT` do next-auth; helper `getErrorDetail` tipado em `lib/api.ts`; remove código morto. tsc limpo, build OK, lint 16→10 erros.
- **Next 16: middleware → proxy (commit, barbearia-frontend/main)** — renomeia `middleware.ts`→`proxy.ts`, elimina aviso de deprecação. Runtime nodejs compatível com sessão JWT.

### Pendências conhecidas
- **Segurança (ação manual do usuário):** rotacionar `BOT_API_KEY` — valor antigo recuperável no histórico git. Opcional: limpar histórico se repo for público.
- **Lint frontend:** 10 erros `react-hooks/set-state-in-effect` — padrão pré-existente em todas as páginas, build passa. Refatoração de data-fetching adiada (risco em Next 16).
- **e2e Playwright:** 8 falhas pré-existentes por drift de seed (serviceId 1/3 arquivados; senha do barber taylor é `senha123`, helpers usam `teste@123`). Requer backend+DB+frontend rodando para validar correção.
- **Dívida de arquitetura (code review):** boilerplate RBAC (`UserUnit` + `resolve_role` + `require_*`) copiado ~20× em 7 routers; `servicos.py` já divergiu (`_resolve_role` próprio). Extrair dependency FastAPI.
- **Perf (code review):** N+1 em `reactivation.py`/`reminders.py` (3-4 queries por alvo) — juntar em SELECT único com joins/anti-join.

### Ciclo 4 — RBAC org-escopado (segurança + dedup)
- **Scan de segurança:** nenhuma rota desprotegida (todos os handlers chamam guard, via helpers `_require_manager` duplicados). `loyalty.py` usa bot-token (consistente).
- **Brecha latente fechada:** `user_units` não tem RLS (tabela-filha); as 21 queries inline `select(UserUnit).where(user_id==...)` liam vínculos de TODAS as orgs → role efetiva poderia ser elevada entre tenants. Centralizei em `app/deps.resolve_current_role` / `resolve_current_role_with_barber`, que juntam com `units` (RLS) para escopar à org atual — padrão que o schema documenta e que só `servicos.py` seguia.
- Removida a duplicação: 21 blocos inline + 2 helpers `_require_manager` + `_resolve_role` próprio do servicos → 1 implementação. Routers agora importam de rbac só os guards.
- **Testes:** 4 novos (resolução por prioridade, sem vínculo→barber, barber_id, e assert de que a query faz JOIN units). **103 passando.** compileall limpo, app.main carrega.

### Próximos passos
1. Otimizar N+1 dos crons (`reactivation.py`/`reminders.py`).
2. e2e Playwright: corrigir drift de seed nos specs (precisa ambiente rodando).
3. Avaliar próxima feature do roadmap (página pública de agendamento).
