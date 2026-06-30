# AI Sales Agent

An autonomous, full-stack AI sales development representative. It finds leads matching an ideal customer profile, researches each company, writes and sends personalized outreach, follows up on a schedule, classifies replies, books meetings on a connected calendar, and hands qualified, interested leads to a human — running continuously on its own without per-step human input.

This repository contains a production-structured implementation: an async Python/FastAPI backend, a LangGraph-orchestrated AI layer, a Celery-driven autonomous worker system, and a Next.js operator console.

---

## What it does

The agent runs a closed loop:

1. **Lead generation** — searches for companies matching ICP criteria (industry, size, tech stack, geography, titles), deduplicates by domain, and enriches contacts via Hunter/Clearbit/Crunchbase.
2. **Research** — scrapes each company's site (Playwright), detects its tech stack, and uses an LLM to extract pain points, products, an ICP fit score, and a tailored value proposition.
3. **Outreach** — generates a non-templated, personalized first email that references concrete facts about the company, then sends it with open/click tracking.
4. **Follow-up** — schedules and sends a configurable follow-up sequence (default day 3 / 7 / 14, max 4 touches), each email adding new value rather than re-pinging.
5. **Reply handling** — ingests inbound replies via webhook, classifies them (interested, wants demo, needs pricing, not interested, unsubscribe, out-of-office, wrong person, …), extracts durable memory (objections, preferences, facts) into a pgvector store, and executes the right next action.
6. **Booking** — for interested leads, queries the rep's Google Calendar free/busy, proposes slots, and books the meeting (with a Google Meet link) when accepted.
7. **Hand-off** — anything needing human judgment surfaces in a review queue; everything else the agent resolves itself.

A Celery beat schedule is the heartbeat that makes this autonomous — research, outreach, follow-ups, reply classification, meeting proposals, and reminders all run on timers, each gated behind a feature flag.

---

## Architecture

```
Next.js operator console
        │  REST + JWT
        ▼
FastAPI (async)  ──►  Services  ──►  Repositories  ──►  PostgreSQL + pgvector
        │                 │
        │                 ├──►  LangGraph AI layer  ──►  OpenAI / Anthropic / Gemini
        │                 └──►  Email (SendGrid/SES/SMTP), Google Calendar, Scraper
        ▼
Celery workers + beat  ──►  Redis (broker + cache + rate limiting)
```

Layering is strict and one-directional: routers depend on services, services depend on repositories, repositories depend on models. The AI layer and external integrations are isolated so providers can be swapped without touching business logic. The same async services are reused by both the API and the Celery workers (bridged via a per-process event loop).

### Tech stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2 (async), Pydantic v2, Alembic
- **AI:** LangGraph + LangChain, OpenAI / Anthropic / Gemini behind a unified router with fallback, pgvector for long-term memory
- **Async/jobs:** Celery + Redis, Celery beat for scheduling
- **Data:** PostgreSQL 16 with pgvector, uuid-ossp, pg_trgm
- **Integrations:** SendGrid / AWS SES / SMTP, Google Calendar, Playwright scraping, Hunter / Clearbit / Crunchbase enrichment
- **Frontend:** Next.js 14 (App Router), React 18, TypeScript, Tailwind, SWR, Recharts
- **Ops:** Docker, docker-compose, GitHub Actions CI, Render / Railway blueprints, Sentry, Prometheus

---

## Repository layout

```
ai-sales-agent/
├── app/
│   ├── core/            # config, database, redis
│   ├── models/          # SQLAlchemy ORM models
│   ├── schemas/         # Pydantic request/response schemas
│   ├── repositories/    # data-access layer (Repository pattern)
│   ├── services/        # business logic
│   ├── ai/              # LLM router, prompts, agents, LangGraph
│   ├── api/v1/          # FastAPI routers
│   ├── workers/         # Celery app, beat schedule, tasks
│   └── main.py          # FastAPI app factory
├── alembic/             # migrations
├── database/schema.sql  # full DDL (also runs on first compose boot)
├── tests/               # unit + integration tests
├── frontend/            # Next.js operator console
├── Dockerfile
├── docker-compose.yml
├── render.yaml / railway.json
└── pyproject.toml
```

