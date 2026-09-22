# MAGE BOOKS SAAS

## Master 5-Sprint Implementation Plan & Feature Playbook

**Autonomous Developer & AI Agent Execution Manual:**  
*Feature-by-Feature Branching, Misuse Case Threat Modeling, and Automated CI/CD Security Testing*

**Author & Engineering Lead:** Marcel Yeboah  
**Target System:** Mage Books SAAS (Ghana Enterprise Accounting Platform)  
**Version:** 2.1.0 (Progressive Security & Threat Modeling Edition)  
**Execution Protocol:** Feature Branching, Misuse Case Gate & Human-in-the-Loop Push Gate  
**Date:** September 2026

---

## 1. Critical Operational Directives for Developers & AI Agents

To ensure disciplined code execution, strict ledger integrity, and zero regressions across the 5 sprints, every human developer and autonomous AI agent (including Antigravity, Cursor, and Claude Code) must strictly adhere to the following seven engineering mandates:

1. **Feature-by-Feature Implementation, PR Merge Gate & Branch Cleanup Protocol:**  
   Development must proceed strictly feature by feature. Developers and agents must never implement multiple features at once or commit directly to the `main` or `develop` branches. For each feature, create a dedicated branch (`feat/<feature-name>`). Before starting any new feature, the agent must ALWAYS check whether the PR for the previous feature has been merged into `develop`. If merged, delete both the local branch and remote branch, pull the latest `develop`, and only then create the next feature branch. Implement the required code, execute automated unit tests and negative abuse tests, and then halt to let the user review, commit, and push the branch to GitHub. Only upon explicit user confirmation does the agent proceed to the next feature.

2. **Progressive Misuse Case & Negative Security Testing:**  
   For every feature implementing critical state machines, authentication, tax splits, or payment reconciliation, the feature branch **MUST** include corresponding negative abuse/misuse test cases located in `tests/security/` (or `apps/<app>/tests/test_security.py`). A feature cannot be deemed complete if it only verifies happy-path conditions without validating defensive failure boundaries.

3. **Human-in-the-Loop Migration Authorization:**  
   Autonomous agents are strictly forbidden from automatically executing `python manage.py migrate` against development or production PostgreSQL/Supabase databases. The agent must generate migration scripts using `makemigrations`, inspect the generated SQL using `sqlmigrate <app> <migration_number>`, output the SQL inspection to the user, and explicitly pause to ask for confirmation before applying any changes.

4. **External APIs & Live Credentials Gate:**  
   When external credentials or endpoints are required (Paystack Live Secret Key, Hubtel Client Credentials, GRA E-VAT Clearance API Keys, or Cloudflare R2 Access Tokens), the agent must prompt the user for them. Concurrently, the codebase must maintain deterministic Mock Service Adapters (e.g., `MockPaystackGateway`, `MockGraEvatClient`, `MockR2Storage`) so that the entire test suite and local development can run offline without live credentials.

5. **Single Unified Configuration via django-environ:**  
   Do not split Django settings into `base.py`, `local.py`, or `production.py`. Maintain exactly **ONE** clean `config/settings.py` file utilizing `django-environ` with explicit type casting and safe development fallbacks. The `.env` file must be discovered gracefully from `BASE_DIR` without crashing when deployed to containerized environments where environment variables are injected at runtime. In non-debug production environments, security defaults (`SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`) must strictly fail fast if omitted.

6. **Isolated Testing Protocol with SQLite:**  
   All automated unit, integration, and security abuse tests must run against SQLite in-memory (`:memory:`), dynamically selected by the test runner in `config/settings.py`. PostgreSQL is reserved strictly for development and production workloads. Automated tests must execute in under 5 seconds.

7. **Modern Python Tooling via uv and ruff:**  
   Package installation, environment locking, and script execution must be performed using `uv` (`uv add`, `uv run`, `uv sync`). Developers and agents must NEVER invoke global/system Python directly. All commands must be run via `uv run` (e.g., `uv run python manage.py ...`) to prevent `ModuleNotFoundError` on installed packages. Formatting and linting must be strictly verified using `ruff` (`ruff check .`, `ruff format .`) before any feature hand-off.

---

## 2. Project Tooling, Environment & Single Settings Configuration

The backend standardizes on Python 3.12 (or 3.14), `uv`, and `ruff`. The runtime configuration is managed through a single `config/settings.py` file utilizing `django-environ` with fail-closed production security defaults:

```python
# config/settings.py
from pathlib import Path
import sys
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# 1. Initialize environ
env = environ.Env()

# 2. Read .env file from BASE_DIR (if present)
# Does not fail if .env is missing (e.g. in containerized production environments)
environ.Env.read_env(BASE_DIR / ".env")

# 3. Detect Testing and Debug Modes
IS_TESTING = "test" in sys.argv or "pytest" in sys.modules
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# 4. Fail-closed Security Defaults for SECRET_KEY, ALLOWED_HOSTS, and CORS
if IS_TESTING or DEBUG:
    SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-magebooks-dev-key")
    ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
    CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])
else:
    # Production strictly fails fast on missing security environment variables
    SECRET_KEY = env("DJANGO_SECRET_KEY")
    ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
    CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party extensions
    "rest_framework",
    "corsheaders",
    "storages",
    # Core Domain Apps
    "apps.core",
    "apps.authentication",
    "apps.tenancy",
    "apps.ledger",
    "apps.tax",
    "apps.invoicing",
    "apps.payments",
    "apps.payroll",
    "apps.audit",
]

# Database Routing: In-Memory SQLite for Automated Tests, PostgreSQL for Dev/Prod
if IS_TESTING:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
elif DEBUG:
    # Safe fallback for local development with DEBUG=True
    DATABASES = {
        "default": env.db("DATABASE_URL", default="postgres://postgres:postgres@localhost:5432/magebooks_db")
    }
else:
    # Production strictly requires DATABASE_URL to prevent silent fallback to default credentials
    DATABASES = {
        "default": env.db("DATABASE_URL")
    }

# Cloudflare R2 Object Storage (S3-Compatible)
CLOUDFLARE_R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
CLOUDFLARE_R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
CLOUDFLARE_R2_BUCKET_NAME = env("R2_BUCKET_NAME", default="magebooks-prod")
CLOUDFLARE_R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")
```

---

## 3. Threat Modeling & Progressive Misuse Case Matrix

In financial software, standard use cases define happy-path commercial interactions. Misuse cases (or abuse cases) model deliberate attacks, race conditions, and edge-case exploits. By defining misuse cases alongside feature requirements, security is transformed into an explicit set of negative invariants and automated test assertions:

| Misuse Case ID | Target Asset & Attack Vector | Threat Mechanism & Impact | Defensive Mitigation | Sprint & Feature Assignment |
| :--- | :--- | :--- | :--- | :--- |
| **MUC 1.1** | **Mobile Money Underpayment Attack** | Attacker pays GHS 1.00 on a GHS 1,200 invoice. If system checks reference existence without exact amount match, invoice marks `PAID`. | Exact Decimal matching (`amount == invoice.total_amount`); transitions to `PARTIALLY_PAID` or Suspense Account 2150. | **Sprint 4** (Feature 4.3) |
| **MUC 1.2** | **Forged Webhook HMAC Signature** | Attacker posts fake payment payload to `/api/v1/payments/webhooks/momo/` to credit invoices without real funds. | Constant-time HMAC-SHA256 signature verification (`hmac.compare_digest`) rejecting non-matching calls with HTTP 401. | **Sprint 4** (Feature 4.1) |
| **MUC 2.1** | **Cross-Tenant BOLA/IDOR Header Spoof** | User in Tenant A sends `X-Tenant-ID` header of Tenant B to inspect competitor invoices and financial ledgers. | `TenantSecurityMiddleware` Stage 3 & 4 validates active membership; terminates unauthorized sessions with HTTP 403. | **Sprint 1** (Feature 1.4) |
| **MUC 2.2** | **RLS Database Session Leak** | Pooled DB connection retains Tenant A context and leaks to subsequent request on same pooled connection. | Middleware executes `SET LOCAL app.current_tenant_id` inside atomic transaction; auto-deallocates on commit/rollback. | **Sprint 1** (Feature 1.4) |
| **MUC 3.1** | **Mobile PWA Physical Cache Dump** | Attacker inspects browser IndexedDB / Dexie.js cache on stolen phone to dump customer TINs and sales. | Client-side field-level encryption (WebCrypto AES-GCM) for sensitive PII before persisting to local cache. | **Sprint 3** (Feature 3.1) |
| **MUC 4.1** | **PDF Engine Server-Side Request Forgery** | Attacker creates customer named `<img src='http://169.254.169.254/latest/meta-data/'>` to leak cloud secrets during PDF compile. | Explicit programmatic URL fetcher disabling (`disabled_url_fetcher`) preventing ReportLab/WeasyPrint from dialing out. | **Sprint 3** (Feature 3.4) |
| **MUC 5.1** | **Payroll Maker Self-Approval Collusion** | Accountant creates payroll draft and attempts to authorize own payment run without independent oversight. | Anti-self-approval validation (`maker_id != checker_id`) returning HTTP 403 Forbidden. | **Sprint 5** (Feature 5.4) |
| **MUC 5.2** | **TOTP 2FA Replay & Concurrency Race** | Attacker sniffs 6-digit TOTP and replays it within 30s drift window; concurrent approval threads bypass locks. | Single-use TOTP consumption cache in Redis (60s TTL) plus distributed Redis lock on `payroll_id` during approval. | **Sprint 5** (Feature 5.4) |

