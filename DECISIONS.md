# DECISIONS.md
> Decisões técnicas e de produto tomadas ao longo do projeto.
> Cada entrada tem: contexto, decisão, motivo e consequências.
> Nunca remover entradas — marcar como supersedida se mudar.

---

## Segurança e isolamento

### D-01 — Regra de Ouro: staging nunca toca produção
**Data:** 2026-06-16  
**Decisão:** Staging usa banco separado (:5433), `EVOLUTION_API_URL` vazio e
`BOT_API_KEY` diferente. Nunca copiar `.env` de produção para staging.  
**Motivo:** Em sessão anterior, `.env.staging` apontava para Evolution de prod —
risco real de disparo em massa de WhatsApp para clientes reais.  
**Implementação:** Trava em `app/services/whatsapp.py:17` (dry-run nativo quando
`EVOLUTION_API_URL` vazio). Regra documentada em `MANUAL-OPERACIONAL.md` Seção 2.

### D-02 — State JWT no fluxo OAuth (sem sessão server-side)
**Data:** 2026-06-21  
**Decisão:** O parâmetro `state` do OAuth é um JWT assinado com `SECRET_KEY`, TTL
5 minutos, contendo `org_id`. Verificado no callback sem precisar de armazenamento
em Redis ou banco.  
**Motivo:** Evita dependência de armazenamento de sessão no servidor para um fluxo
que dura segundos. CSRF-safe porque o state é assinado.  
**Arquivo:** `app/api/integracoes.py:52-70` (`_build_state`, `_verify_state`).

### D-03 — Tokens OAuth cifrados em repouso (Fernet/AES-128)
**Data:** 2026-06-21  
**Decisão:** `access_token` e `refresh_token` do Google são cifrados com Fernet
antes de persistir em `integration_accounts.token_encrypted` (LargeBinary).  
**Motivo:** Tokens OAuth dão acesso à agenda Google do usuário — não podem ser
armazenados em plaintext mesmo num banco com RLS.  
**Implementação:** `app/core/crypto.py`. Chave via `TOKEN_ENCRYPTION_KEY` (env var,
nunca no código). Falha explícita se chave ausente.

---

## Arquitetura e escopo

### D-04 — Fase 2 sem contato com n8n/bot
**Data:** 2026-06-16  
**Decisão:** A integração Google Calendar não toca o workflow n8n, a Evolution API
nem o bot WhatsApp. O sync é direto: `appointments → Google Calendar` via
BackgroundTask FastAPI.  
**Motivo:** O bot em produção é o core do produto. Qualquer mudança no n8n/Evolution
requer chip de teste isolado + janela de manutenção.  
**Consequência:** Fase 3 (disponibilidade via Calendar, status CRM automático) fica
bloqueada até staging n8n/Evolution ser montado.

### D-05 — Sync Calendar como BackgroundTask (não fila/worker)
**Data:** 2026-06-21  
**Decisão:** `push_appointment()` é chamado como `fastapi.BackgroundTasks` nos
endpoints de criação, reagendamento, conclusão, cancelamento e faltou.  
**Motivo:** MVP com instância única — adicionar Redis/Celery seria
over-engineering. BackgroundTask não bloqueia o response do barbeiro.  
**Trade-off:** Se o processo do FastAPI reiniciar durante o background task, a
sincronização é perdida (sem retry automático). Aceitável no MVP; para HA futura,
migrar para fila.  
**Arquivo:** `app/services/calendar_sync.py`. Hooks em `app/api/agenda.py` e
`app/api/barbeiro.py`.

### D-06 — Sem migration nova para a Fase 2
**Data:** 2026-06-21  
**Decisão:** Tabelas `integration_accounts` e `calendar_sync` já existiam desde
`0001_initial`. A Fase 2 apenas as utiliza — sem ALTER TABLE, sem nova migration.  
**Motivo:** Reduz risco de deploy; a migration `0007_crm_leads` já está em
produção e é o head atual.