---

## Quick start (Docker)

```bash
cp .env.example .env          # fill in OPENAI_API_KEY and any providers you want
docker compose up --build
```

This starts Postgres (with pgvector + schema), Redis, the API (port 8000), a Celery worker, Celery beat, Flower (port 5555), and the frontend (port 3000).

- API docs: http://localhost:8000/docs
- Operator console: http://localhost:3000
- Task monitor: http://localhost:5555

Default seeded admin (from `database/schema.sql`): `admin@example.com` / `changeme` — change immediately.

---

## Local development (without Docker)

Backend:

```bash
pip install ".[dev]"
playwright install chromium
# point DATABASE_URL / REDIS_URL at local services, then:
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker --loglevel=info     # separate shell
celery -A app.workers.celery_app beat --loglevel=info       # separate shell
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

---

## Configuration

All configuration is environment-driven via `app/core/config.py` (Pydantic settings). See `.env.example` for the full list. Key groups:

- **Core:** `SECRET_KEY`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, `DATABASE_URL`, `REDIS_URL`
- **LLM:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_AI_API_KEY`, primary/fallback provider
- **Email:** `DEFAULT_EMAIL_PROVIDER` + SendGrid/SES/SMTP credentials, daily/hourly send limits
- **Calendar:** Google OAuth client id/secret/redirect
- **Enrichment:** Hunter / Clearbit / Crunchbase keys
- **Feature flags:** `FEATURE_AUTO_RESEARCH`, `FEATURE_AUTO_OUTREACH`, `FEATURE_AUTO_FOLLOWUP`, `FEATURE_REPLY_CLASSIFICATION`, `FEATURE_AUTO_BOOKING`, `FEATURE_AI_MEMORY`, `FEATURE_LINKEDIN_SCRAPING`

The feature flags let you turn on autonomy incrementally — e.g. run research and outreach automatically but keep booking manual until you trust it.

---

## Safety, compliance, and guardrails

- **Send limits** are enforced per hour and per day to protect domain reputation.
- **Unsubscribe and bounce handling** stop sequences immediately and mark contacts non-emailable.
- **Robots.txt** is respected during scraping, with per-domain rate limiting via Redis.
- **Secrets at rest** (OAuth tokens, third-party API keys) are Fernet-encrypted.
- **Human-in-the-loop** review queue captures every reply the agent isn't confident about.
- LinkedIn scraping is **disabled by default** and gated behind a feature flag, since compliant use requires a specific proxy/account strategy.

Operating an autonomous outreach system is subject to anti-spam law (CAN-SPAM, GDPR, CASL) and the terms of the data sources and email providers you connect. You are responsible for ensuring your use is lawful and consented where required.

---

## Testing

```bash
pytest -v                       # all tests
pytest -m unit                  # unit only (no DB)
pytest -m integration           # API integration (needs test DB)
pytest --cov=app                # with coverage
```

The integration suite spins up against a `sales_agent_test` database and mocks the LLM so no real AI calls are made. CI runs lint (ruff), type-check (mypy), and the full test suite against Postgres + Redis service containers.

---

## How autonomy is wired (the beat schedule)

| Task | Cadence | What it does |
| --- | --- | --- |
| `research_new_leads` | 10 min | Queue research for unresearched leads |
| `dispatch_initial_outreach` | 5 min | Send first touch to new leads in active campaigns |
| `process_due_followups` | 15 min | Send the next follow-up for due leads |
| `classify_pending_replies` | 5 min | Safety net for replies the webhook missed |
| `propose_meetings` | 15 min | Offer slots to interested leads |
| `send_meeting_reminders` | 10 min | 24h / 1h reminders |
| `aggregate_daily_stats` | nightly | Roll up metrics for the dashboard |
| `cleanup_expired_memory` | nightly | Prune expired vector memory |
| `generate_daily_report` | daily 08:00 | Produce the daily summary |

---

## License

Provided as-is as a reference implementation. Review and harden before production use.
