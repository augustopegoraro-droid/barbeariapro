# BarbeariaPro — Guia de Instalação Técnica

> **Público:** técnico/desenvolvedor que instala o sistema **uma única vez** no
> computador da barbearia e o deixa rodando sozinho.
> **Não é** o manual do dia a dia da recepção (esse é o `MANUAL-RECEPCAO.md`).

Este guia usa **somente** os nomes, portas, comandos e arquivos reais deste
projeto. Confira tudo antes de entregar.

---

## 0. Visão geral da arquitetura (o que você vai colocar de pé)

O sistema tem **dois grupos de containers Docker**, em **dois arquivos compose
separados**, com **project names diferentes** para não colidirem:

### Grupo 1 — Infra / Bot WhatsApp (`docker-compose.yml`)
| Serviço (compose) | Container | Porta no host | Função |
|---|---|---|---|
| `postgres` | `barbeariapro-postgres` | `5432` | Banco de dados da aplicação |
| `n8n` | `n8n` | `5678` | Orquestrador do robô de WhatsApp (workflows) |
| `evolution-postgres` | `evolution_postgres` | — (interna) | Banco da Evolution |
| `evolution-redis` | `evolution_redis` | — (interna) | Cache da Evolution |
| `evolution-api` | `evolution_api` | `8080` | Gateway que conecta no WhatsApp |

- Redes: `barbearia_network` (postgres/n8n) e `barbearia-whatsapp_default` (evolution).
- Volumes (dados persistentes): `barbeariapro_postgres_data`, `n8n_data`,
  `barbearia-whatsapp_postgres_data`, `barbearia-whatsapp_evolution_instances`.

### Grupo 2 — Aplicação (`docker-compose.app.yml`, project `barbeariapro-app`)
| Serviço | Container | Porta no host | Imagem |
|---|---|---|---|
| `backend` | `barbeariapro-app-backend` | `8000` | `barbeariapro-backend` (FastAPI/uvicorn, Python 3.12) |
| `frontend` | `barbeariapro-app-frontend` | `3000` | `barbeariapro-frontend` (Next 16, Node 20) |

- Rede própria: `barbeariapro-app_default`.
- O backend (container) **não** está na mesma rede do postgres. Ele alcança o
  banco pela porta publicada no host, via `host.docker.internal:5432`
  (configurado em `.env.docker` + `extra_hosts: host.docker.internal:host-gateway`).

### Como o bot WhatsApp conversa com tudo
```
WhatsApp do cliente
      │
      ▼
evolution_api (:8080)  ──webhook──►  n8n (:5678)
      ▲                                   │
      │ envia resposta                    │ chama a regra de negócio
      └───────────────────────────────────┤
                                          ▼
                       backend FastAPI (host.docker.internal:8000)
                                          │
                                          ▼
                            barbeariapro-postgres (:5432)
```
- `n8n` e `evolution_api` se enxergam pelo host (`host.docker.internal`),
  porque estão em redes diferentes — por isso ambos têm
  `extra_hosts: host.docker.internal:host-gateway` no compose da infra.
- O `n8n` chama o backend em `http://host.docker.internal:8000` (mesma porta que
  hoje é servida pelo container `barbeariapro-app-backend`).

### URLs reais depois de instalado
| O quê | URL |
|---|---|
| Painel da recepção (frontend) | http://localhost:3000 (redireciona para `/login`) |
| API (backend) | http://localhost:8000 — health em `/health`, docs em `/docs` |
| Evolution API / Manager | http://localhost:8080 e http://localhost:8080/manager |
| n8n (workflows do robô) | http://localhost:5678 |

---

## 1. Pré-requisitos do computador da barbearia

- **Sistema operacional:** Windows 10/11, macOS 12+ ou Linux com Docker.
  (O ambiente de referência deste projeto é **macOS** — `host.docker.internal`
  funciona nativamente no Docker Desktop de macOS/Windows. Em **Linux** ele é
  habilitado pelo `extra_hosts: host.docker.internal:host-gateway`, já presente
  nos dois composes.)