### D-07 — Callback OAuth redireciona para o frontend
**Data:** 2026-06-21  
**Decisão:** O callback `/integracoes/google/calendar/callback` redireciona para
`GOOGLE_FRONTEND_SUCCESS_URL?calendar=connected` quando essa variável estiver
configurada; caso contrário retorna JSON (útil para testes de API).  
**Motivo:** O usuário não deve ver um JSON cru após autorizar o Calendar; deve
voltar para o painel com feedback visual.  
**Implementação:** `config.py:53` (`google_frontend_success_url`). Frontend
exibe banner verde quando detecta `?calendar=connected` na URL.

---

## Frontend

### D-08 — Frontend é repositório git separado
**Data:** descoberto em 2026-06-21  
**Decisão:** `barbearia-frontend/` tem seu próprio `.git`. Commits de frontend
e backend são feitos em repos separados.  
**Consequência prática:** Sempre fazer `git -C barbearia-frontend/ add/commit`
para mudanças de frontend. O `.gitignore` do backend ignora o diretório inteiro.

### D-09 — Agenda do barbeiro mobile-first
**Data:** 2026-06-21  
**Decisão:** `/barbeiro/agenda` foi refatorada para uso primário em celular:
header sticky, modal de conclusão como bottom-sheet, ações com touch targets
≥44px, skeleton de loading, auto-reload via `visibilitychange`.  
**Motivo:** O barbeiro usa a página no próprio celular durante o dia de trabalho,
não num desktop.  
**Arquivo:** `barbearia-frontend/app/barbeiro/agenda/page.tsx` (commit `205e43f`).

### D-10 — Botão "Conectar Calendar" usa endpoint `/authorize-url` (não redirect direto)
**Data:** 2026-06-21  
**Decisão:** O frontend chama `GET /integracoes/google/calendar/authorize-url`
(que retorna `{"url": "..."}`) e depois faz `window.location.href = url`.
Não chama `/authorize` diretamente.  
**Motivo:** Axios/fetch seguem redirects automaticamente, mas o redirect vai para
`accounts.google.com` que bloqueia pela política CORS. A abordagem JSON resolve
isso: o frontend recebe a URL e o browser navega nativamente.  
**Arquivo:** `app/api/integracoes.py:188-210` (`authorize_url_json`).

---

## Produto e priorização

### D-11 — Lembrete 24h é a próxima feature de maior ROI
**Data:** 2026-06-21 (análise do ROADMAP_IMPLEMENTACAO.md)  
**Decisão:** Após o merge da Fase 2, a próxima feature prioritária é o lembrete
24h antes via WhatsApp.  
**Motivo:** A infraestrutura já está 100% pronta (`message_log`, Evolution API,
n8n, `app/api/reminders.py`, telefones E.164, consentimentos LGPD). É o argumento
de venda nº 1 (redução de no-show). Só precisa de 1 workflow cron no n8n.  
**Requisito prévio:** Fase 3 exige staging de n8n/Evolution com chip de teste.
O lembrete também toca o Evolution — portanto é Fase 3.

### D-12 — Google Calendar sync é ROI baixo (mas foi pedido)
**Data:** 2026-06-21  
**Decisão:** O sync Calendar foi implementado mesmo com ROI baixo no ranking do
ROADMAP (posição 28 de 30).  
**Motivo:** Pedido direto do usuário como feature da Fase 2. Não atrapalha o
roadmap comercial — foi feito de forma isolada sem tocar o bot.

---

## Dívida técnica conhecida (não resolver sem discussão)

| Item | Arquivo | Severidade | Observação |
|---|---|---|---|
| Estado do bot em memória (debounce, dedup, sessões) | `app/api/bot.py:49-61` | Médio | Restart perde estado; impossibilita 2ª instância. Aguarda Redis. |
| N+1 nos crons de reativação e lembrete | `app/services/reactivation.py`, `reminders.py` | Baixo | 3-4 queries por alvo; aceitável no volume atual. |
| 2 testes hardcoded na org 3 | `tests/test_clientes_integration.py`, `test_e2e_flow.py` | Baixo | Fail ambiental no staging; não são bugs. |
| `NEXT_PUBLIC_ORG_ID` no docker-compose.app.yml mudou de 3 para 1 | `docker-compose.app.yml` | ⚠️ Verificar | Produção é org 3; se baked na imagem de prod, precisa reverter antes do próximo deploy. |
