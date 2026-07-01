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

## Limpeza (reset) da org 1 — OPCIONAL e destrutivo

Se a decisão for **substituir** a base atual (em vez de mesclar via dedup), o reset
é uma etapa **separada, gated e com backup obrigatório** (passo 1 acima). O escopo
precisa ser decidido explicitamente (o que apagar vs. preservar: config estrutural
— org/unidade/usuários/serviços/profissionais/horários — normalmente é preservada;
dados operacionais — clientes/agendamentos/pagamentos/assinaturas/fidelidade/
conversas — é o que se limpa). **Não** há script de reset no repo até essa decisão.

## Teste
`tests/test_trinks_import.py` valida o parser (mapeamento, telefone, dedup, data,
e-mail, canal, encoding latin-1) contra `tests/fixtures/trinks/clientes_sample.csv`
(dados anonimizados). Rodar: `.venv/bin/python -m pytest tests/test_trinks_import.py -q`.