---

## 4. Automated Security Testing Pipeline in CI/CD

To prevent security debt, automated security gates are integrated directly into Continuous Integration (`.github/workflows/security.yml` and `.github/workflows/ci.yml`). Every feature pull request is automatically vetted across five automated layers before merge:

1. **Secret Scanning (Gitleaks):** Scans every commit diff for high-entropy strings, Paystack keys, Supabase URLs, or R2 credentials. Rejects push if a secret is detected.
2. **Software Composition Analysis (pip-audit & npm audit):** Audits open-source dependencies in `pyproject.toml` and `package-lock.json` against the National Vulnerability Database. Fails on High/Critical CVEs (CVSS >= 7.0).
3. **Static Application Security Testing (Bandit & ESLint Security):** Scans Python code for insecure functions, weak cryptography, SQL injection vectors, and hardcoded secrets without executing code.
4. **Django Deployment Security Audit:** Executes `python manage.py check --deploy` in CI to verify production hardening flags (HSTS, SSL redirect, secure session cookies).
5. **Automated Misuse Case Abuse Test Suite:** Executes `python manage.py test tests.security` running negative abuse penetration tests against API endpoints.

```yaml
# .github/workflows/security.yml
name: Security & Misuse Testing Gate

on:
  push:
    branches: [ develop, main ]
  pull_request:
    branches: [ develop, main ]

jobs:
  secret-scan:
    name: Secret & Credential Leak Detection
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  backend-security:
    name: Backend SAST, SCA & Misuse Tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
      - run: uv python install 3.12
      - run: uv sync

      # SCA Check
      - name: Dependency Vulnerability Audit
        run: |
          uv pip install pip-audit
          uv run pip-audit --strict --desc

      # SAST Check
      - name: Python Bandit SAST
        run: |
          uv pip install bandit
          uv run bandit -r apps/ config/ -ll -ii

      # Functional Unit Tests
      - name: Run SQLite Unit Tests
        run: uv run python manage.py test apps

      # Negative Misuse & Abuse Test Suite
      - name: Run Automated Misuse Cases
        run: uv run python manage.py test tests.security
```

---

## 5. Feature-by-Feature Git Lifecycle & Hand-off Protocol

To ensure complete transparency and code review between the autonomous agent and the project owner, every single feature follows a strict execution loop:

### Phase 0: Pre-Feature PR Merge Verification & Branch Cleanup Gate
Before writing a single line of code or creating a new feature branch, the agent must ALWAYS check whether the PR for the previous feature has been merged into `develop`:
1. If the previous PR is merged:
   - Switch to `develop` and pull latest upstream commits:
     ```bash
     git checkout develop && git pull origin develop
     ```
   - Delete the merged local branch:
     ```bash
     git branch -d feat/<previous-feature-name>
     ```
   - Delete the merged remote branch:
     ```bash
     git push origin --delete feat/<previous-feature-name>
     ```
2. If the previous PR is NOT yet merged:
   - The agent must halt and wait for the user to confirm that the PR has been reviewed and merged into `develop`.

### Phase A: Feature Branch Creation
Once `develop` is fully updated and old branches are cleaned up, verify that the working tree is clean and create the new feature branch:
```bash
git checkout -b feat/<feature-name>
```

### Phase B: Test-Driven Implementation & SQLite Verification
Implement the feature's models, services, views, and unit tests. Run linting and automated tests against the in-memory SQLite runner using `uv run` to guarantee 100% test pass rates:
```bash
# Run fast linting and formatting checks
uv run ruff check .
uv run ruff format .

# Execute isolated in-memory SQLite test suite
uv run python manage.py test apps.<app_name>
```

