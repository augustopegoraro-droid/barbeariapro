# Import de clientes da Trinks (onboarding de tenant)

Migração da base de clientes de um export da **Trinks** para um org (tenant) do
BarbeariaPro. Piloto: **Taylor & Thedy (org 1)**.

> ⚠️ **PII / LGPD:** os arquivos exportados (`TrinksInformations/…`) contêm CPF,
> telefone, e-mail e endereço de milhares de clientes. **Nunca** versione esses
> arquivos (já cobertos pelo `.gitignore`). Versione só o código do importador e
> fixtures anonimizadas (`tests/fixtures/trinks/`).

## O que é importado

O export de clientes da Trinks é um relatório **ISO-8859-1 (latin-1), CRLF**, com
um preâmbulo de filtros no topo e o cabeçalho real (`"CPF";"Origem";"Nome";…`,
`;`-delimitado) mais abaixo. O parser acha o cabeçalho, mapeia por **nome de
coluna** (robusto a ordem) e deduplica por telefone dentro do arquivo.

| Coluna Trinks | Campo `clients` | Observação |
|---|---|---|
| Nome | `name` | obrigatório; linha sem nome é ignorada |
| Telefone 1 (fallback Telefone 2) | `phone_e164` | normalizado (E.164, `normalize_phone`); obrigatório |
| E-mail | `email` | normalizado p/ minúsculas (migration `0022`) |
| Data de Nascimento | `birth_date` | `dd/mm/aaaa` (migration `0022`) |
| Observações (+ Instagram) | `notes` | concatenados (migration `0022`) |
| Origem / Como nos conheceu | `acquisition_channel` | mapeado p/ `ContactChannel` |
| CPF, Gênero, Endereço, agendamentos, status | — | **não importado** (sem uso hoje / LGPD: minimizar dado) |

**Não importáveis** (contabilizados no relatório, não descartados em silêncio):
sem nome, sem telefone, telefone inválido, duplicado no arquivo.

## Runbook (roda NA VM — o Postgres não é acessível de fora)

```bash
# 0) Deploy do código na VM
git pull                     # traz migration 0022 + scripts/import_trinks.py

# 1) BACKUP (obrigatório — torna qualquer limpeza reversível)
docker exec <container_postgres> pg_dump -U barber_owner barbeariapro \
  > ~/backup_pre_trinks.sql

# 2) Migration (estende clients: email, birth_date, notes)
#    usa a role dona (ADMIN_DATABASE_URL) — ver PROJECT_CONTEXT
alembic upgrade head          # -> head 0022_client_trinks_fields

# 3) Colocar o export na VM (NUNCA commitar; scp para fora do git)
#    ex.: scp "ClientesT&T.csv" vm:~/barbeariapro/TrinksInformations/

# 4) DRY-RUN (padrão): só relatório, não grava nada
python scripts/import_trinks.py --org-id 1 --file "TrinksInformations/ClientesT&T.csv"

# 5) Conferir o relatório (importáveis, duplicados, sem telefone, etc.)

# 6) IMPORT REAL (grava + commita). Deduplica por telefone contra o org.
python scripts/import_trinks.py --org-id 1 --file "TrinksInformations/ClientesT&T.csv" --commit

# 7) Validar no painel / API
```

### Dedup
O importador consulta os telefones já existentes no org e **pula** os repetidos —
então rodar de novo é idempotente e **não** exige limpar a base antes. Um cliente
com telefone já presente não é duplicado.

## Limpeza (reset) da org — `scripts/reset_org.py`

Para **substituir** a base fictícia pela real, o `reset_org.py` apaga os dados
**operacionais/de cliente** e **preserva a configuração estrutural**.

| Apaga (operacional/fictício) | Preserva (config/estrutura) |
|---|---|
| clients, client_consents | organizations, units, business_hours |
| appointments, appointment_items | users, user_units |
| payments, expenses | barbers, barber_units, barber_services, time_off |
| leads, lead_events | services |
| conversations, messages, attachments, message_log | plans, subscriptions *(assinatura do org c/ a plataforma)* |
| calendar_sync | **integration_accounts** *(WhatsApp/Google — conexão viva)* |
| client_memberships, membership_usages | membership_plans, membership_plan_items *(catálogo)* |
| client_loyalty, loyalty_point_ledger, loyalty_vouchers | loyalty_tiers, loyalty_rules *(config)* |
| | expense_categories *(config)* |

Segurança do script: roda como `barber_app` com `set_current_org` (**RLS auto-escopa
no org**) + `WHERE organization_id` explícito; **dry-run por padrão**; com `--commit`
exige `--confirm-name "<nome exato do org>"`; tudo em transação (erro → rollback).

```bash
# 1) BACKUP primeiro (obrigatório — ver acima)
# 2) dry-run: conta o que seria apagado, por tabela
python scripts/reset_org.py --org-id 1
# 3) aplicar (exige o nome exato do org)
python scripts/reset_org.py --org-id 1 --commit --confirm-name "Barbearia Taylor e Thedy"
```

Validado no staging (org 1): os 18 DELETEs executam em ordem FK-safe com privilégio
de `barber_app` (testado com rollback, sem tocar os dados). **Se quiser apagar
também os catálogos preservados** (planos de mensalidade / tiers de fidelidade /
categorias), me avise para incluí-los na lista.

> Alternativa ao reset: o importador **deduplica** por telefone, então dá para
> **mesclar** a base real sem limpar — útil se a base atual não for 100% fictícia.

## Agendamentos — `scripts/import_trinks_appointments.py`

Import de agendamentos (ex.: `AgendamentosFuturosJulho.csv`). Cada linha liga
**cliente** (por telefone; **cria** se novo, com nome/e-mail da linha), **profissional**
(por nome) e **serviço** (de-para Trinks→catálogo). Cria `Appointment` (status
`agendado`, `display_number` sequencial por unidade, fuso `app_timezone`→UTC) +
`AppointmentItem` (preço/duração da linha). Pula `Cancelado`, serviço sem de-para e
linha sem telefone (tudo contabilizado no relatório). Pré-requisito: profissionais e
serviços já existentes na org.

De-para de serviços em `app/services/trinks_appointments.py::_SERVICE_MAP` (ajuste lá
se surgirem nomes novos). Rodar (na VM, mesmo padrão de mount):

```bash
# dry-run → conferir → --commit
... backend python scripts/import_trinks_appointments.py --org-id 1 --file TrinksInformations/agendamentos.csv
... backend python scripts/import_trinks_appointments.py --org-id 1 --file TrinksInformations/agendamentos.csv --commit
```

Validado no staging: parser no arquivo real (48 parseáveis, de-para 100%) + caminho de
escrita (43 appointments + clientes, com rollback).

## Teste
`tests/test_trinks_import.py` valida o parser (mapeamento, telefone, dedup, data,
e-mail, canal, encoding latin-1) contra `tests/fixtures/trinks/clientes_sample.csv`
(dados anonimizados). Rodar: `.venv/bin/python -m pytest tests/test_trinks_import.py -q`.
