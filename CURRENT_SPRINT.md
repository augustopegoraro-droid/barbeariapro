# CURRENT_SPRINT.md
> Estado do desenvolvimento em 2026-06-21. Atualizar a cada sessão.

---

## Branch ativo

`feat/fase2-google-calendar` (backend)  
PR: https://github.com/augustopegoraro-droid/barbeariapro/pull/1  
Base: `main`

---

## Fase 2 — Google Calendar (escopo fechado)

**Objetivo:** OAuth + worker de sync `appointments → Google Calendar`.  
**Restrição:** zero contato com n8n/Evolution/bot.

### ✅ Concluído nesta fase

| Entrega | Arquivos | Commit |
|---|---|---|
| Config Google OAuth + chave Fernet | `app/core/config.py` | `a973514` |
| Criptografia Fernet de tokens | `app/core/crypto.py` | `a973514` |
| Cliente HTTP Google Calendar (OAuth2 + CRUD eventos) | `app/services/google_calendar.py` | `a973514` |
| Router OAuth (`/authorize`, `/callback`, `/authorize-url`, `/status`) | `app/api/integracoes.py` | `447cbb0` + `10be0ca` |
| Worker de sync (`push_appointment`) com refresh automático | `app/services/calendar_sync.py` | `447cbb0` |
| Hooks BackgroundTask em agenda e barbeiro | `app/api/agenda.py`, `app/api/barbeiro.py` | `447cbb0` |
| Página `/admin/configuracoes` com botão "Conectar Google Calendar" | `barbearia-frontend/app/admin/configuracoes/page.tsx` | `205e43f` (frontend) |
| Agenda do barbeiro otimizada para mobile | `barbearia-frontend/app/barbeiro/agenda/page.tsx` | `205e43f` (frontend) |
| Testes (30 testes de Calendar + OAuth + worker) | `tests/test_calendar_crypto.py`, `test_google_calendar_client.py`, `test_integracoes_oauth.py`, `test_calendar_sync_worker.py` | vários |

### Fluxo OAuth completo (como testar)

```
1. Iniciar staging (ver PROJECT_CONTEXT.md § 4)
2. next dev na porta 3000
3. Login: taylor@barbeariapro.com / senha123
4. Navegar para /admin/configuracoes
5. Clicar "Conectar Google Calendar"
   → abre consentimento Google
   → callback → /admin/configuracoes?calendar=connected (banner verde)
6. Criar agendamento em /admin/agenda
   → BackgroundTask chama push_appointment → insert_event no Google
   → calendar_sync grava external_event_id + sync_status=synced
```

### O que a Fase 2 NÃO inclui (fora de escopo)

- Integração com n8n (disponibilidade via Calendar)
- Automação de status CRM via Calendar
- Qualquer contato com bot/Evolution
- Esses itens são Fase 3, bloqueada pela Regra de Ouro

---

## Estado da Fase 1 (produção)

**Deployada em 2026-06-16.** Estável. Não mexer sem janela.

Entregues e no ar:
- CRM/Kanban (`/admin/crm`, `app/api/crm.py`, models `Lead`/`LeadEvent`)
- Dashboard operacional (`/dashboard/operacional`)
- Fix timezone nos filtros de data
- Fix loyalty no `/barbeiro/atendimento/concluir`
- RBAC centralizado (`app/deps.resolve_current_role`)
- Migration `0007_crm_leads` aplicada em produção

Rollback disponível: imagens `barbeariapro-backend:pre-fase1` / `barbeariapro-frontend:pre-fase1`

---

## Próximos passos (Fase 2 → merge → próxima feature)

### Imediato (antes do merge do PR #1)
- [ ] Testar o fluxo OAuth completo no browser (ver "Como testar" acima)
- [ ] Adicionar no Google Cloud Console a URI de staging:
  `http://localhost:8001/integracoes/google/calendar/callback`
- [ ] Verificar `docker-compose.app.yml`: `NEXT_PUBLIC_ORG_ID` está como `"1"` mas
  produção usa org `3` — confirmar se foi intencional antes do próximo deploy

### Pós-merge (próximas features por ROI)

Ordem sugerida pelo `ROADMAP_IMPLEMENTACAO.md` (Fase 1 do roadmap comercial):

| # | Feature | Esforço | Observação |
|---|---|---|---|
| 1 | **Lembrete 24h antes via WhatsApp** | Baixo | Infraestrutura 100% pronta; só falta o cron n8n + endpoint `/internal/reminders` |
| 2 | **Cron de reativação** | Trivial | `POST /internal/loyalty/reactivation/run` já existe; zero código novo — 1 workflow n8n |
| 3 | **Deploy VPS + HTTPS** | Médio | Pré-requisito para vender; CORS já por env var |
| 4 | **Export CSV comissões/faturamento** | Baixo | Queries já existem no dashboard |

### Fase 3 (BLOQUEADA — não iniciar sem aprovação explícita)
Requer staging isolado de n8n/Evolution com chip de teste.
Envolve: régua de follow-up 20min/24h/48h, gestão de objeções no prompt n8n,
automação de status CRM via Calendar.
Trava de segurança: `app/services/whatsapp.py:17` (dry-run nativo).

---

## Containers em produção (estado em 2026-06-21)

```
barbeariapro-app-backend    Up 3 days (healthy)   :8000
barbeariapro-app-frontend   Up 45 hours (healthy) :3000
barbeariapro-postgres       Up 45 hours (healthy) :5432
barbeariapro-staging-postgres  Up 32 hours        :5433  ← staging
```

n8n e Evolution (infra) UP mas não listados acima — verificar com `docker ps`.