### Phase C: Migration Inspection (If Schema Modified)
If the feature introduces or mutates database models, generate the migration and inspect the raw SQL. The agent must output this SQL to the user and request approval before proceeding:
```bash
uv run python manage.py makemigrations <app_name>
uv run python manage.py sqlmigrate <app_name> <migration_number>
# [PAUSE]: Prompt user for confirmation before running 'migrate'.
```

### Phase D: Hand-off, Review & User Push Gate
Once tests pass, the agent halts and presents the exact git command sequence to the user. The user reviews the git diff and pushes the branch to GitHub:
```bash
git status
git add .
git commit -m "feat(<scope>): implement <feature description>"
git push -u origin feat/<feature-name>
```

The agent waits for the user to confirm that the branch has been pushed and the pull request opened. The agent then loops back to **Phase 0** before starting the next feature.

---

## 6. Sprint 1: Core Foundation, Multi-Tenancy & Security Baseline

**Sprint Objective:** Establish tooling, single environ configuration, JWT authentication, 5-stage `TenantSecurityMiddleware`, and Dual-UUID base models, incorporating CI/CD security scanning and cross-tenant BOLA defenses.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Misuse Tests |
| :--- | :--- | :--- | :--- |
| **Feature 1.1** | `feat/sprint1-tooling-environ-settings` | Initialize project with `uv init`, configure `pyproject.toml` with `ruff`, install dependencies (`django-environ`, `uuid6`, `psycopg`, `djangorestframework`), create single `config/settings.py`, configure `.github/workflows/security.yml` (Gitleaks, Bandit, pip-audit), and verify SQLite test runner. | `uv run python manage.py test apps.core` (Runner boots in <1s; CI workflow passes) |
| **Feature 1.2** | `feat/sprint1-auth-jwt-sessions` | Implement `CustomUser` model, `CustomUserManager`, and JWT login/logout/refresh endpoints setting HttpOnly, Secure, SameSite=Strict session cookies. Defend against CSRF via `JWTCookieAuthentication.enforce_csrf` and allow safe header fallback for stale cookies. | `TestJWTAuth`: Login returns 200 with HttpOnly cookies; cookie mutating requests require CSRF; unauthenticated requests return 401. |
| **Feature 1.3** | `feat/sprint1-tenancy-rbac-models` | Implement `Organization` and `OrganizationMembership` models in `apps/tenancy` with 5 RBAC roles (`OWNER`, `ADMIN`, `ACCOUNTANT`, `BOOKKEEPER`, `AUDITOR`) and auditor `access_expires_at`. | `TestTenancyModels`: User assigned roles; membership queries scoped correctly. |
| **Feature 1.4** | `feat/sprint1-tenant-security-middleware` | Build `TenantSecurityMiddleware` executing 5 guards. Incorporate **Misuse Case 2.1** (Cross-Tenant Header Spoofing BOLA) and **Misuse Case 2.2** (RLS Session Leak) defenses in `tests/security/test_tenancy_security.py`. | `TestTenantSecurity`: Spoofed `X-Tenant-ID` returns 403; expired auditor returns 403; `SET LOCAL` resets across requests. |
| **Feature 1.5** | `feat/sprint1-dual-uuid-base-models` | Implement `BaseTenantModel` with `uuid6.uuid7` internal primary key, organization ForeignKey, composite `UNIQUE(organization, id)` constraint for database-level tenant isolation, and `PublicShareableMixin` with `uuid4` `share_token` in `apps/core`. Establish migration inspection protocol. | `TestDualUUID`: Assert `id` is UUIDv7 (timestamp ordered) and `share_token` is UUIDv4. |

---

## 7. Sprint 2: Double-Entry Ledger Core & 2026 Ghanaian Statutory Tax Engine (Act 1151)

