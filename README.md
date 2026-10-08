# PulseWatch — Uptime & Incident Monitoring

Add a website or API, and PulseWatch checks it every 30 s – 15 min, charts response times,
tracks uptime %, opens an **incident** when it goes down and **emails you** when it goes down
and when it recovers.

**Stack:** React 19 + TypeScript + Tailwind + Recharts · FastAPI · PostgreSQL · SQLAlchemy/Alembic ·
asyncio/httpx workers · Docker · AWS (ECS Fargate, RDS, ALB, S3, CloudFront, SES, Secrets Manager,
CloudWatch) · Terraform · GitHub Actions (CI + OIDC deploys)

![Dashboard](docs/dashboard.png)
![Monitor detail](docs/monitor-detail.png)
<sub>Screenshots use sample history from `scripts/seed_demo.py`.</sub>

## Architecture

```mermaid
flowchart LR
  U[Browser] -->|HTTPS| CF[CloudFront]
  CF -->|static files| S3[(S3: React build)]
  CF -->|/api/*| ALB[Load balancer]
  ALB --> API[FastAPI on ECS Fargate]
  API --> DB[(RDS PostgreSQL)]
  W[Checker workers on ECS Fargate] -->|claim due monitors\nFOR UPDATE SKIP LOCKED| DB
  W -->|HTTP checks| T[Monitored websites]
  W -->|down / recovered| SES[Amazon SES email]
  CW[CloudWatch alarms] --> SNS[SNS email]
```

## Engineering highlights

