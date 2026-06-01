-- ============================================================================
-- BarbeariaPro — Schema PostgreSQL (MVP SaaS multi-tenant)
-- Target: PostgreSQL 16+
-- ----------------------------------------------------------------------------
-- Decisão de chaves:
--   • PK INTERNA  = BIGINT (GENERATED ALWAYS AS IDENTITY)
--       - índices e FKs menores (8 bytes), joins mais baratos ao longo de
--         anos de volume em appointments / appointment_items / message_log;
--       - sequencial = boa localidade de índice no caminho de escrita quente.
--   • IDENTIFICADOR EXTERNO = public_id UUID, apenas nas entidades expostas
--     em API/integração (organizations, clients, appointments).
--       - public_id NÃO é PK nem líder de índice, portanto a ordenação
--         temporal do UUIDv7 não traz benefício aqui;
--       - UUIDv7 nativo só chega no PG18 (uuidv7()). Em PG16 usamos
--         gen_random_uuid() (UUIDv4, embutido no core desde o PG13,
--         sem extensão), que é a escolha executável e suficiente para
--         um identificador externo estável e não adivinhável.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ENUM TYPES
-- (labels em ASCII para evitar acentos em identificadores de tipo)
-- ----------------------------------------------------------------------------
CREATE TYPE subscription_status AS ENUM ('trial', 'active', 'past_due', 'canceled');
CREATE TYPE unit_role           AS ENUM ('owner', 'manager', 'reception', 'barber');
CREATE TYPE service_category     AS ENUM ('cabelo', 'barba', 'combo', 'quimica', 'estetica');
CREATE TYPE contact_channel      AS ENUM ('whatsapp', 'instagram', 'google', 'indicacao', 'passante');
CREATE TYPE appointment_status   AS ENUM ('agendado', 'concluido', 'cancelado', 'faltou');
CREATE TYPE payment_method       AS ENUM ('dinheiro', 'cartao', 'pix');
CREATE TYPE consent_status       AS ENUM ('opt_in', 'opt_out');
CREATE TYPE integration_provider AS ENUM ('google_calendar', 'whatsapp');
CREATE TYPE integration_status   AS ENUM ('active', 'revoked', 'error');
CREATE TYPE sync_status          AS ENUM ('pending', 'synced', 'failed');
CREATE TYPE message_direction    AS ENUM ('outbound', 'inbound');
CREATE TYPE delivery_status      AS ENUM ('pending', 'sent', 'delivered', 'failed');

-- ============================================================================
-- SaaS / TENANT
-- ============================================================================

CREATE TABLE plans (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    price_month  NUMERIC(10,2) NOT NULL DEFAULT 0,
    max_units    INTEGER NOT NULL,
    max_barbers  INTEGER NOT NULL,
    features     JSONB   NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT plans_price_nonneg   CHECK (price_month >= 0),
    CONSTRAINT plans_units_positive CHECK (max_units   > 0),
    CONSTRAINT plans_barbers_pos    CHECK (max_barbers > 0)
);

CREATE TABLE organizations (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id   UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);

CREATE TABLE subscriptions (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id      BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    plan_id              BIGINT NOT NULL REFERENCES plans(id)         ON DELETE RESTRICT,
    status               subscription_status NOT NULL DEFAULT 'trial',
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end   TIMESTAMPTZ NOT NULL,
    canceled_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT subs_period_valid CHECK (current_period_end > current_period_start)
);
CREATE INDEX idx_subscriptions_org    ON subscriptions(organization_id);
CREATE INDEX idx_subscriptions_status ON subscriptions(status);

-- ============================================================================
-- ESTRUTURA
-- ============================================================================

