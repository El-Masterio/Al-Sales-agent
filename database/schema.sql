-- =============================================================================
-- AI Sales Agent — PostgreSQL Schema
-- Version: 1.0.0
-- Requires: PostgreSQL 15+, pgvector extension
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";        -- pgvector for embeddings
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- trigram indexes for fuzzy search

-- =============================================================================
-- ENUMS
-- =============================================================================

CREATE TYPE company_size AS ENUM (
    '1-10',
    '11-50',
    '51-200',
    '201-500',
    '501-1000',
    '1001-5000',
    '5000+'
);

CREATE TYPE lead_status AS ENUM (
    'new',
    'researching',
    'ready_to_contact',
    'contacted',
    'replied',
    'interested',
    'meeting_scheduled',
    'meeting_completed',
    'qualified',
    'proposal_sent',
    'negotiating',
    'closed_won',
    'closed_lost',
    'not_interested',
    'unsubscribed',
    'bounced'
);

CREATE TYPE email_status AS ENUM (
    'draft',
    'queued',
    'sent',
    'delivered',
    'opened',
    'clicked',
    'replied',
    'bounced',
    'failed',
    'unsubscribed'
);

CREATE TYPE email_type AS ENUM (
    'initial_outreach',
    'follow_up_1',
    'follow_up_2',
    'follow_up_3',
    'reply',
    'meeting_confirmation',
    'meeting_reminder',
    'proposal'
);

CREATE TYPE reply_classification AS ENUM (
    'interested',
    'maybe_later',
    'not_interested',
    'needs_pricing',
    'wants_demo',
    'out_of_office',
    'wrong_person',
    'unsubscribe_request',
    'question',
    'positive_general',
    'negative_general',
    'unclassified'
);

CREATE TYPE meeting_status AS ENUM (
    'proposed',
    'confirmed',
    'rescheduled',
    'cancelled',
    'completed',
    'no_show'
);

CREATE TYPE campaign_status AS ENUM (
    'draft',
    'active',
    'paused',
    'completed',
    'archived'
);

CREATE TYPE task_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed',
    'cancelled'
);

CREATE TYPE user_role AS ENUM (
    'admin',
    'sales_rep',
    'viewer'
);

-- =============================================================================
-- UTILITY: updated_at trigger function
-- =============================================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TABLE: users
-- Internal users of the Sales Agent platform
-- =============================================================================

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            user_role NOT NULL DEFAULT 'sales_rep',
    avatar_url      TEXT,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    google_calendar_token   JSONB,          -- encrypted OAuth2 token
    google_calendar_id      TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_users_email ON users(email);

-- =============================================================================
-- TABLE: companies
-- Target companies found via lead generation
-- =============================================================================