**Sprint Objective:** Implement append-only double-entry general ledger journals, sub-5ms dynamic balance calculations, and Act 1151 unified 20.0% tax engine with floating-point truncation defenses.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Misuse Tests |
| :--- | :--- | :--- | :--- |
| **Feature 2.1** | `feat/sprint2-chart-of-accounts-calendar` | Implement `FiscalCalendar`, `FiscalPeriod`, and `ChartOfAccounts` models with clean 4-digit hierarchy (1000-5999) and Ghanaian standard initial seed fixture. | `TestChartOfAccounts`: Seed loads 4-digit accounts; validates account categories. |
| **Feature 2.2** | `feat/sprint2-double-entry-ledger-engine` | Implement `JournalEntry` and `JournalLine` models with `check_positive_values` and `check_either_debit_or_credit` constraints. Implement `LedgerService.post_journal_entry()` enforcing `Sum(Debits) == Sum(Credits)` and deterministic `ORDER BY id` lock ordering to prevent deadlock exploits. | `TestLedgerEngine`: Unbalanced entry raises `ValidationError`; balanced entry commits successfully. |
| **Feature 2.3** | `feat/sprint2-act1151-tax-engine` | Implement `TaxCalculationEngine` in `apps/tax/services.py` enforcing Act 1151: 15% VAT, 2.5% NHIL, 2.5% GETFund (unified 20% non-cascading rate). Defend against floating-point truncation via `Decimal` math. COVID levy completely abolished. | `TestAct1151TaxEngine`: GHS 1000 base yields exactly GHS 150 VAT, GHS 25 NHIL, GHS 25 GETFund. |
| **Feature 2.4** | `feat/sprint2-dynamic-balance-selectors` | Build optimized SQL balance selectors in `apps/ledger/selectors.py` computing real-time Trial Balance, Profit & Loss, and Balance Sheet via single SQL aggregates without locking account records. | `TestDynamicBalances`: Sub-5ms calculation over 10,000 synthetic journal lines in SQLite. |

---

## 8. Sprint 3: Invoicing, Luhn Sequence References & Air-Gapped PDF Generation

**Sprint Objective:** Implement B2B/B2C invoice compilation, customer point-in-time snapshots, self-validating Luhn sequence codes, PWA IndexedDB encryption, and air-gapped PDF generation defending against SSRF.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Misuse Tests |
| :--- | :--- | :--- | :--- |
| **Feature 3.1** | `feat/sprint3-invoicing-models-snapshots` | Implement `Invoice` and `InvoiceLine` models in `apps/invoicing` with database-enforced composite tenant foreign key (`(organization_id, customer_id) -> contacts(organization_id, id)`). Store immutable point-in-time customer legal snapshot (legal name, TIN/Ghana Card PIN, address). Implement client-side WebCrypto AES-GCM encryption for PWA IndexedDB cache (**MUC 3.1**). | `TestInvoiceSnapshot`: Updating customer profile after invoice issuance leaves invoice snapshot untouched. |
| **Feature 3.2** | `feat/sprint3-luhn-reference-generator` | Implement self-validating sequence code generator with Luhn check-digit (e.g., `'84291-6'`) and Ghana Card / TIN regex pre-validators in `apps/invoicing/utils.py`. | `TestLuhnGenerator`: Validates correct Luhn check digits; detects transpositions in O(1). |
| **Feature 3.3** | `feat/sprint3-invoicing-api-ledger-posting` | Build `InvoiceCreateAPIView` with atomic posting to `LedgerService` (Dr 1200 AR, Cr 4000 Revenue, Cr 2100/2110/2120 Taxes). Commits locally as `'PENDING_GRA'` and returns HTTP 201 in <150ms. | `TestInvoiceAPI`: POST creates invoice, posts balanced journal, enqueues async clearance task. |
| **Feature 3.4** | `feat/sprint3-airgapped-pdf-r2-storage` | Build air-gapped invoice PDF generator with ReportLab/WeasyPrint. Implement **Misuse Case 4.1** (SSRF Prevention): explicitly configure `disabled_url_fetcher` to block outbound image/URL calls. Configure Cloudflare R2 upload with `MockR2Storage` fallback. | `TestInvoicePDFSecurity`: Injecting `<img src='http://169.254.169.254'>` raises `PermissionError` without outbound call. |

---

## 9. Sprint 4: Payment Webhook Rails, Suspense Reconciliation & GRA Clearance