- **Docker:** Docker Desktop (macOS/Windows) ou Docker Engine + Compose v2 (Linux).
- **RAM:** mínimo **8 GB** (recomendado 16 GB — são ~7 containers + Node/Python).
- **Disco:** ~10 GB livres para imagens + volumes do banco.
- **Internet:** estável (a Evolution mantém a sessão do WhatsApp aberta e o robô
  usa a API da OpenAI).
- **Python 3.12** instalado no host — necessário **só na instalação** para rodar
  as migrations e o seed (o container do backend **não** inclui `alembic/` nem
  `scripts/`, por isso esse passo roda no host).

---

## 2. Instalar o Docker

1. Baixe no site oficial: **https://www.docker.com/products/docker-desktop/**
   (macOS/Windows) ou siga **https://docs.docker.com/engine/install/** (Linux).
2. Instale e abra o **Docker Desktop**. Aguarde o ícone da baleia ficar verde
   ("Docker Desktop is running").
3. Confirme no terminal:
   ```bash
   docker --version
   docker compose version
   ```
   Ambos devem responder com um número de versão. Compose precisa ser **v2**
   (o comando é `docker compose`, com espaço — não `docker-compose`).

---

## 3. Copiar o projeto para o computador da barbearia

Opção A — clonar (se houver repositório Git):
```bash
git clone <URL-DO-REPOSITORIO> barbeariapro
cd barbeariapro
```

Opção B — copiar a pasta inteira (pendrive/rede). Garanta que vieram juntos:
- `docker-compose.yml` (infra)
- `docker-compose.app.yml` (app)
- `Dockerfile` (backend) e `barbearia-frontend/Dockerfile` (frontend)
- `.dockerignore`, `barbearia-frontend/.dockerignore`
- `requirements.txt`, `alembic/`, `alembic.ini`, `scripts/`, `app/`, `models/`
- `barbearia-frontend/` (código do painel)
- `.env.example`

> **Atenção:** os arquivos `.env` e `.env.docker` **não** vão para o Git
> (contêm segredos). Você vai criá-los no passo 4.

---

## 4. Configurar as variáveis de ambiente

São **dois** arquivos na raiz do projeto.

### 4.1 `.env` — configuração base da aplicação e da infra
Crie a partir do exemplo e edite:
```bash
cp .env.example .env
```

| Variável | Para que serve | Observação |
|---|---|---|
| `SECRET_KEY` | Chave que assina o token de login (JWT) | **Troque** por string longa e aleatória |
| `JWT_ALGORITHM` | Algoritmo do JWT | Deixe `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Validade do login em minutos | Ex.: `480` (8h) |
| `DATABASE_URL` | Conexão **da aplicação** (role `barber_app`, com RLS) | No host fica `@localhost:5432`; no container é sobrescrito (ver 4.2) |
| `ADMIN_DATABASE_URL` | Conexão **dona** do banco — usada **só pelo seed** | Role `barber_owner` |
| `APP_DB_ROLE` | Nome da role do app | `barber_app` |
| `SEED_PASSWORD` | Senha inicial dos usuários criados pelo seed | Ex.: `senha123` (troque depois) |
| `BOT_API_KEY` | Chave que o **n8n** usa para chamar o backend | String longa e secreta |
| `BOT_ORGANIZATION_ID` | ID da organização usada pelo robô | Ex.: `3` |
| `BOT_UNIT_ID` | ID da unidade usada pelo robô | Ex.: `3` |
| `ENABLE_DEBUG_ENDPOINTS` | Liga endpoints de debug do bot | Mantenha `false` em produção |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credenciais do container `barbeariapro-postgres` | Default: `postgres` / `postgres` / `barbeariapro` |
| `EVOLUTION_API_KEY` | Chave de autenticação da Evolution API | Usada pelo n8n e pelo backend para enviar mensagens |
| `EVOLUTION_POSTGRES_PASSWORD` | Senha do banco interno da Evolution | Ex.: `evolution123` |
| `EVOLUTION_SERVER_URL` | URL pública da Evolution | `http://localhost:8080` |
| `EVOLUTION_API_URL` | URL que o **backend** usa para falar com a Evolution | No host `http://localhost:8080`; no container é sobrescrito (4.2) |
| `EVOLUTION_INSTANCE_NAME` | Nome da instância do WhatsApp na Evolution | Ex.: `barbearia` |
| `OPENAI_API_KEY` | Chave da OpenAI usada pelo robô (IA) | Secreta |