CREATE TABLE companies (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    name                TEXT NOT NULL,
    website             TEXT,
    domain              TEXT,                       -- extracted from website
    linkedin_url        TEXT,
    crunchbase_url      TEXT,

    -- Classification
    industry            TEXT,
    sub_industry        TEXT,
    company_size        company_size,
    employee_count      INTEGER,
    founded_year        INTEGER,
    hq_country          TEXT,
    hq_city             TEXT,

    -- Financials
    annual_revenue_usd  BIGINT,
    funding_stage       TEXT,                       -- seed, series-a, etc.
    total_funding_usd   BIGINT,
    last_funding_date   DATE,

    -- Research output (AI-generated)
    description         TEXT,
    products_summary    TEXT,
    pain_points         TEXT[],
    tech_stack          TEXT[],
    recent_news         JSONB,                      -- [{title, url, date, summary}]
    value_proposition   TEXT,                       -- why our service fits them
    icp_score           SMALLINT CHECK (icp_score BETWEEN 0 AND 100),

    -- Status
    lead_status         lead_status NOT NULL DEFAULT 'new',
    assigned_to         UUID REFERENCES users(id) ON DELETE SET NULL,
    disqualify_reason   TEXT,

    -- Research metadata
    last_researched_at  TIMESTAMPTZ,
    research_version    INTEGER NOT NULL DEFAULT 0,

    -- Raw data
    raw_scrape_data     JSONB,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_companies_domain       ON companies(domain);
CREATE INDEX idx_companies_lead_status  ON companies(lead_status);
CREATE INDEX idx_companies_icp_score    ON companies(icp_score DESC);
CREATE INDEX idx_companies_assigned_to  ON companies(assigned_to);
CREATE INDEX idx_companies_industry     ON companies(industry);
CREATE INDEX idx_companies_name_trgm    ON companies USING GIN (name gin_trgm_ops);
CREATE INDEX idx_companies_tech_stack   ON companies USING GIN (tech_stack);

-- =============================================================================
-- TABLE: contacts
-- Decision makers and contacts at target companies
-- =============================================================================

CREATE TABLE contacts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,

    -- Identity
    first_name      TEXT NOT NULL,
    last_name       TEXT,
    full_name       TEXT GENERATED ALWAYS AS (
                        first_name || COALESCE(' ' || last_name, '')
                    ) STORED,
    title           TEXT,
    seniority       TEXT,                           -- c-level, vp, director, manager, ic
    department      TEXT,                           -- engineering, marketing, sales, etc.

    -- Contact info
    email           TEXT,
    email_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    email_bounce    BOOLEAN NOT NULL DEFAULT FALSE,
    phone           TEXT,
    linkedin_url    TEXT,
    twitter_url     TEXT,

    -- Decision maker signal
    is_decision_maker   BOOLEAN NOT NULL DEFAULT FALSE,
    is_primary_contact  BOOLEAN NOT NULL DEFAULT FALSE,

    -- Enrichment metadata
    enrichment_source   TEXT,                       -- hunter, clearbit, manual
    enrichment_at       TIMESTAMPTZ,
    enrichment_data     JSONB,

    -- Opt-out
    unsubscribed        BOOLEAN NOT NULL DEFAULT FALSE,
    unsubscribed_at     TIMESTAMPTZ,

    notes           TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_contacts_updated_at
    BEFORE UPDATE ON contacts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_contacts_company_id    ON contacts(company_id);
CREATE INDEX idx_contacts_email         ON contacts(email);
CREATE INDEX idx_contacts_is_primary    ON contacts(company_id, is_primary_contact);
CREATE UNIQUE INDEX idx_contacts_email_unique ON contacts(email) WHERE email IS NOT NULL;

-- =============================================================================
-- TABLE: campaigns
-- Outreach campaigns grouping related sequences
-- =============================================================================

CREATE TABLE campaigns (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    description     TEXT,
    owner_id        UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    -- Targeting
    icp_criteria    JSONB NOT NULL DEFAULT '{}',    -- {industries, sizes, tech_stack, etc.}
    max_leads       INTEGER NOT NULL DEFAULT 500,

    -- Sequence config
    follow_up_days  INTEGER[] NOT NULL DEFAULT '{3,7,14}',
    max_attempts    SMALLINT NOT NULL DEFAULT 4,

    -- Email config
    from_name       TEXT NOT NULL,
    from_email      TEXT NOT NULL,
    reply_to_email  TEXT,
    email_provider  TEXT NOT NULL DEFAULT 'sendgrid', -- sendgrid | ses | smtp

    -- AI config
    value_proposition   TEXT,                       -- injected into every prompt
    tone                TEXT NOT NULL DEFAULT 'professional', -- professional | friendly | direct
    llm_model          TEXT NOT NULL DEFAULT 'gpt-4.1',

    status          campaign_status NOT NULL DEFAULT 'draft',

    -- Stats (denormalised for dashboard speed)
    stat_leads_added    INTEGER NOT NULL DEFAULT 0,
    stat_emails_sent    INTEGER NOT NULL DEFAULT 0,
    stat_emails_opened  INTEGER NOT NULL DEFAULT 0,
    stat_replies        INTEGER NOT NULL DEFAULT 0,
    stat_meetings       INTEGER NOT NULL DEFAULT 0,

    started_at      TIMESTAMPTZ,
    paused_at       TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_campaigns_updated_at
    BEFORE UPDATE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_campaigns_owner_id ON campaigns(owner_id);
CREATE INDEX idx_campaigns_status   ON campaigns(status);

-- =============================================================================
-- TABLE: campaign_leads
-- Junction: which leads are in which campaign, with per-lead status
-- =============================================================================

CREATE TABLE campaign_leads (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,

    status          lead_status NOT NULL DEFAULT 'new',
    attempt_count   SMALLINT NOT NULL DEFAULT 0,
    next_follow_up  TIMESTAMPTZ,
    stopped_at      TIMESTAMPTZ,
    stop_reason     TEXT,                           -- replied, unsubscribed, max_attempts

    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (campaign_id, company_id)
);

CREATE TRIGGER trg_campaign_leads_updated_at
    BEFORE UPDATE ON campaign_leads
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_campaign_leads_campaign    ON campaign_leads(campaign_id);
CREATE INDEX idx_campaign_leads_company     ON campaign_leads(company_id);
CREATE INDEX idx_campaign_leads_next_fu     ON campaign_leads(next_follow_up) WHERE stopped_at IS NULL;

-- =============================================================================
-- TABLE: emails
-- Every email sent by the system
-- =============================================================================

CREATE TABLE emails (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    campaign_lead_id UUID REFERENCES campaign_leads(id) ON DELETE SET NULL,
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,
    sent_by         UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Email content
    email_type      email_type NOT NULL,
    subject         TEXT NOT NULL,
    body_html       TEXT NOT NULL,
    body_text       TEXT NOT NULL,
    from_email      TEXT NOT NULL,
    from_name       TEXT NOT NULL,
    to_email        TEXT NOT NULL,
    to_name         TEXT,
    reply_to        TEXT,

    -- Threading
    message_id      TEXT UNIQUE,                    -- SMTP Message-ID header
    thread_id       TEXT,                           -- for grouping by thread
    in_reply_to     TEXT,                           -- parent Message-ID

    -- Delivery
    status          email_status NOT NULL DEFAULT 'draft',
    provider        TEXT,                           -- sendgrid | ses | smtp
    provider_message_id TEXT,

    -- Tracking
    tracking_id     UUID NOT NULL DEFAULT uuid_generate_v4(),  -- for pixel/click
    opened_count    SMALLINT NOT NULL DEFAULT 0,
    clicked_count   SMALLINT NOT NULL DEFAULT 0,
    first_opened_at TIMESTAMPTZ,
    last_opened_at  TIMESTAMPTZ,

    -- AI metadata
    ai_model        TEXT,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    generation_ms   INTEGER,

    -- Timestamps
    scheduled_at    TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    bounced_at      TIMESTAMPTZ,
    bounce_type     TEXT,                           -- hard | soft
    bounce_reason   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_emails_updated_at
    BEFORE UPDATE ON emails
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_emails_company_id      ON emails(company_id);
CREATE INDEX idx_emails_contact_id      ON emails(contact_id);
CREATE INDEX idx_emails_campaign_id     ON emails(campaign_id);
CREATE INDEX idx_emails_status          ON emails(status);
CREATE INDEX idx_emails_tracking_id     ON emails(tracking_id);
CREATE INDEX idx_emails_thread_id       ON emails(thread_id);
CREATE INDEX idx_emails_sent_at         ON emails(sent_at DESC);

-- =============================================================================
-- TABLE: email_events
-- Granular open/click/bounce event log
-- =============================================================================

CREATE TABLE email_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_id    UUID NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,          -- opened | clicked | bounced | unsubscribed | spam_complaint
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address  INET,
    user_agent  TEXT,
    click_url   TEXT,                   -- for clicked events
    raw_payload JSONB                   -- full webhook payload
);

CREATE INDEX idx_email_events_email_id  ON email_events(email_id);
CREATE INDEX idx_email_events_type      ON email_events(event_type);
CREATE INDEX idx_email_events_time      ON email_events(occurred_at DESC);

-- =============================================================================
-- TABLE: replies
-- Inbound emails from leads, classified by AI
-- =============================================================================

CREATE TABLE replies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_id        UUID REFERENCES emails(id) ON DELETE SET NULL,   -- the email being replied to
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE SET NULL,

    -- Raw inbound
    from_email      TEXT NOT NULL,
    from_name       TEXT,
    subject         TEXT,
    body_text       TEXT NOT NULL,
    body_html       TEXT,
    message_id      TEXT UNIQUE,
    in_reply_to     TEXT,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- AI classification
    classification  reply_classification NOT NULL DEFAULT 'unclassified',
    classification_confidence   NUMERIC(4,3),       -- 0.000–1.000
    sentiment_score NUMERIC(4,3),                   -- -1.0 to 1.0
    ai_summary      TEXT,
    ai_suggested_action TEXT,
    classified_at   TIMESTAMPTZ,
    classification_model TEXT,

    -- Action taken
    action_taken    TEXT,
    actioned_at     TIMESTAMPTZ,
    actioned_by     UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Human review
    reviewed        BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at     TIMESTAMPTZ,
    override_classification reply_classification,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_replies_updated_at
    BEFORE UPDATE ON replies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_replies_company_id     ON replies(company_id);
CREATE INDEX idx_replies_campaign_id    ON replies(campaign_id);
CREATE INDEX idx_replies_classification ON replies(classification);
CREATE INDEX idx_replies_received_at    ON replies(received_at DESC);
CREATE INDEX idx_replies_reviewed       ON replies(reviewed) WHERE reviewed = FALSE;

-- =============================================================================
-- TABLE: meetings
-- Booked meetings with leads
-- =============================================================================

CREATE TABLE meetings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    reply_id        UUID REFERENCES replies(id) ON DELETE SET NULL,
    assigned_rep    UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Scheduling
    title           TEXT NOT NULL,
    description     TEXT,
    status          meeting_status NOT NULL DEFAULT 'proposed',
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL,
    duration_minutes SMALLINT NOT NULL DEFAULT 30,
    timezone        TEXT NOT NULL DEFAULT 'UTC',

    -- Location
    location_type   TEXT NOT NULL DEFAULT 'video',  -- video | phone | in_person
    meeting_url     TEXT,                           -- Zoom/Meet link
    phone_number    TEXT,
    address         TEXT,

    -- Calendar integration
    google_event_id         TEXT UNIQUE,
    google_calendar_id      TEXT,
    ics_uid                 TEXT UNIQUE,

    -- Outcome
    outcome         TEXT,                           -- completed outcome notes
    outcome_notes   TEXT,
    next_steps      TEXT,
    deal_value_usd  INTEGER,

    -- Reminders
    reminder_24h_sent   BOOLEAN NOT NULL DEFAULT FALSE,
    reminder_1h_sent    BOOLEAN NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_meetings_updated_at
    BEFORE UPDATE ON meetings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_meetings_company_id    ON meetings(company_id);
CREATE INDEX idx_meetings_assigned_rep  ON meetings(assigned_rep);
CREATE INDEX idx_meetings_starts_at     ON meetings(starts_at);
CREATE INDEX idx_meetings_status        ON meetings(status);

-- =============================================================================
-- TABLE: conversation_memory
-- AI long-term memory per company (stored as vector embeddings)
-- =============================================================================

CREATE TABLE conversation_memory (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,

    memory_type     TEXT NOT NULL,                  -- summary | preference | objection | fact | milestone
    content         TEXT NOT NULL,
    embedding       vector(1536),                   -- OpenAI text-embedding-3-small

    -- Context
    source_type     TEXT,                           -- email | reply | meeting | manual
    source_id       UUID,                           -- FK to whichever source table
    importance      SMALLINT NOT NULL DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),

    -- Expiry
    expires_at      TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_memory_updated_at
    BEFORE UPDATE ON conversation_memory
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_memory_company_id  ON conversation_memory(company_id);
CREATE INDEX idx_memory_type        ON conversation_memory(memory_type);
CREATE INDEX idx_memory_embedding   ON conversation_memory
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- =============================================================================
-- TABLE: notes
-- Human or AI-generated notes on any entity
-- =============================================================================

CREATE TABLE notes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    author_id       UUID REFERENCES users(id) ON DELETE SET NULL,
    is_ai_generated BOOLEAN NOT NULL DEFAULT FALSE,

    -- Polymorphic FK (only one set at a time)
    company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE CASCADE,
    meeting_id      UUID REFERENCES meetings(id) ON DELETE CASCADE,

    content         TEXT NOT NULL,
    pinned          BOOLEAN NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT notes_entity_check CHECK (
        (company_id IS NOT NULL)::INT +
        (contact_id IS NOT NULL)::INT +
        (meeting_id IS NOT NULL)::INT = 1
    )
);

CREATE TRIGGER trg_notes_updated_at
    BEFORE UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_notes_company_id   ON notes(company_id);
CREATE INDEX idx_notes_contact_id   ON notes(contact_id);
CREATE INDEX idx_notes_meeting_id   ON notes(meeting_id);

-- =============================================================================
-- TABLE: tasks
-- Celery task audit log
-- =============================================================================

CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    celery_task_id  TEXT UNIQUE,
    task_name       TEXT NOT NULL,
    task_args       JSONB NOT NULL DEFAULT '{}',
    status          task_status NOT NULL DEFAULT 'pending',

    -- Relations (nullable)
    company_id      UUID REFERENCES companies(id) ON DELETE SET NULL,
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    email_id        UUID REFERENCES emails(id) ON DELETE SET NULL,

    -- Execution
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_ms     INTEGER,

    -- Result
    result          JSONB,
    error           TEXT,
    retry_count     SMALLINT NOT NULL DEFAULT 0,
    max_retries     SMALLINT NOT NULL DEFAULT 3,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tasks_status       ON tasks(status);
CREATE INDEX idx_tasks_task_name    ON tasks(task_name);
CREATE INDEX idx_tasks_company_id   ON tasks(company_id);
CREATE INDEX idx_tasks_queued_at    ON tasks(queued_at DESC);

-- =============================================================================
-- TABLE: daily_stats
-- Pre-aggregated daily metrics for dashboard (avoids expensive GROUP BYs)
-- =============================================================================

CREATE TABLE daily_stats (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stat_date       DATE NOT NULL,
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,  -- NULL = global

    leads_added         INTEGER NOT NULL DEFAULT 0,
    leads_researched    INTEGER NOT NULL DEFAULT 0,
    emails_sent         INTEGER NOT NULL DEFAULT 0,
    emails_opened       INTEGER NOT NULL DEFAULT 0,
    emails_clicked      INTEGER NOT NULL DEFAULT 0,
    replies_received    INTEGER NOT NULL DEFAULT 0,
    meetings_booked     INTEGER NOT NULL DEFAULT 0,
    meetings_completed  INTEGER NOT NULL DEFAULT 0,
    deals_closed        INTEGER NOT NULL DEFAULT 0,
    revenue_usd         INTEGER NOT NULL DEFAULT 0,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (stat_date, campaign_id)
);

CREATE TRIGGER trg_daily_stats_updated_at
    BEFORE UPDATE ON daily_stats
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_daily_stats_date       ON daily_stats(stat_date DESC);
CREATE INDEX idx_daily_stats_campaign   ON daily_stats(campaign_id, stat_date DESC);

-- =============================================================================
-- TABLE: api_keys
-- External API keys for integrations (stored encrypted)
-- =============================================================================

CREATE TABLE api_keys (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service     TEXT NOT NULL,                      -- openai | sendgrid | hunter | clearbit | google
    label       TEXT NOT NULL,
    key_hash    TEXT NOT NULL,                      -- pgcrypto encrypted
    key_preview TEXT NOT NULL,                      -- last 4 chars for display
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (user_id, service, label)
);

CREATE INDEX idx_api_keys_user_id  ON api_keys(user_id);
CREATE INDEX idx_api_keys_service  ON api_keys(service);

-- =============================================================================
-- TABLE: webhook_logs
-- Inbound webhook audit log (email provider callbacks, etc.)
-- =============================================================================

CREATE TABLE webhook_logs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source      TEXT NOT NULL,                      -- sendgrid | ses | google
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL,
    processed   BOOLEAN NOT NULL DEFAULT FALSE,
    processed_at TIMESTAMPTZ,
    error       TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_webhook_logs_source    ON webhook_logs(source);
CREATE INDEX idx_webhook_logs_processed ON webhook_logs(processed) WHERE processed = FALSE;
CREATE INDEX idx_webhook_logs_received  ON webhook_logs(received_at DESC);

-- =============================================================================
-- VIEWS
-- =============================================================================

-- Dashboard summary view
CREATE OR REPLACE VIEW v_dashboard_summary AS
SELECT
    c.id                        AS campaign_id,
    c.name                      AS campaign_name,
    c.status                    AS campaign_status,
    COUNT(DISTINCT cl.id)       AS total_leads,
    COUNT(DISTINCT cl.id) FILTER (WHERE cl.status = 'contacted')    AS leads_contacted,
    COUNT(DISTINCT cl.id) FILTER (WHERE cl.status = 'replied')      AS leads_replied,
    COUNT(DISTINCT cl.id) FILTER (WHERE cl.status IN ('interested','meeting_scheduled','qualified')) AS leads_engaged,
    COUNT(DISTINCT e.id) FILTER (WHERE e.status = 'sent')           AS emails_sent,
    COUNT(DISTINCT e.id) FILTER (WHERE e.opened_count > 0)          AS emails_opened,
    COUNT(DISTINCT e.id) FILTER (WHERE e.clicked_count > 0)         AS emails_clicked,
    COUNT(DISTINCT r.id)                                             AS replies_total,
    COUNT(DISTINCT m.id) FILTER (WHERE m.status IN ('confirmed','completed')) AS meetings_booked,
    ROUND(
        COUNT(DISTINCT e.id) FILTER (WHERE e.opened_count > 0)::NUMERIC
        / NULLIF(COUNT(DISTINCT e.id) FILTER (WHERE e.status = 'sent'), 0) * 100, 1
    )                           AS open_rate_pct,
    ROUND(
        COUNT(DISTINCT r.id)::NUMERIC
        / NULLIF(COUNT(DISTINCT e.id) FILTER (WHERE e.status = 'sent'), 0) * 100, 1
    )                           AS reply_rate_pct
FROM campaigns c
LEFT JOIN campaign_leads cl ON cl.campaign_id = c.id
LEFT JOIN emails e          ON e.campaign_id = c.id
LEFT JOIN replies r         ON r.campaign_id = c.id
LEFT JOIN meetings m        ON m.campaign_id = c.id
GROUP BY c.id, c.name, c.status;

-- Lead pipeline view
CREATE OR REPLACE VIEW v_lead_pipeline AS
SELECT
    co.id,
    co.name,
    co.website,
    co.industry,
    co.company_size,
    co.icp_score,
    co.lead_status,
    co.tech_stack,
    ct.full_name    AS primary_contact,
    ct.title        AS contact_title,
    ct.email        AS contact_email,
    u.full_name     AS assigned_to,
    co.last_researched_at,
    co.created_at,
    co.updated_at
FROM companies co
LEFT JOIN contacts ct ON ct.company_id = co.id AND ct.is_primary_contact = TRUE
LEFT JOIN users u     ON u.id = co.assigned_to;

-- =============================================================================
-- SEED DATA
-- =============================================================================

-- Default admin user (password: changeme — bcrypt hash)
INSERT INTO users (email, full_name, password_hash, role) VALUES
(
    'admin@example.com',
    'System Admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewMI8nFgHNVUzxBi',
    'admin'
);

-- Example campaign
INSERT INTO campaigns (
    name, description, owner_id, from_name, from_email,
    follow_up_days, max_attempts, value_proposition, icp_criteria
)
SELECT
    'Q3 SaaS Outreach',
    'Targeting mid-market SaaS companies with 50-500 employees',
    id,
    'Alex Rivera',
    'alex@yourdomain.com',
    '{3,7,14}',
    4,
    'We help SaaS teams reduce churn by 30% through AI-powered customer success workflows.',
    '{"industries": ["SaaS", "Software"], "sizes": ["51-200", "201-500"], "tech_stacks": ["Stripe", "Salesforce", "HubSpot"]}'::JSONB
FROM users WHERE email = 'admin@example.com';

-- =============================================================================
-- MIGRATION TRACKING
-- =============================================================================

CREATE TABLE schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT
);

INSERT INTO schema_migrations (version, description) VALUES
('001', 'Initial schema — all core tables, enums, indexes, views, seed data');