CREATE TABLE units (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name            TEXT   NOT NULL,
    timezone        TEXT   NOT NULL DEFAULT 'America/Sao_Paulo',
    address         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_units_org ON units(organization_id);

CREATE TABLE users (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    email           TEXT   NOT NULL,
    password_hash   TEXT   NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT users_email_per_org UNIQUE (organization_id, email)
);
-- (sem idx_users_org: o UNIQUE (organization_id, email) já indexa o prefixo organization_id)

CREATE TABLE barbers (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name            TEXT   NOT NULL,
    specialty       TEXT,
    commission_pct  NUMERIC(5,4) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT barbers_commission_range CHECK (commission_pct >= 0 AND commission_pct <= 1)
);
CREATE INDEX idx_barbers_org ON barbers(organization_id);

-- Vínculo usuário↔unidade + PAPEL por unidade (mesma pessoa pode ter papéis
-- diferentes em filiais diferentes). barber_id liga o login ao profissional.
CREATE TABLE user_units (
    user_id   BIGINT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    unit_id   BIGINT NOT NULL REFERENCES units(id)   ON DELETE CASCADE,
    role      unit_role NOT NULL,
    barber_id BIGINT REFERENCES barbers(id)          ON DELETE SET NULL,
    PRIMARY KEY (user_id, unit_id)
);
CREATE INDEX idx_user_units_unit   ON user_units(unit_id);
CREATE INDEX idx_user_units_barber ON user_units(barber_id);

-- Barbeiro atua em N unidades.
CREATE TABLE barber_units (
    barber_id BIGINT NOT NULL REFERENCES barbers(id) ON DELETE CASCADE,
    unit_id   BIGINT NOT NULL REFERENCES units(id)   ON DELETE CASCADE,
    PRIMARY KEY (barber_id, unit_id)
);
CREATE INDEX idx_barber_units_unit ON barber_units(unit_id);

CREATE TABLE services (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id      BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name                 TEXT   NOT NULL,
    category             service_category NOT NULL,
    default_duration_min INTEGER NOT NULL,
    price                NUMERIC(10,2) NOT NULL,
    cost                 NUMERIC(10,2) NOT NULL DEFAULT 0,
    is_active            BOOLEAN NOT NULL DEFAULT true,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at           TIMESTAMPTZ,
    CONSTRAINT services_duration_pos CHECK (default_duration_min > 0),
    CONSTRAINT services_price_nonneg CHECK (price >= 0),
    CONSTRAINT services_cost_nonneg  CHECK (cost  >= 0)
);
CREATE INDEX idx_services_org ON services(organization_id);

-- ============================================================================
-- CLIENTES  (escopo de ORGANIZAÇÃO — não de unidade)
-- ============================================================================

CREATE TABLE clients (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    organization_id     BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name                TEXT NOT NULL,
    phone_e164          TEXT NOT NULL,
    acquisition_channel contact_channel,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT clients_phone_per_org UNIQUE (organization_id, phone_e164),
    CONSTRAINT clients_phone_e164_fmt CHECK (phone_e164 ~ '^\+[1-9][0-9]{7,14}$')
);
-- (sem idx_clients_org: o UNIQUE (organization_id, phone_e164) já indexa o prefixo organization_id)

-- LGPD: opt-in auditável é pré-requisito para envio de WhatsApp.
CREATE TABLE client_consents (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id  BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    channel    contact_channel NOT NULL,
    status     consent_status  NOT NULL,
    source     TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT client_consents_unique UNIQUE (client_id, channel)
);
CREATE INDEX idx_client_consents_client ON client_consents(client_id);

-- ============================================================================
-- AGENDA (FATO)
-- ============================================================================

CREATE TABLE appointments (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id          UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    organization_id    BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    unit_id            BIGINT NOT NULL REFERENCES units(id)         ON DELETE RESTRICT,
    client_id          BIGINT NOT NULL REFERENCES clients(id)       ON DELETE RESTRICT,
    display_number     INTEGER NOT NULL,             -- sequencial por unidade (atribuído pela aplicação)
    start_at           TIMESTAMPTZ NOT NULL,
    end_at             TIMESTAMPTZ NOT NULL,
    status             appointment_status NOT NULL DEFAULT 'agendado',
    booking_channel    contact_channel,
    rating             SMALLINT,
    total_amount       NUMERIC(10,2) NOT NULL DEFAULT 0, -- = Σ items.price_charged (esperado/faturado)
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT appt_time_valid     CHECK (end_at > start_at),
    CONSTRAINT appt_rating_range   CHECK (rating IS NULL OR (rating BETWEEN 1 AND 5)),
    CONSTRAINT appt_total_nonneg   CHECK (total_amount >= 0),
    CONSTRAINT appt_display_per_unit UNIQUE (unit_id, display_number)
);
CREATE INDEX idx_appt_org_start    ON appointments(organization_id, start_at);
CREATE INDEX idx_appt_unit_start   ON appointments(unit_id, start_at);
CREATE INDEX idx_appt_client_start ON appointments(client_id, start_at);
-- consulta real: "agendados/faltas por unidade num período" — status puro tem baixa seletividade
CREATE INDEX idx_appt_unit_status_start ON appointments(unit_id, status, start_at);

-- Linhas de serviço da visita; carregam o SNAPSHOT de preço e duração.
-- barber_id por item: a mesma visita pode ter serviços de barbeiros diferentes.
CREATE TABLE appointment_items (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appointment_id   BIGINT NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    service_id       BIGINT NOT NULL REFERENCES services(id)     ON DELETE RESTRICT,
    barber_id        BIGINT NOT NULL REFERENCES barbers(id)      ON DELETE RESTRICT,
    price_charged    NUMERIC(10,2) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    position         SMALLINT NOT NULL DEFAULT 1,
    CONSTRAINT appt_items_price_nonneg CHECK (price_charged   >= 0),
    CONSTRAINT appt_items_dur_pos      CHECK (duration_minutes > 0)
);
CREATE INDEX idx_appt_items_appt    ON appointment_items(appointment_id);
CREATE INDEX idx_appt_items_barber  ON appointment_items(barber_id);
CREATE INDEX idx_appt_items_service ON appointment_items(service_id);

-- ============================================================================
-- FINANCEIRO
-- ============================================================================

-- Pagamentos = REALIZADO (reconciliável contra appointments.total_amount).
CREATE TABLE payments (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    appointment_id  BIGINT NOT NULL REFERENCES appointments(id)  ON DELETE RESTRICT,
    amount          NUMERIC(10,2) NOT NULL,
    tip_amount      NUMERIC(10,2),
    method          payment_method NOT NULL,
    paid_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT payments_amount_nonneg CHECK (amount >= 0),
    CONSTRAINT payments_tip_nonneg    CHECK (tip_amount IS NULL OR tip_amount >= 0)
);
CREATE INDEX idx_payments_appt     ON payments(appointment_id);
CREATE INDEX idx_payments_org_paid ON payments(organization_id, paid_at);

CREATE TABLE expense_categories (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name            TEXT NOT NULL,
    CONSTRAINT expense_cat_unique UNIQUE (organization_id, name)
);
-- (sem idx_expense_cat_org: o UNIQUE (organization_id, name) já indexa o prefixo organization_id)

CREATE TABLE expenses (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id  BIGINT NOT NULL REFERENCES organizations(id)     ON DELETE RESTRICT,
    unit_id          BIGINT NOT NULL REFERENCES units(id)             ON DELETE RESTRICT,
    category_id      BIGINT NOT NULL REFERENCES expense_categories(id) ON DELETE RESTRICT,
    amount           NUMERIC(12,2) NOT NULL,
    competence_month DATE NOT NULL,   -- convenção: primeiro dia do mês
    note             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT expenses_amount_nonneg CHECK (amount >= 0),
    CONSTRAINT expenses_competence_first_day CHECK (EXTRACT(DAY FROM competence_month) = 1)
);
CREATE INDEX idx_expenses_org_month ON expenses(organization_id, competence_month);
CREATE INDEX idx_expenses_unit      ON expenses(unit_id);

-- ============================================================================
-- DISPONIBILIDADE
-- ============================================================================

CREATE TABLE business_hours (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id   BIGINT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    weekday   SMALLINT NOT NULL,        -- 0 = domingo ... 6 = sábado
    open_time TIME NOT NULL,
    close_time TIME NOT NULL,
    CONSTRAINT bh_weekday_range CHECK (weekday BETWEEN 0 AND 6),
    CONSTRAINT bh_time_valid    CHECK (close_time > open_time),
    CONSTRAINT bh_unique_slot   UNIQUE (unit_id, weekday, open_time)
);
CREATE INDEX idx_business_hours_unit ON business_hours(unit_id);

CREATE TABLE time_off (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    barber_id BIGINT NOT NULL REFERENCES barbers(id) ON DELETE CASCADE,
    start_at  TIMESTAMPTZ NOT NULL,
    end_at    TIMESTAMPTZ NOT NULL,
    reason    TEXT,
    CONSTRAINT time_off_valid CHECK (end_at > start_at)
);
CREATE INDEX idx_time_off_barber ON time_off(barber_id, start_at);

-- ============================================================================
-- INTEGRAÇÕES (andaime mínimo — implementação futura)
-- ============================================================================

CREATE TABLE integration_accounts (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id          BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    unit_id                  BIGINT REFERENCES units(id) ON DELETE CASCADE,
    provider                 integration_provider NOT NULL,
    token_encrypted          BYTEA NOT NULL,   -- cifrado em repouso (chave em cofre/KMS)
    refresh_token_encrypted  BYTEA,
    status                   integration_status NOT NULL DEFAULT 'active',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_integration_accounts_org ON integration_accounts(organization_id);
-- lookup do worker: conta por organização+provider (e por unidade+provider)
CREATE INDEX idx_integration_accounts_provider ON integration_accounts(organization_id, provider);

-- 1:N — uma visita pode sincronizar com mais de uma conta (ex.: agenda do
-- barbeiro + agenda da loja). external_etag detecta conflito bidirecional.
CREATE TABLE calendar_sync (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appointment_id         BIGINT NOT NULL REFERENCES appointments(id)         ON DELETE CASCADE,
    integration_account_id BIGINT NOT NULL REFERENCES integration_accounts(id) ON DELETE CASCADE,
    external_event_id      TEXT,
    external_etag          TEXT,
    sync_status            sync_status NOT NULL DEFAULT 'pending',
    attempt_count          INTEGER NOT NULL DEFAULT 0,
    last_synced_at         TIMESTAMPTZ,
    CONSTRAINT calendar_sync_unique UNIQUE (appointment_id, integration_account_id),
    CONSTRAINT calendar_sync_attempts_nonneg CHECK (attempt_count >= 0)
);
-- fila de pendências/falhas para o worker
CREATE INDEX idx_calendar_sync_pending ON calendar_sync(sync_status)
    WHERE sync_status IN ('pending', 'failed');
-- lookup por evento externo (webhook inbound do Google)
CREATE INDEX idx_calendar_sync_event ON calendar_sync(external_event_id)
    WHERE external_event_id IS NOT NULL;

-- Saída (lembretes) + entrada (respostas/webhooks) com dedup por idempotência.
CREATE TABLE message_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    client_id       BIGINT NOT NULL REFERENCES clients(id)       ON DELETE RESTRICT,
    appointment_id  BIGINT REFERENCES appointments(id)           ON DELETE SET NULL,
    direction       message_direction NOT NULL,
    idempotency_key TEXT UNIQUE,          -- dedup de webhook reentregue (NULLs múltiplos OK)
    template        TEXT,
    delivery_status delivery_status NOT NULL DEFAULT 'pending',
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT message_log_attempts_nonneg CHECK (attempt_count >= 0)
);
CREATE INDEX idx_message_log_org_created ON message_log(organization_id, created_at);
CREATE INDEX idx_message_log_client      ON message_log(client_id);
-- fila de reenvio: cobre primeira tentativa agendada (pending) e reenvio (failed)
CREATE INDEX idx_message_log_retry ON message_log(next_retry_at)
    WHERE delivery_status IN ('pending', 'failed') AND next_retry_at IS NOT NULL;

-- ============================================================================
-- ISOLAMENTO MULTI-TENANT (Row-Level Security por organização)
-- ----------------------------------------------------------------------------
-- A aplicação define o tenant da sessão antes de cada transação:
--     SET app.current_org_id = '<id da organização>';
-- As policies abaixo cobrem as tabelas que carregam organization_id
-- diretamente. As tabelas-filhas (user_units, barber_units, appointment_items,
-- client_consents, business_hours, time_off, calendar_sync) são acessadas
-- pela aplicação SEMPRE através do pai já filtrado; o passo de endurecimento
-- (denormalizar organization_id nelas para RLS direto) fica para fase seguinte.
-- ============================================================================

ALTER TABLE organizations        ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE units                ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE barbers              ENABLE ROW LEVEL SECURITY;
ALTER TABLE services             ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients              ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments         ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments             ENABLE ROW LEVEL SECURITY;
ALTER TABLE expense_categories   ENABLE ROW LEVEL SECURITY;
ALTER TABLE expenses             ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_log          ENABLE ROW LEVEL SECURITY;

-- organizations usa a própria PK como chave de tenant.
CREATE POLICY org_isolation ON organizations
    USING (id = current_setting('app.current_org_id', true)::bigint);

CREATE POLICY tenant_isolation ON subscriptions
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON units
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON users
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON barbers
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON services
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON clients
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON appointments
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON payments
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON expense_categories
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON expenses
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON integration_accounts
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
CREATE POLICY tenant_isolation ON message_log
    USING (organization_id = current_setting('app.current_org_id', true)::bigint);