| Problem | How it's solved |
|---|---|
| Run many workers without checking a site twice | Workers claim due monitors with `SELECT … FOR UPDATE SKIP LOCKED` in short transactions (never held during network I/O). A test runs 4 concurrent workers over 200 monitors and asserts every monitor is claimed exactly once. |
| Slow checks overlapping | A worker claims only as many monitors as it has free slots, so each lease starts when its check starts. Every claim gets a **unique token and a lease** (`timeout + 5 s`), and every check runs under a **total deadline** (DNS + connect + full response; httpx's own timeouts are per-read, so a server trickling bytes could otherwise run forever). A result is accepted only with the current token before the lease expires. |
| Email problems affecting monitoring | **Transactional outbox:** alerts are written to a `notifications` table in the same transaction as the check result. A **separate notifier process** runs 4 sending slots; each claims **one** email at a time (so no worker sits on emails it isn't sending), and a **heartbeat renews the claim while the send runs**; SMTP sends also have a **real total deadline** that shuts the socket (per-read timeouts alone let a server trickle bytes forever). Real-socket tests cover a trickling SMTP server and a send longer than the claim. No transaction is open while sending, completion/retry times are taken after the send, and retries back off exponentially (at-least-once). A test runs two workers with 9-second sends and checks all 20 emails go out exactly once. Verified live: with a mail server taking 3 s per email, checker rounds stayed at 1 s. |
| Users choose URLs our servers request (SSRF) | The hostname is resolved **once**, every address must be public (blocks `127.0.0.1`, `10.x`, AWS metadata `169.254.169.254`, …), and the checker connects to **that exact IP** with the original Host header and TLS SNI, closing the DNS-rebinding gap. Redirects aren't followed; no connection reuse across hostnames. |
| Alert fatigue from one network blip | A monitor goes **down** only after N consecutive failures (default 2); incidents are tracked independently of the display status (so pausing/resuming can't strand one), with one email per outage plus a recovery email. |
| Long chart ranges | 7 days of 1-minute checks (10,080 rows) is downsampled server-side into ≤ 500 time buckets; a bucket containing any failure shows as failed. |
| Unbounded data growth | Composite index on `(monitor_id, checked_at)`; workers purge checks older than 30 days. |
| Secure auth | bcrypt (cost 12, 72-byte limit validated with a clear error), short-lived JWTs, identical errors for unknown email vs wrong password, other users' monitors return 404 (not 403). An expired token signs the user out of the UI automatically. |
| Single origin in production | CloudFront serves the React app from a private S3 bucket and forwards `/api/*` to the ALB: free HTTPS, no CORS, and the ALB only accepts traffic from CloudFront's IP ranges. |
| No AWS keys in GitHub | GitHub Actions assumes a deploy role through OIDC, scoped to this repo's `main` branch and least-privilege actions. |
| Deploy role drift | A test parses every `aws …` command in the deploy workflow and fails if the Terraform deploy role doesn't allow it (`iam:PassRole` scoped to the two ECS roles). |
| Bad or untested deploys | Deploy runs only after CI passes and checks out **the exact commit CI tested**; images are tagged with the git SHA in an **immutable** ECR repo and each release registers a task definition pinned to that image. ECS circuit breaker rolls back failures. |
| Schema drift | A test applies all Alembic migrations to a fresh, empty database, runs `alembic check` (models == migrations), downgrades and upgrades again. |

## Delivery guarantees

Alert email is **at-least-once**, not exactly-once. A duplicate is possible if:

- a notifier crashes after the provider accepted an email but before recording it as sent, or
- an SES send is still running after `MAX_HOLD_S` (150 s): claim renewal stops, but the
  in-flight HTTPS request can't be cancelled, so another worker may retry it.

SMTP sends can't hit the second case, because their total deadline (30 s) shuts the socket long
before `MAX_HOLD_S`. Neither SMTP nor SES offers an idempotency key, so a duplicate alert is the
chosen trade-off over a lost one.

## Results

> Fill these in after running them yourself.

| Metric | Value | How measured |
|---|---|---|
| Worker throughput | **162–181 checks/sec, 0 duplicate checks** in each of 3 runs (2,000 checks per run, ~11–12 s) | `make bench` → `scripts/bench_worker.py`: 2,000 monitors, 4 workers, local test server with 20–80 ms latency and 5% errors. Measured 2026-10-08 at commit `4017245`, 2 vCPUs, PostgreSQL 16 |
| Tests | 58 backend (PostgreSQL) + 11 frontend + 4 infra | `make test`, run in CI on every push |
| Deployment | AWS infrastructure (ECS Fargate, RDS, CloudFront) and the deploy workflow are defined; not yet applied to a live AWS account | `infra/terraform/`, `.github/workflows/deploy.yml` |

## Run locally

**Option A — Docker (everything):**
```bash
docker compose up --build        # app: http://localhost:8080   alert emails: http://localhost:8025
```

**Option B — without Docker (for development):**
```bash
# 1. PostgreSQL running locally, then:
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pulsewatch
alembic upgrade head
python scripts/seed_demo.py            # optional sample data (demo@pulsewatch.dev / demo-password)
uvicorn app.main:app --reload          # API docs: http://localhost:8000/docs
python -m app.worker                   # second terminal: checker
python -m app.notify_worker            # third terminal: email sender
# 2. Frontend
cd ../web && npm install && npm run dev   # http://localhost:5173
```

## Tests and benchmark

```bash
cd backend && TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pulse_test python -m pytest -q
cd web && npm test
createdb pulsewatch_bench   # the benchmark refuses to run on any database without "bench" in its name
cd backend && DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pulsewatch_bench \
  python scripts/bench_worker.py --monitors 2000 --workers 4
```
Without `TEST_DATABASE_URL` the backend tests use SQLite and skip the concurrency test.

## Deploy to AWS

1. Install Terraform and the AWS CLI; run `aws configure` with an admin user of **your** account.
2. ```bash
   cd infra/terraform
   cp terraform.tfvars.example terraform.tfvars   # set your email and GitHub repo
   terraform init && terraform apply
   ```
3. Click the two verification emails from AWS (SES sender + SNS alarms).
4. Copy the `github_actions_variables` output into GitHub → Settings → Secrets and variables →
   Actions → **Variables**. Then GitHub → Actions → **Deploy** → *Run workflow* for the first
   release (until then the ECS services have no image to run). After that, every push to `main`
   that passes CI deploys itself.
5. Open the `app_url` output.

**Cost:** roughly $25–35/month (load balancer ~$16, two small Fargate tasks ~$18; RDS is free-tier
eligible for 12 months). Record your demo, take screenshots, then `terraform destroy` if you don't
want to keep it running. **SES sandbox:** new accounts can only email verified addresses — fine for
a demo; request production access to email anyone.

## Project layout

```
backend/   FastAPI app (app/), worker, Alembic migrations, tests, benchmark + seed scripts
web/       React + TypeScript frontend (Vite, Tailwind, Recharts, Vitest)
infra/     Terraform for AWS
.github/   CI (tests, lint, build, terraform validate) and OIDC deploy
```
