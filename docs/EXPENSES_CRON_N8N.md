# Cron de despesas recorrentes (D-102)

Um workflow de cron no n8n materializa, **1× por mês**, as **despesas fixas**
cadastradas em `/admin/financeiro` → aba **A pagar** → painel "Despesas fixas"
(`expense_recurrences`). Cada template ativo vira uma conta `a_pagar` do mês
corrente (`competence_month` = 1º dia do mês; `due_date` = dia `day_of_month`).

Mesmo molde do "BarbeariaPro Cron - Lembrete 24h" / D-96 / D-98. **Não** editar
`workflows.json` local (diverge da VM); criar o workflow direto no n8n da VM.

## Workflow

- **Schedule Trigger (cron):** `0 6 1 * *` (dia 1 de cada mês, ~6h).
- **HTTP Request:**
  - Method: `POST`
  - URL: `http://host.docker.internal:8000/internal/expenses/run`
  - Headers: `X-Bot-Token: {{ $env.BOT_API_KEY }}`, `Content-Type: application/json`
- Resposta: `{ created, skipped }`.

## Idempotência

Rodar o endpoint mais de uma vez no mesmo mês é seguro: o índice único parcial
`expenses_recurrence_month_unique` (`organization_id, recurrence_id,
competence_month WHERE recurrence_id IS NOT NULL`) garante **1 conta por template
por mês**. Chamadas repetidas retornam `created: 0` e incrementam `skipped`.

## Teste manual

```bash
curl -X POST http://SEU_HOST:8000/internal/expenses/run \
  -H "X-Bot-Token: SEU_BOT_API_KEY"
# → {"created": N, "skipped": M}
```

Sem `X-Bot-Token` (ou errado) → **401**.