**Sprint Objective:** Implement Mobile Money webhooks, Redis idempotency mutexes, automated Luhn reconciliation defending against underpayments (**MUC 1.1**) and forged HMACs (**MUC 1.2**), and asynchronous GRA clearance.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Misuse Tests |
| :--- | :--- | :--- | :--- |
| **Feature 4.1** | `feat/sprint4-webhook-hmac-receiver` | Implement `MomoWebhookView` in `apps/payments/views.py`. Implement **Misuse Case 1.2**: verify HMAC-SHA256 signature using constant-time comparison (`hmac.compare_digest`). Reject unverified or tampered payloads with HTTP 401. Build `MockGateway` adapters. | `TestWebhookSecurity`: Valid HMAC passes; tampered payload or missing signature returns 401. |
| **Feature 4.2** | `feat/sprint4-redis-webhook-idempotency` | Implement distributed idempotency lock using Redis (`SET momo:evt:<event_id> EX 60 NX`). Discard duplicate webhooks with immediate HTTP 200 OK without re-posting journal lines. | `TestWebhookIdempotency`: Replaying exact same webhook event twice executes ledger posting exactly once. |
| **Feature 4.3** | `feat/sprint4-momo-reconciliation-suspense` | Build `ReconciliationService`. Implement **Misuse Case 1.1** (Underpayment Defense): assert `amount_paid == invoice.total_amount` before marking `PAID`; route partial payments to `PARTIALLY_PAID`. Route unresolvable deposits to Suspense Account 2150 with owner alert. | `TestReconciliation`: Underpayment does not mark `PAID`; missing ref credits Suspense Account 2150. |
| **Feature 4.4** | `feat/sprint4-gra-evat-async-worker` | Build Celery task `clear_with_gra` in `apps/tax/tasks.py` with exponential backoff retries. Compile in-memory QR SVG, inject into invoice PDF, PUT to R2, and mark invoice `CLEARED`. Build `MockGraEvatClient`. | `TestGRAWorker`: `MockGraEvatClient` returns SDC ID; invoice transitions to `CLEARED`; QR SVG compiled. |

---

## 10. Sprint 5: Statutory External Audit PBC Package & Segregation of Duties

**Sprint Objective:** Implement time-bound auditor access, one-click PBC audit package export with SHA-256 manifest hashing, and payroll maker-checker 2FA approval defending against self-approval (**MUC 5.1**) and replay attacks (**MUC 5.2**).

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Misuse Tests |
| :--- | :--- | :--- | :--- |
| **Feature 5.1** | `feat/sprint5-auditor-rbac-sessions` | Enforce read-only access (GET/HEAD only) for Auditor role at API view and ORM levels. Block write operations with HTTP 403. Automatically invalidate sessions when `now() >= access_expires_at`. | `TestAuditorRBAC`: Auditor can read GL/TB; POST `/api/v1/invoices/` returns 403 Forbidden. |
| **Feature 5.2** | `feat/sprint5-pbc-audit-export-worker` | Build Celery task `compile_pbc_package` in `apps/audit/tasks.py`. Stream GL (CSV), Trial Balance (CSV), Act 1151 Tax Returns (CSV), and cleared invoice PDFs into an in-memory ZIP archive. | `TestPBCWorker`: Asynchronous task compiles ZIP containing all required audit workpapers. |
| **Feature 5.3** | `feat/sprint5-audit-hash-presigned-r2` | Implement SHA-256 cryptographic digest calculation over PBC ZIP. Store immutable record in `AuditTrail` model. Upload archive to R2 and generate 24-hour presigned download link. | `TestAuditTrail`: SHA-256 checksum recorded; presigned URL generated; audit log is immutable. |
| **Feature 5.4** | `feat/sprint5-payroll-maker-checker-2fa` | Implement `PayrollRun` in `apps/payroll`. Calculate PAYE and SSNIT (5.5% employee, 13% employer). Implement **Misuse Case 5.1**: enforce `maker_id != checker_id`. Implement **Misuse Case 5.2**: single-use TOTP consumption cache in Redis (60s TTL) plus distributed lock on `payroll_id` during approval. | `TestPayrollSecurity`: Maker attempting approval gets 403; TOTP replay within 30s is rejected. |

---

## 11. Enhanced Definition of Done (DoD) with Security Gates

Before requesting user review and pushing any feature branch, the developer or AI agent must verify that the feature satisfies all six criteria of the Definition of Done:

1. **Complete Implementation:** All models, services, views, and adapters defined in the feature scope are fully written and free of placeholders or mock stubs in production paths.
2. **100% Functional Test Pass Rate:** All automated unit and integration tests run green against in-memory SQLite (`python manage.py test apps.<app_name>`) in under 5 seconds.
3. **Automated Misuse/Abuse Test Execution:** All corresponding negative security tests defined for the feature run green (`python manage.py test tests.security`).
4. **Zero Linting & SAST Findings:** `ruff check .`, `ruff format .`, and `bandit -r apps/ config/ -ll -ii` report zero errors or high-severity warnings.
5. **Migration Inspection Completed:** If database models were added or modified, `sqlmigrate` was executed, output was reviewed by the user, and explicit authorization was granted before running `migrate`.
6. **Clean Hand-off:** Git status is clean, feature commit message adheres to Conventional Commits (`feat(<scope>): <description>`), and user pushes branch to GitHub before checking out develop for the next feature.