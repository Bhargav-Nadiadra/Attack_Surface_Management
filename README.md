# ASM Asset Discovery Service

A FastAPI microservice for an Attack Surface Management platform. It manages the domains an
organization wants monitored, runs **passive DNS discovery** (A, AAAA, NS and MX records) in a
background worker, tracks every scan, and exposes the discovered assets through a secured,
role-based REST API.

- **Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync), PostgreSQL 16, Alembic,
  Celery + Redis, JWT (PyJWT) + bcrypt
- **Quality:** pytest (199 tests, ~96% coverage), Ruff, Black, isort, mypy (strict)
- **Run everything:** `docker compose up --build` → <http://localhost:8000/docs>

---

## Contents

1. [Architecture overview](#1-architecture-overview)
2. [Installation (local, without Docker)](#2-installation-local-without-docker)
3. [Run with Docker](#3-run-with-docker)
4. [Run the test suite](#4-run-the-test-suite)
5. [Environment variables reference](#5-environment-variables-reference)
6. [Key design decisions and trade-offs](#6-key-design-decisions-and-trade-offs)
7. [Ideas for future improvement](#7-ideas-for-future-improvement)
8. [API walkthrough (curl)](#8-api-walkthrough-curl)

---

## 1. Architecture overview

### Components

```
                 ┌────────────────────────────────────────────┐
  HTTP client ──►│  api  (FastAPI + uvicorn)                  │
  (Swagger UI)   │  auth · RBAC · domains · scans · assets    │
                 └───────┬───────────────────────┬────────────┘
                         │ SQL                   │ enqueue job (after commit)
                         ▼                       ▼
                 ┌──────────────┐        ┌──────────────┐
                 │  PostgreSQL  │◄───────│    Redis     │  Celery broker
                 │  users       │  SQL   └──────┬───────┘
                 │  domains     │               │ consume
                 │  scans       │        ┌──────▼──────────────────────┐
                 │  assets      │◄───────│ worker (Celery)             │──► DNS resolvers
                 └──────────────┘  SQL   │ scans.run_discovery         │    (A/AAAA/NS/MX)
                        ▲                └─────────────────────────────┘
                        │ SQL            ┌─────────────────────────────┐
                        └────────────────│ beat (Celery)               │
                                         │ scans.sweep_stale every 60s │
                                         └─────────────────────────────┘
```

| Service | Role |
|---|---|
| `api` | FastAPI app: JWT auth, RBAC, domain/scan/asset endpoints, `/health`, `/docs` |
| `worker` | Celery worker that runs DNS discovery jobs |
| `beat` | Celery beat that runs the stale-scan sweeper on a schedule |
| `db` | PostgreSQL 16 |
| `redis` | Celery broker |
| `migrate` | One-shot `alembic upgrade head`; the app services wait for it to succeed |

### Request flow: creating a domain

1. `POST /domains` validates and normalizes the FQDN (lowercase, trailing dot removed).
2. In **one transaction** the service inserts the domain **and** its first scan (`PENDING`), then commits.
3. **Only after the commit** the scan id is enqueued to Celery, so the worker can never look for a row
   that does not exist yet.
4. The worker atomically claims the scan (`UPDATE … SET status='RUNNING' WHERE id=… AND status='PENDING'`),
   resolves A, AAAA, NS and MX with a timeout per record type, stores the assets and marks the scan
   `COMPLETED`, or marks it `FAILED` with an `error_message`.

### Scan lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING: domain created / manual scan
    PENDING --> RUNNING: worker claims the job
    RUNNING --> COMPLETED: DNS records stored
    RUNNING --> FAILED: error, timeout or stale
    PENDING --> PENDING: re-enqueued (sweeper)
    state "Final (a rescan creates a new scan)" as FINAL
    COMPLETED --> FINAL
    FAILED --> FINAL
```

A scan can never stay stuck: any error marks it `FAILED`, Celery time limits stop hung tasks, and the
beat sweeper fails scans left `RUNNING` by a crashed worker and re-enqueues `PENDING` scans whose
enqueue was lost (for example when Redis is briefly down).

### Project structure

```
app/
  api/            route handlers and dependencies (auth, RBAC, DB session, dispatcher)
  core/           config, database, security, permissions, logging, middleware, error handling
  models/         SQLAlchemy models and enums
  schemas/        Pydantic request/response models and validators
  services/       business logic (auth, domains, scans, discovery, sweeper, dispatcher)
  repositories/   data access (queries only)
  workers/        Celery app, tasks and the DNS resolver
migrations/       Alembic migrations
tests/            pytest suite
```

Layering rule: routes only do HTTP work (parsing, status codes, permissions), services own the business
rules and transactions, repositories own the queries, and Celery tasks are thin wrappers around services.

### API summary

| Method | Path | Admin | Analyst | Viewer | Success |
|---|---|:-:|:-:|:-:|---|
| POST | `/auth/login` | public | public | public | 200 token (429 when rate-limited) |
| POST | `/auth/register` | ✅ | ❌ | ❌ | 201 user |
| GET | `/domains?page&limit&status&search` | ✅ | ✅ | ✅ | 200 page |
| POST | `/domains` | ✅ | ✅ | ❌ | 201 domain (auto-scan queued) |
| GET | `/domains/{id}` | ✅ | ✅ | ✅ | 200 domain |
| DELETE | `/domains/{id}` | ✅ | ❌ | ❌ | 204 (scans and assets cascade) |
| POST | `/domains/{id}/scan` | ✅ | ✅ | ❌ | 202 `{scan_id, status}` |
| GET | `/domains/{id}/scans?page&limit` | ✅ | ✅ | ✅ | 200 page of scan history |
| GET | `/assets?domain_id&type&latest_only&page&limit` | ✅ | ✅ | ✅ | 200 page of assets |
| GET | `/health` | public | public | public | 200 / 503 |

Every error uses the same shape:

```json
{ "error": { "code": "domain_exists", "message": "Domain 'example.com' already exists.", "details": [] } }
```

Common codes: `validation_error` (400), `not_authenticated` / `invalid_token` / `token_expired` /
`invalid_credentials` (401), `permission_denied` (403), `domain_not_found` (404), `domain_exists` /
`email_taken` / `scan_in_progress` (409), `rate_limited` (429), `internal_error` (500).

---

## 2. Installation (local, without Docker)

**Prerequisites:** Python 3.12+, a PostgreSQL server (for example managed with pgAdmin) and Redis.

```bash
# 1. Virtual environment and dependencies
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. Configuration
cp .env.example .env                 # Windows: copy .env.example .env
#    then edit .env: set DATABASE_URL to your database, plus JWT_SECRET_KEY and the admin password

# 3. Create the database (e.g. in pgAdmin) and apply migrations
alembic upgrade head

# 4. Redis (any Redis works; Docker is the quickest)
docker run -d --name asm-redis -p 6379:6379 redis:7-alpine
```

Run the three processes in separate terminals:

```bash
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat --loglevel=info
```

> **Windows:** Celery's default prefork pool is not supported on Windows. Start the worker with
> `-P solo` (or `-P threads`): `celery -A app.workers.celery_app worker --loglevel=info -P solo`.

Open <http://localhost:8000/docs>. On first start the API creates the admin user from
`FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` (only when the `users` table is empty).

---

## 3. Run with Docker

```bash
docker compose up --build
```

That single command:

1. builds the image (multi-stage `python:3.12-slim`, runs as a non-root user),
2. starts **PostgreSQL** and **Redis** and waits until both are healthy,
3. runs **Alembic migrations** once in the `migrate` service,
4. starts the **API**, the Celery **worker** and **beat**.

| URL / port | What |
|---|---|
| <http://localhost:8000/docs> | Swagger UI |
| <http://localhost:8000/health> | Health check |
| `localhost:5433` | The compose PostgreSQL (user `asm`, password `asm`, database `asm`) |

**Default login:** `admin@example.com` / `ChangeMe123!` (from `.env.example`).
In Swagger, call `POST /auth/login`, copy `access_token`, click **Authorize** and paste it.

**No `.env` is required.** Containers load `.env.example` first and then `.env` if it exists.
`docker-compose.yml` always points `DATABASE_URL` and the Redis/Celery URLs at the `db` and `redis`
containers, so a local `.env` can never point Docker at another database.

Optional compose variables (shell environment or `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `API_PORT` | `8000` | Host port for the API |
| `POSTGRES_HOST_PORT` | `5433` | Host port for the compose PostgreSQL |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `asm` / `asm` / `asm` | Compose database credentials |
| `WORKER_CONCURRENCY` | `4` | Celery worker processes |
| `DNS_NAMESERVERS` | `1.1.1.1,8.8.8.8` | Resolvers used for discovery inside Docker. Docker's built-in DNS drops AAAA answers when the container network has no IPv6, so discovery queries public resolvers directly |

```bash
docker compose up --build -d     # run in the background
docker compose logs -f worker    # follow the worker logs
docker compose down              # stop (data is kept in the pgdata volume)
docker compose down -v           # stop and delete the database volume
```

---

## 4. Run the test suite

The suite has **199 tests** (~96% coverage). It covers authentication, the complete RBAC matrix,
domain CRUD (including duplicates and FQDN validation), scan triggering and history, enqueue-after-commit
ordering, discovery logic with **DNS mocked**, the stale-scan sweeper, asset filtering, health and
error handling.

**Locally** (uses the database in `DATABASE_URL`):

```bash
pytest
pytest --cov=app --cov-report=term-missing
```

**In Docker** (uses the compose PostgreSQL; starts only `db` and `migrate`):

```bash
docker compose --profile test run --rm tests
docker compose --profile test run --rm tests pytest tests/test_rbac.py -q
```

**How isolation works:** tests run against a real PostgreSQL, because enums and the partial unique index
behave differently on SQLite. Each test runs inside a transaction that is **rolled back** at the end
(`join_transaction_mode="create_savepoint"`), so commits inside services only release a savepoint.
Tests only assert on rows they create, so **existing data is never modified**. No real Redis, Celery or
DNS is used: the scan dispatcher and the DNS resolver are replaced with fakes. The schema must already be
at `head` (`alembic upgrade head`; in Docker the `migrate` service does this). Avoid running the API or
worker against the same database while the tests run.

**Code quality checks:**

```bash
ruff check .
black --check .
isort --check-only .
mypy
```

The `test` stage of the Dockerfile contains these tools too; the production image does not.

**Continuous integration:** `.github/workflows/ci.yml` runs Ruff, Black, isort, mypy and the
test suite (against a PostgreSQL service container) on every push and pull request to `main`.

---

## 5. Environment variables reference

All application settings come from environment variables (or `.env`). **Nothing is hardcoded in the
code**: if a required variable is missing, the app refuses to start and names the variable.
`.env.example` lists every variable with working defaults for local development.

| Variable | Required | Example / default | Description |
|---|:-:|---|---|
| `APP_NAME` | yes | `ASM Asset Discovery Service` | Title shown in the OpenAPI docs |
| `LOG_LEVEL` | yes | `INFO` | Log level for API and worker (JSON logs) |
| `DATABASE_URL` | yes | `postgresql+psycopg://user:pass@localhost:5432/asm` | SQLAlchemy URL (psycopg v3). Overridden by compose in Docker |
| `DB_CONNECT_TIMEOUT_SECONDS` | yes | `3` | DB connect timeout; keeps `/health` fast when the DB is down |
| `JWT_SECRET_KEY` | yes | *(long random string)* | HMAC secret used to sign tokens. **Change it in any real deployment** |
| `JWT_ALGORITHM` | yes | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | yes | `60` | Token lifetime (`expires_in` = minutes × 60) |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | yes | `5` | Login attempts allowed per client IP per window |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | yes | `60` | Length of the login rate-limit window |
| `FIRST_ADMIN_EMAIL` | yes | `admin@example.com` | Admin seeded at startup when no users exist |
| `FIRST_ADMIN_PASSWORD` | yes | `ChangeMe123!` | Seeded admin password; must meet the password policy |
| `DNS_TIMEOUT_SECONDS` | yes | `5` | Timeout per DNS record type |
| `DNS_NAMESERVERS` | no | *(empty)* / `1.1.1.1,8.8.8.8` | Comma-separated resolver IPs used for discovery; empty uses the system resolver |
| `REDIS_URL` | yes | `redis://localhost:6379/0` | Redis URL. Overridden by compose in Docker |
| `CELERY_BROKER_URL` | no | `redis://localhost:6379/0` | Celery broker; empty means `REDIS_URL` |
| `CELERY_RESULT_BACKEND` | no | `redis://localhost:6379/1` | Celery result backend; empty means `REDIS_URL` (results are not stored) |
| `SCAN_SOFT_TIME_LIMIT_SECONDS` | yes | `90` | Soft limit: the scan is marked `FAILED` |
| `SCAN_TIME_LIMIT_SECONDS` | yes | `120` | Hard limit: the task is killed (must be greater than the soft limit) |
| `SWEEP_INTERVAL_SECONDS` | yes | `60` | How often beat runs the stale-scan sweeper |
| `STALE_PENDING_MINUTES` | yes | `2` | `PENDING` scans older than this are re-enqueued |
| `STALE_RUNNING_MINUTES` | yes | `10` | `RUNNING` scans older than this are marked `FAILED` (must exceed the hard limit) |

Secrets live only in `.env`, which is git-ignored. Generate a secret with
`python -c "import secrets; print(secrets.token_urlsafe(64))"`.

---

## 6. Key design decisions and trade-offs

**Sync SQLAlchemy instead of async.** The brief lists async as a bonus. Sync sessions keep the code and
tests simpler and fit Celery, whose tasks are synchronous. Route handlers are plain `def`, so FastAPI
runs them in its thread pool and the event loop is never blocked. Moving to `AsyncSession` is a known
next step.

**Celery + Redis instead of FastAPI `BackgroundTasks`.** `BackgroundTasks` lose jobs when the process
restarts and cannot scale beyond one process. Celery gives a durable queue, separate worker processes
that scale with replicas and `--concurrency`, `acks_late`, time limits, and beat for periodic work.

**Enqueue after commit, plus a sweeper.** The scan row is committed first and enqueued second, so a job
never references a missing row. If the enqueue fails (Redis down), the API still answers 201/202 and the
scan stays `PENDING`; beat re-enqueues it. Workers claim jobs with an atomic conditional `UPDATE`, so a
duplicate delivery is a no-op. Results are not stored in Redis (`task_ignore_result`) because the
database is the source of truth.

**One active scan per domain, enforced twice.** The API returns 409 when a scan is `PENDING` or
`RUNNING`, and a **partial unique index** (`scans(domain_id) WHERE status IN ('PENDING','RUNNING')`)
guarantees it even when two requests race; the resulting `IntegrityError` becomes 409. The brief only
requires blocking while `RUNNING`; blocking `PENDING` as well avoids duplicate queued jobs.

**Domain status mirrors its latest scan.** `domains.status` is `PENDING`, `RUNNING`, `COMPLETED` or
`FAILED`, which matches the examples in the brief and makes "find failed domains" a simple filter.

**A domain is never without a scan.** The domain and its first scan are created in the same transaction.
The automatic scan's `triggered_by` is the user who created the domain.

**Discovery behaviour.**
- The four record types are queried in sequence, each with its own timeout.
- `NoAnswer` means "no records of this type"; `NXDOMAIN` fails the scan with a clear message.
- A timeout on one type is logged and the scan continues; if **every** type fails, the scan fails.
- Values are normalized: IPs as strings, NS hosts lowercase without the trailing dot, MX as
  `"<preference> <exchange>"` (for example `10 mail.example.com`). Duplicates within a scan are removed
  and also blocked by a unique constraint.
- Unexpected errors are stored as a generic message; the details go only to the logs.
- Inside Docker, discovery queries public resolvers (`DNS_NAMESERVERS`, default `1.1.1.1,8.8.8.8`)
  because Docker's built-in DNS drops AAAA answers when the container network has no IPv6. Locally the
  system resolver is used.

**Asset history vs. current state.** `GET /assets` returns assets from every scan by default, which keeps
the full history the brief asks for. `latest_only=true` returns only assets from each domain's latest
`COMPLETED` scan (the current attack surface).

**400 instead of 422.** The brief specifies 400 for validation failures, so FastAPI's default 422 is
replaced. Validation details name the field and the problem but never echo the submitted value, so
passwords cannot leak back in a response.

**Security.**
- bcrypt password hashing; a password policy (8+ characters with upper, lower, digit and special
  character, no whitespace, at most 72 bytes because of bcrypt's input limit).
- JWT with expiry. Each request reloads the user, so deactivation and role changes apply immediately;
  the role is taken from the database, not from the token.
- Login returns the same 401 message for an unknown email, a wrong password and an inactive account, and
  runs a dummy bcrypt check for unknown emails so response time does not reveal which emails exist.
- **Login rate limiting:** each client IP gets `LOGIN_RATE_LIMIT_ATTEMPTS` attempts per
  `LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default 5 per minute), counted in Redis. Further attempts get
  **429** with a `Retry-After` header, before any password check runs. If Redis is unavailable the
  limiter fails open (logs a warning) so an outage cannot lock everyone out.
- `/auth/register` is Admin-only; the first admin is seeded from environment variables.
- **Audit log:** domain deletions and user registrations are recorded in the `audit_logs` table
  (actor, action, target, details) **in the same transaction** as the action, so an action and its
  audit record are saved together or not at all. Records outlive the deleted domain.
- Passwords, tokens and hashes are never logged. Containers run as a non-root user.

**Observability.** Structured JSON logs for requests (method, path, status, duration, `request_id`),
authentication events, the worker job lifecycle (`scan.queued`, `scan.started`, `scan.completed` with
asset counts, `scan.failed`, `scan.swept`) and errors. Every response carries `X-Request-ID`; a valid
incoming id is reused so a request can be traced across services.

**Configuration.** Everything comes from the environment. Docker works with no `.env` because compose
loads `.env.example` and sets the in-network database and Redis URLs itself.

**Testing against the real database.** Tests run on PostgreSQL rather than SQLite (enums and the partial
index behave differently), each inside a rolled-back transaction, so no separate test database is needed
and existing data is never modified.

**Project structure.** Follows the layout suggested in the brief, with `tests/` at the project root
(rather than inside `app/`) so the production image ships without tests.

---

## 7. Ideas for future improvement

- **Automatic retries** for transient DNS failures (Celery `retry` with exponential backoff).
- **Refresh tokens** and token revocation; user management endpoints (deactivate, change role).
- **Scheduled rescans** per domain, and **asset diffing** between scans (new / removed records, alerts).
- **Metrics** endpoint (Prometheus): request latency, scans by status, scan duration.
- **Soft delete** for domains, keeping history for audits.
- **Fully async** stack (`asyncpg` + `AsyncSession`).
- **Multi-tenancy** (organizations owning domains).
- Scaling: run multiple API replicas behind a load balancer, add worker replicas, use PgBouncer for
  connection pooling, respect upstream DNS rate limits, and partition the `assets` table by time.

---

## 8. API walkthrough (curl)

```bash
BASE=http://localhost:8000

# Log in as the seeded admin
ADMIN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"ChangeMe123!"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Register an analyst (Admin only)
curl -s -X POST $BASE/auth/register -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"email":"analyst@company.com","password":"StrongPass123!","full_name":"Jane Analyst","role":"ANALYST"}'

# Create a domain: a discovery scan starts automatically
DOMAIN_ID=$(curl -s -X POST $BASE/domains -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"domain":"Example.COM"}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")

# Poll the scan history until the scan is COMPLETED
curl -s "$BASE/domains/$DOMAIN_ID/scans" -H "Authorization: Bearer $ADMIN"

# List the discovered assets (all, by domain, by record type, latest scan only)
curl -s "$BASE/assets" -H "Authorization: Bearer $ADMIN"
curl -s "$BASE/assets?domain_id=$DOMAIN_ID&type=A" -H "Authorization: Bearer $ADMIN"
curl -s "$BASE/assets?domain_id=$DOMAIN_ID&latest_only=true" -H "Authorization: Bearer $ADMIN"

# Trigger a manual rescan (202), then delete the domain with its scans and assets (204)
curl -s -X POST "$BASE/domains/$DOMAIN_ID/scan" -H "Authorization: Bearer $ADMIN"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/domains/$DOMAIN_ID" -H "Authorization: Bearer $ADMIN"

# Health
curl -s $BASE/health
```

On Windows PowerShell, use `curl.exe` (not the `curl` alias) or the Swagger UI at `/docs`.