### 4.2 `.env.docker` — overrides para rodar **dentro dos containers**
Os containers não enxergam `localhost` da máquina; eles alcançam a infra por
`host.docker.internal`. Este arquivo sobrescreve as variáveis afetadas. **Não vai
para o Git** (já coberto por `.gitignore` em `.env.*`).

Gere automaticamente a partir do `.env` (rewrite de `localhost` → `host.docker.internal`):
```bash
DB=$(grep -E '^DATABASE_URL=' .env | cut -d= -f2- | sed 's/@localhost:/@host.docker.internal:/')
cat > .env.docker <<EOF
# Overrides p/ execução em container (NÃO comitar)
DATABASE_URL=${DB}
EVOLUTION_API_URL=http://host.docker.internal:8080
API_URL_INTERNAL=http://host.docker.internal:8000
AUTH_SECRET=$(openssl rand -base64 48 | tr -d '\n')
AUTH_TRUST_HOST=true
EOF
```

| Variável (`.env.docker`) | Para que serve |
|---|---|
| `DATABASE_URL` | Mesma do app, mas apontando para `host.docker.internal:5432` (backend → postgres) |
| `EVOLUTION_API_URL` | Backend → Evolution via `host.docker.internal:8080` |
| `API_URL_INTERNAL` | **Frontend (SSR/next-auth)** → backend via `host.docker.internal:8000` |
| `AUTH_SECRET` | Segredo do next-auth (assina a sessão do painel) |
| `AUTH_TRUST_HOST` | `true` — necessário para o next-auth atrás de `localhost` em container |

> O **navegador** usa `NEXT_PUBLIC_API_URL=http://localhost:8000` (embutido no
> build do frontend, via `--build-arg` no `docker-compose.app.yml`). O
> **servidor** do Next (login) usa `API_URL_INTERNAL`. Os dois contextos são
> tratados em `barbearia-frontend/lib/api.ts`.

---

## 5. Subir a infra (banco + robô WhatsApp) e preparar o banco

A infra usa o `docker-compose.yml` (sem `-f`, é o arquivo padrão).

### 5.1 Subir só o banco e aplicar as migrations
```bash
# 1) sobe apenas o postgres
docker compose up -d postgres

# 2) prepara o ambiente Python (host) — uma vez
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3) cria o schema do banco
.venv/bin/alembic upgrade head

# 4) popula dados iniciais (organização, unidade, serviços, profissionais/logins)
.venv/bin/python scripts/seed.py
```
O seed imprime os logins criados (e a senha = `SEED_PASSWORD`). Exemplos reais
deste projeto: `taylor@barbeariapro.com`, `thedy@barbeariapro.com` (role `owner`).

### 5.2 Subir o restante da infra (n8n + evolution)
```bash
docker compose up -d
```

