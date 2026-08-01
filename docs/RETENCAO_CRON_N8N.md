# Cron de retenção — purga de auditoria e sessões (D-70 / D-86)

O endpoint `POST /internal/audit/purge` existe desde o D-70 e **nunca foi
agendado**: a política de retenção estava declarada (`organizations.audit_retention_months`,
default 12) e não era cumprida. Desde o D-86 a mesma chamada purga também as
sessões expiradas de staff (`sessions`) e do site público (`client_sessions`),
que guardam IP e user-agent e não tinham prazo nenhum.

Um agendamento só, no mesmo molde de `GESTOR_CRON_N8N.md`. **Não** editar o
`workflows.json` local (diverge da VM) — criar direto no n8n da VM.

## Workflow

- **Nome:** `BarbeariaPro Cron - Retenção LGPD`
- **Schedule Trigger (cron):** `30 4 * * *` (todo dia às 4h30, fora do expediente
  — a purga faz DELETE em tabela grande).
- **HTTP Request:**
  - Method: `POST`
  - URL: `http://host.docker.internal:8000/internal/audit/purge`
  - Headers: `X-Bot-Token: {{ $env.BOT_API_KEY }}`, `Content-Type: application/json`

Resposta:

```json
{
  "deleted": 0,
  "sessions": { "staff_sessions": 0, "client_sessions": 0 }
}
```

- `deleted` — linhas de `audit_logs` além da retenção **de cada org**
  (`app_audit_purge_expired`, SECURITY DEFINER, cross-org numa chamada).
- `sessions` — linhas removidas por `app_sessions_purge_expired` (migration 0047).
  Critério: revogada/expirada há mais de 30 dias, ou parada há mais de 60 dias
  (staff) / 430 dias (cliente final — o cookie do site vive 400). Constantes em
  `app/services/retention.py`.

## Antes de ligar

A **primeira execução** apaga tudo o que já passou do prazo acumulado desde
2026-07 — pode ser um volume grande de uma vez. Confira o que vai sair antes:

```sql
SELECT o.id, o.name, o.audit_retention_months,
       count(*) FILTER (
         WHERE a.created_at < now() - (o.audit_retention_months || ' months')::interval
       ) AS a_purgar,
       count(*) AS total
  FROM organizations o
  LEFT JOIN audit_logs a ON a.organization_id = o.id
 GROUP BY o.id, o.name, o.audit_retention_months;
```

Se o número assustar, suba a retenção antes de ligar o cron
(`PUT /admin/security/retention`, ou a tela quando existir) — apagar é
irreversível e a tabela é append-only por desenho.