### 5.3 Importar o workflow do robô no n8n (se ainda não importado)
```bash
docker compose cp workflows.json n8n:/tmp/
docker compose exec n8n n8n import:workflow --input=/tmp/workflows.json
docker compose restart n8n
```
(Confira os IDs/ativação no painel do n8n em http://localhost:5678.)

---

## 6. Subir a aplicação (backend + frontend)

Use **sempre** o `-f docker-compose.app.yml` para o app:
```bash
docker compose -f docker-compose.app.yml up -d --build
```
O `--build` constrói as imagens `barbeariapro-backend` e `barbeariapro-frontend`.
O `frontend` só sobe depois que o `backend` ficar **healthy** (`depends_on:
condition: service_healthy`).

Comandos úteis do app:
```bash
docker compose -f docker-compose.app.yml ps        # status dos containers do app
docker compose -f docker-compose.app.yml logs -f   # logs ao vivo
docker compose -f docker-compose.app.yml down       # parar SÓ o app (não toca na infra)
```

---

## 7. Conectar o número de WhatsApp da barbearia (Evolution API)

A instância é a definida em `EVOLUTION_INSTANCE_NAME` (ex.: `barbearia`).
Use o **número exclusivo** da barbearia (de preferência um chip só para isso).

### Caminho A — Manager visual (mais simples)
1. Abra **http://localhost:8080/manager** no navegador.
2. Faça login com a **`EVOLUTION_API_KEY`** (a mesma do `.env`).
3. Crie/abra a instância `barbearia`.
4. Clique em **Connect / QR Code**. Um QR code aparece na tela.
5. No celular da barbearia: **WhatsApp → Configurações → Aparelhos conectados →
   Conectar um aparelho** e aponte a câmera para o QR.
6. Quando o status virar **`open`/conectado**, o WhatsApp está pareado.

### Caminho B — via API (alternativa por terminal)
```bash
# criar a instância (se não existir)
curl -X POST http://localhost:8080/instance/create \
  -H "apikey: <EVOLUTION_API_KEY>" -H "Content-Type: application/json" \
  -d '{"instanceName":"barbearia","integration":"WHATSAPP-BAILEYS","qrcode":true}'

# obter o QR para parear
curl http://localhost:8080/instance/connect/barbearia -H "apikey: <EVOLUTION_API_KEY>"

# conferir o estado da conexão
curl http://localhost:8080/instance/connectionState/barbearia -H "apikey: <EVOLUTION_API_KEY>"
```
O `connectionState` deve retornar `open` quando conectado.

> O QR **expira** em segundos. Se sumir, gere de novo. Mantenha o celular com
> internet — se o WhatsApp deslogar o aparelho, é preciso reparear.

---

## 8. Validar que tudo subiu

### 8.1 Containers de pé
```bash
docker ps
```
Esperado (7 containers): `barbeariapro-app-backend`, `barbeariapro-app-frontend`,
`barbeariapro-postgres`, `n8n`, `evolution_api`, `evolution_postgres`,
`evolution_redis` — todos `Up` (os do app com `(healthy)`).

### 8.2 Health checks reais
```bash
curl http://localhost:8000/health
# → {"status":"ok"}

curl http://localhost:8000/health/db
# → {"status":"ok","database":"reachable"}   (backend no container falando com o postgres da infra)

curl -i http://localhost:3000
# → HTTP/1.1 307 Temporary Redirect   /   location: /login

curl http://localhost:8080/instance/connectionState/barbearia -H "apikey: <EVOLUTION_API_KEY>"
# → estado "open" quando o WhatsApp está conectado
```

### 8.3 Caminho do bot até a API
```bash
docker exec n8n sh -c "wget -q -O - http://host.docker.internal:8000/health"
# → {"status":"ok"}   (o n8n alcança o backend)
```

---

## 9. Iniciar sozinho quando o PC liga

1. **Docker Desktop → Settings → General → "Start Docker Desktop when you log in"**
   (em Linux: `sudo systemctl enable docker`). Isso garante que o Docker sobe no boot.
2. As **restart policies** já estão nos composes:
   - Infra: `postgres` e `n8n` = `restart: unless-stopped`; evolution = `restart: always`.
   - App: `backend` e `frontend` = `restart: unless-stopped`.
   Ou seja, depois que o Docker inicia, os containers voltam **sozinhos** (a menos
   que tenham sido parados manualmente com `down`/`stop`).
3. Configure também o **login automático do usuário do sistema operacional** (para
   não travar no boot esperando senha), se a barbearia desligar o PC à noite.

> Se algum dia você der `docker compose ... down`, os containers **não** voltam
> sozinhos no próximo boot até você subir de novo. Para o dia a dia, prefira
> deixar ligado.

---

## 10. Criar o login da recepcionista

O sistema **não tem tela de cadastro de usuário**; os logins nascem do
`scripts/seed.py`. Você tem duas opções:

### Opção A — usar um login existente (mais rápido)
Entregue à recepção um dos logins criados pelo seed (ex.: `taylor@barbeariapro.com`,
senha = `SEED_PASSWORD`). **Troque a senha** logo na primeira entrada (ver 10.2).

### Opção B — criar um usuário dedicado de recepção (`role = reception`)
1. Descubra `organization_id` e `unit_id` reais:
   ```bash
   docker exec -it barbeariapro-postgres psql -U postgres -d barbeariapro \
     -c "SELECT id FROM organizations; SELECT id, name FROM units;"
   ```
2. Gere o hash da senha com o venv do host:
   ```bash
   .venv/bin/python -c "from app.core.security import hash_password; print(hash_password('SENHA_DA_RECEPCAO'))"
   ```
3. Insira o usuário e o vínculo com a unidade (role `reception`):
   ```bash
   docker exec -it barbeariapro-postgres psql -U postgres -d barbeariapro <<'SQL'
   -- ajuste organization_id, unit_id e o hash gerado acima
   INSERT INTO users (organization_id, email, password_hash)
   VALUES (3, 'recepcao@barbeariapro.com', '<HASH_GERADO>')
   RETURNING id;
   -- use o id retornado abaixo como user_id; role=reception; barber_id fica NULL
   INSERT INTO user_units (user_id, unit_id, role, barber_id)
   VALUES (<USER_ID>, 3, 'reception', NULL);
   SQL
   ```
4. Teste o login:
   ```bash
   curl -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' \
     -d '{"organization_id":3,"email":"recepcao@barbeariapro.com","password":"SENHA_DA_RECEPCAO"}'
   # → deve retornar access_token e "role":"reception"
   ```

### 10.2 Trocar senha
> **Observação honesta:** este projeto ainda **não expõe** um endpoint/tela de
> "trocar senha" próprio. Para alterar uma senha hoje, gere um novo hash (passo
> 10.2 → passo 2 acima) e faça `UPDATE users SET password_hash='<NOVO_HASH>'
> WHERE email='...';`. Avalie implementar uma tela de troca de senha antes de
> escalar o uso.

---

## 11. Checklist de entrega (antes de deixar a barbearia operando)

- [ ] `docker ps` mostra os **7 containers** `Up` (app com `(healthy)`).
- [ ] `curl http://localhost:8000/health` → `{"status":"ok"}`.
- [ ] `curl http://localhost:8000/health/db` → `"database":"reachable"`.
- [ ] `curl -i http://localhost:3000` → `307` para `/login`.
- [ ] http://localhost:3000 abre a tela de login no navegador.
- [ ] WhatsApp da barbearia **conectado** (`connectionState` = `open`).
- [ ] Teste real: enviar uma mensagem ao número da barbearia e ver o robô responder.
- [ ] Login da recepção funciona (Opção A ou B do passo 10).
- [ ] Senhas padrão (`SEED_PASSWORD`) **trocadas**; `SECRET_KEY`, `BOT_API_KEY`,
      `EVOLUTION_API_KEY`, `OPENAI_API_KEY` **preenchidas com valores reais**.
- [ ] Docker Desktop configurado para **iniciar no login** (passo 9).
- [ ] **Backup** testado (ver abaixo) e agendado.
- [ ] Atalho no navegador (favorito) para **http://localhost:3000**.
- [ ] `MANUAL-RECEPCAO.md` entregue/impresso e os dados de suporte preenchidos.

### Backup do banco (anote/agende)
Container do banco da aplicação: **`barbeariapro-postgres`**, banco `barbeariapro`.
```bash
# gerar backup
docker exec barbeariapro-postgres pg_dump -U postgres barbeariapro > backup-$(date +%Y%m%d).sql

# restaurar (em caso de necessidade)
cat backup-AAAAMMDD.sql | docker exec -i barbeariapro-postgres psql -U postgres -d barbeariapro
```
> Se o `pg_dump` pedir senha, use `POSTGRES_PASSWORD` do `.env`. Guarde os backups
> **fora** do PC da barbearia (nuvem/HD externo).

---

## Apêndice — Comandos de referência rápida

```bash
# INFRA (banco + robô)
docker compose up -d                 # subir tudo
docker compose ps                    # status
docker compose logs -f n8n           # logs de um serviço
docker compose down                  # parar infra (⚠ derruba o robô)

# APP (backend + frontend)
docker compose -f docker-compose.app.yml up -d --build   # subir/atualizar
docker compose -f docker-compose.app.yml ps              # status
docker compose -f docker-compose.app.yml logs -f         # logs
docker compose -f docker-compose.app.yml down            # parar só o app

# GERAL
docker ps                            # todos os containers
```
