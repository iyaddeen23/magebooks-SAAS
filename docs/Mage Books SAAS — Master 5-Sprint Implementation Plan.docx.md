**MAGE BOOKS SAAS**

**Master 5-Sprint Implementation Plan & Feature Playbook**

*Autonomous Developer & AI Agent Execution Manual:*  
*Feature-by-Feature Branching, Single django-environ Configuration, and SQLite Testing Protocol*

**Author & Engineering Lead:** Marcel Yeboah  
**Target System:** Mage Books SAAS (Ghana Enterprise Accounting Platform)  
**Version:** 2.0.0 (Feature-Driven Engineering Edition)  
**Execution Protocol:** Feature Branching, In-Memory Testing & Human-in-the-Loop Push Gate  
**Date:** September 2026

**1\. Critical Operational Directives for Developers & AI Agents**

To ensure disciplined code execution, strict ledger integrity, and zero regressions across the 5 sprints, every human developer and autonomous AI agent (including Antigravity) must strictly adhere to the following six engineering mandates:

1\. Feature-by-Feature Implementation, PR Merge Gate & Branch Cleanup Protocol: Development must proceed strictly feature by feature. Developers and agents must never implement multiple features at once or commit directly to the main or develop branches. For each feature, create a dedicated branch without sprint prefixes ('feat/\<feature-name\>'). Before starting any new feature, the agent must ALWAYS check whether the PR for the previous feature has been merged into 'develop'. If merged, delete both the local branch and the remote branch, pull the latest 'develop', and only then create the next feature branch.

2\. Human-in-the-Loop Migration Authorization: Autonomous agents are strictly forbidden from automatically executing 'python manage.py migrate' against development or production PostgreSQL databases. The agent must generate migration scripts using 'makemigrations', inspect the generated SQL using 'sqlmigrate \<app\> \<migration\_number\>', output the SQL inspection to the user, and explicitly pause to ask for confirmation before applying any changes.

3\. External APIs & Live Credentials Gate: When external credentials or endpoints are required (Paystack Live Secret Key, Hubtel Client Credentials, GRA E-VAT Clearance API Keys, or Cloudflare R2 Access Tokens), the agent must prompt the user for them. Concurrently, the codebase must maintain deterministic Mock Service Adapters (e.g., MockPaystackGateway, MockGraEvatClient, MockR2Storage) so that the entire test suite and local development can run offline without live credentials.

4\. Single Unified Configuration via django-environ: Do not split Django settings into base.py, local.py, or production.py. Maintain exactly ONE clean 'config/settings.py' file utilizing 'django-environ' with explicit type casting and safe development fallbacks. The .env file must be discovered gracefully from BASE\_DIR without crashing when deployed to containerized environments where environment variables are injected at runtime.

5\. Isolated Testing Protocol with SQLite: All automated unit and integration tests must run against SQLite in-memory (:memory:), dynamically selected by the test runner in config/settings.py. PostgreSQL is reserved strictly for development and production workloads. Automated tests must execute in under 5 seconds.

6\. Modern Python Tooling & Strict Virtual Environment Execution via uv and ruff: All package installation, environment locking, and script execution must be performed using 'uv' ('uv add', 'uv run', 'uv sync'). Developers and agents must NEVER invoke global/system Python directly. All commands must be run via 'uv run' (e.g. 'uv run python manage.py ...') or within the active virtual environment ('.venv') to prevent 'ModuleNotFoundError' on installed packages. Formatting and linting must be strictly verified using 'ruff' ('ruff check .', 'ruff format .') before any feature hand-off.

**2\. Project Tooling, Environment & Single Settings Configuration**

The backend standardizes on Python 3.12 (or 3.14), uv, and ruff. The entire runtime configuration is managed through a single 'config/settings.py' file utilizing 'django-environ'. This eliminates environment drift while providing rock-solid type casting and graceful .env fallback:

| \# config/settings.py from pathlib import Path import sys import environ  \# Build paths inside the project like this: BASE\_DIR / 'subdir'. BASE\_DIR \= Path(\_\_file\_\_).resolve().parent.parent  \# 1\. Initialize environ with explicit type casting and safe fallback defaults env \= environ.Env(     DJANGO\_DEBUG=(bool, False),     DJANGO\_SECRET\_KEY=(str, "django-insecure-magebooks-dev-key"),     DJANGO\_ALLOWED\_HOSTS=(list, \["\*"\]),     DJANGO\_CORS\_ALLOWED\_ORIGINS=(list, \["http://localhost:3000"\]), )  \# 2\. Read .env file from BASE\_DIR (if present) \# Does not fail if .env is missing (e.g. in containerized production environments) environ.Env.read\_env(BASE\_DIR / ".env")  \# 3\. Pull variables (automatically type-cast by environ) SECRET\_KEY \= env("DJANGO\_SECRET\_KEY") DEBUG \= env("DJANGO\_DEBUG") ALLOWED\_HOSTS \= env("DJANGO\_ALLOWED\_HOSTS")  INSTALLED\_APPS \= \[     "django.contrib.admin",     "django.contrib.auth",     "django.contrib.contenttypes",     "django.contrib.sessions",     "django.contrib.messages",     "django.contrib.staticfiles",     \# Third-party extensions     "rest\_framework",     "corsheaders",     "storages",     \# Core Domain Apps     "apps.core",     "apps.authentication",     "apps.tenancy",     "apps.ledger",     "apps.tax",     "apps.invoicing",     "apps.payments",     "apps.payroll",     "apps.audit", \]  \# Database Routing: In-Memory SQLite for Automated Tests, PostgreSQL for Dev/Prod IS\_TESTING \= "test" in sys.argv or "pytest" in sys.modules  if IS\_TESTING:     DATABASES \= {         "default": {             "ENGINE": "django.db.backends.sqlite3",             "NAME": ":memory:",         }     } else:     DATABASES \= {         "default": env.db("DATABASE\_URL", default="postgres://postgres:postgres@localhost:5432/magebooks\_db")     }  \# Cloudflare R2 Object Storage (S3-Compatible) CLOUDFLARE\_R2\_ACCESS\_KEY\_ID \= env("R2\_ACCESS\_KEY\_ID", default="") CLOUDFLARE\_R2\_SECRET\_ACCESS\_KEY \= env("R2\_SECRET\_ACCESS\_KEY", default="") CLOUDFLARE\_R2\_BUCKET\_NAME \= env("R2\_BUCKET\_NAME", default="magebooks-prod") CLOUDFLARE\_R2\_ENDPOINT\_URL \= env("R2\_ENDPOINT\_URL", default="") |
| :---- |

&nbsp;

**3\. Feature-by-Feature Git Lifecycle & Hand-off Protocol**

To ensure complete transparency and code review between the autonomous agent and the project owner, every single feature follows a strict execution loop:

**Phase 0: Pre-Feature PR Merge Verification & Branch Cleanup Gate**

Before writing a single line of code or creating a new feature branch, the agent must ALWAYS check whether the PR for the previous feature has been merged into 'develop':
1. If the previous PR is merged:
   - Switch to 'develop' and pull latest upstream commits:
     `git checkout develop && git pull origin develop`
   - Delete the merged local branch:
     `git branch -d feat/<previous-feature-name>`
   - Delete the merged remote branch:
     `git push origin --delete feat/<previous-feature-name>`
2. If the previous PR is NOT yet merged:
   - The agent must halt and wait for the user to confirm that the PR has been reviewed and merged into 'develop'.

**Phase A: Feature Branch Creation**

Once 'develop' is fully updated and old branches are cleaned up, verify that the working tree is clean and create the new feature branch:

| git checkout -b feat/\<feature-name\> |
| :---- |

&nbsp;

**Phase B: Test-Driven Implementation & SQLite Verification**

Implement the feature's models, services, views, and unit tests. Run linting and automated tests against the in-memory SQLite runner using 'uv run' to guarantee 100% test pass rates:

| \# Run fast linting and formatting checks uv run ruff check . uv run ruff format .  \# Execute isolated in-memory SQLite test suite uv run python manage.py test apps.\<app\_name\> |
| :---- |

&nbsp;

**Phase C: Migration Inspection (If Schema Modified)**

If the feature introduces or mutates database models, generate the migration and inspect the raw SQL. The agent must output this SQL to the user and request approval before proceeding:

| uv run python manage.py makemigrations \<app\_name\> uv run python manage.py sqlmigrate \<app\_name\> \<migration\_number\> \# \[PAUSE\]: Prompt user for confirmation before running 'migrate'. |
| :---- |

&nbsp;

**Phase D: Hand-off, Review & User Push Gate**

Once tests pass, the agent halts and presents the exact git command sequence to the user. The user reviews the git diff and pushes the branch to GitHub:

| git status git add . git commit \-m "feat(\<scope\>): implement \<feature description\>" git push \-u origin feat/\<feature-name\> |
| :---- |

&nbsp;

The agent waits for the user to confirm that the branch has been pushed and the pull request opened. The agent then loops back to **Phase 0** before starting the next feature.

**4\. Sprint 1: Core Foundation, Multi-Tenancy & Dual-UUID Engine**

Sprint Objective: Establish project tooling with uv, single django-environ configuration, JWT authentication, 5-stage TenantSecurityMiddleware, and Dual-UUID base models across 5 discrete feature branches.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Test Suite |
| :---- | :---- | :---- | :---- |
| **Feature 1.1** | feat/sprint1-tooling-environ-settings | Initialize project with 'uv init', configure pyproject.toml with ruff, install dependencies (django-environ, uuid6, psycopg, djangorestframework), create single config/settings.py, and verify SQLite test runner. | uv run python manage.py test core (Test runner boots in \<1s) |
| **Feature 1.2** | feat/sprint1-auth-jwt-sessions | Implement CustomUser model, CustomUserManager, and JWT login/logout/refresh endpoints setting HttpOnly, Secure, SameSite=Strict session cookies. | TestJWTAuth: Login returns 200 with HttpOnly cookies; unauthenticated requests return 401\. |
| **Feature 1.3** | feat/sprint1-tenancy-rbac-models | Implement Organization and OrganizationMembership models in apps/tenancy with 5 RBAC roles (OWNER, ADMIN, ACCOUNTANT, BOOKKEEPER, AUDITOR) and auditor access\_expires\_at. | TestTenancyModels: User assigned roles; membership queries scoped correctly. |
| **Feature 1.4** | feat/sprint1-tenant-security-middleware | Build TenantSecurityMiddleware executing the 5-stage guard sequence: JWT validation \-\> Tenant header check \-\> Active membership verification \-\> Auditor expiry check \-\> PostgreSQL RLS session binding. | TestTenantSecurityMiddleware: Spoofed X-Tenant-ID returns 403; expired auditor returns 403\. |
| **Feature 1.5** | feat/sprint1-dual-uuid-base-models | Implement BaseTenantModel with uuid6.uuid7 internal primary key and PublicShareableMixin with uuid4 share\_token in apps/core. Establish migration inspection protocol. | TestDualUUID: Assert id is UUIDv7 (timestamp ordered) and share\_token is UUIDv4. |

&nbsp;

**5\. Sprint 2: Double-Entry Ledger Core & 2026 Ghanaian Statutory Tax Engine (Act 1151\)**

Sprint Objective: Implement append-only double-entry general ledger journals, sub-5ms dynamic balance calculations, and the 2026 Act 1151 unified 20.0% tax engine across 4 discrete feature branches.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Test Suite |
| :---- | :---- | :---- | :---- |
| **Feature 2.1** | feat/sprint2-chart-of-accounts-calendar | Implement FiscalCalendar, FiscalPeriod, and ChartOfAccounts models with clean 4-digit hierarchy (1000-5999) and Ghanaian standard initial seed fixture. | TestChartOfAccounts: Seed loads 4-digit accounts; validates account categories. |
| **Feature 2.2** | feat/sprint2-double-entry-ledger-engine | Implement JournalEntry and JournalLine models with check\_positive\_values and check\_either\_debit\_or\_credit constraints. Implement LedgerService.post\_journal\_entry() enforcing Sum(Debits) \== Sum(Credits) and deterministic ORDER BY id lock ordering. | TestLedgerEngine: Unbalanced entry raises ValidationError; balanced entry commits successfully. |
| **Feature 2.3** | feat/sprint2-act1151-tax-engine | Implement TaxCalculationEngine in apps/tax/services.py enforcing Act 1151: 15% VAT, 2.5% NHIL, 2.5% GETFund (unified 20% non-cascading rate). COVID levy completely abolished. Arbitrary-precision Decimal math. | TestAct1151TaxEngine: GHS 1000 base yields exactly GHS 150 VAT, GHS 25 NHIL, GHS 25 GETFund. |
| **Feature 2.4** | feat/sprint2-dynamic-balance-selectors | Build optimized SQL balance selectors in apps/ledger/selectors.py computing real-time Trial Balance, Profit & Loss, and Balance Sheet via single SQL aggregates without locking account records. | TestDynamicBalances: Sub-5ms calculation over 10,000 synthetic journal lines in SQLite. |

&nbsp;

**6\. Sprint 3: Invoicing, Luhn Sequence References & Air-Gapped PDF Generation**

Sprint Objective: Implement B2B/B2C invoice compilation, customer point-in-time snapshots, self-validating Luhn sequence codes, and air-gapped PDF generation to Cloudflare R2 across 4 discrete feature branches.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Test Suite |
| :---- | :---- | :---- | :---- |
| **Feature 3.1** | feat/sprint3-invoicing-models-snapshots | Implement Invoice and InvoiceLine models in apps/invoicing. Store immutable point-in-time customer legal snapshot (legal name, TIN/Ghana Card PIN, address) directly on invoice record. | TestInvoiceSnapshot: Updating customer profile after invoice issuance leaves invoice snapshot untouched. |
| **Feature 3.2** | feat/sprint3-luhn-reference-generator | Implement self-validating sequence code generator with Luhn check-digit (e.g., '84291-6') and Ghana Card / TIN regex pre-validators in apps/invoicing/utils.py. | TestLuhnGenerator: Validates correct Luhn check digits; detects transpositions in O(1). |
| **Feature 3.3** | feat/sprint3-invoicing-api-ledger-posting | Build InvoiceCreateAPIView with atomic posting to LedgerService (Dr 1200 AR, Cr 4000 Revenue, Cr 2100/2110/2120 Taxes). Commits locally as 'PENDING\_GRA' and returns HTTP 201 in \<150ms. | TestInvoiceAPI: POST creates invoice, posts balanced journal, enqueues async clearance task. |
| **Feature 3.4** | feat/sprint3-airgapped-pdf-r2-storage | Build air-gapped invoice PDF generator with ReportLab/WeasyPrint (no outbound network calls). Configure Cloudflare R2 upload via S3Boto3Storage and create MockR2Storage adapter. | TestInvoicePDF: Generates valid PDF in memory; MockR2Storage verifies upload and presigned URL. |

&nbsp;

**7\. Sprint 4: Payment Webhook Rails, Suspense Reconciliation & GRA Clearance**

Sprint Objective: Implement Mobile Money webhooks (Hubtel/Paystack), Redis idempotency mutexes, automated Luhn reconciliation into Suspense Account 2150, and asynchronous GRA clearance across 4 discrete feature branches.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Test Suite |
| :---- | :---- | :---- | :---- |
| **Feature 4.1** | feat/sprint4-webhook-hmac-receiver | Implement MomoWebhookView in apps/payments/views.py. Verify HMAC-SHA256 signature using tenant webhook secret. Reject unverified requests with HTTP 401\. Build MockGateway adapters. | TestWebhookSecurity: Valid HMAC passes; tampered payload or missing signature returns 401\. |
| **Feature 4.2** | feat/sprint4-redis-webhook-idempotency | Implement distributed idempotency lock using Redis ('SET momo:evt:\<event\_id\> EX 60 NX'). Discard duplicate webhooks with immediate HTTP 200 OK without re-posting journal lines. | TestWebhookIdempotency: Replaying exact same webhook event twice executes ledger posting exactly once. |
| **Feature 4.3** | feat/sprint4-momo-reconciliation-suspense | Build ReconciliationService: Match valid Luhn references to open invoices in O(1) and mark PAID. Route unresolvable or corrupted deposits to Suspense Account 2150 with automated owner alert. | TestReconciliation: Matched ref settles AR; missing ref credits Suspense Account 2150\. |
| **Feature 4.4** | feat/sprint4-gra-evat-async-worker | Build Celery task 'clear\_with\_gra' in apps/tax/tasks.py with exponential backoff retries. Compile in-memory QR SVG, inject into invoice PDF, PUT to R2, and mark invoice CLEARED. Build MockGraEvatClient. | TestGRAWorker: MockGraEvatClient returns SDC ID; invoice transitions to CLEARED; QR SVG compiled. |

&nbsp;

**8\. Sprint 5: Statutory External Audit PBC Package & Segregation of Duties**

Sprint Objective: Implement time-bound auditor access, one-click PBC audit package export with SHA-256 manifest hashing, and payroll maker-checker 2FA approval across 4 discrete feature branches.

| Feature ID | Git Branch | Deliverables & Implementation Scope | Verification & Test Suite |
| :---- | :---- | :---- | :---- |
| **Feature 5.1** | feat/sprint5-auditor-rbac-sessions | Enforce read-only access (GET/HEAD only) for Auditor role at API view and ORM levels. Block write operations with HTTP 403\. Automatically invalidate sessions when now() \>= access\_expires\_at. | TestAuditorRBAC: Auditor can read GL/TB; POST /api/v1/invoices/ returns 403 Forbidden. |
| **Feature 5.2** | feat/sprint5-pbc-audit-export-worker | Build Celery task 'compile\_pbc\_package' in apps/audit/tasks.py. Stream GL (CSV), Trial Balance (CSV), Act 1151 Tax Returns (CSV), and cleared invoice PDFs into an in-memory ZIP archive. | TestPBCWorker: Asynchronous task compiles ZIP containing all required audit workpapers. |
| **Feature 5.3** | feat/sprint5-audit-hash-presigned-r2 | Implement SHA-256 cryptographic digest calculation over PBC ZIP. Store immutable record in AuditTrail model. Upload archive to R2 and generate 24-hour presigned download link. | TestAuditTrail: SHA-256 checksum recorded; presigned URL generated; audit log is immutable. |
| **Feature 5.4** | feat/sprint5-payroll-maker-checker-2fa | Implement PayrollRun and PayrollLine models in apps/payroll. Calculate PAYE and SSNIT (5.5% employee, 13% employer). Enforce maker\_id \!= checker\_id. Require TOTP 2FA before double-entry posting and bulk disbursal. | TestPayrollSegregation: Maker attempting approval gets 403; valid TOTP by checker approves and posts journal. |

&nbsp;

**9\. Definition of Done (DoD) per Feature Branch**

Before requesting user review and pushing any feature branch, the developer or agent must verify that the feature satisfies all five criteria of the Definition of Done:

1\. Complete Implementation: All models, services, views, and adapters defined in the feature scope are fully written and free of placeholders or mock stubs in production paths.

2\. 100% Test Pass Rate: All automated unit and integration tests run green against in-memory SQLite ('python manage.py test apps.\<app\_name\>'). Total test execution time remains under 5 seconds.

3\. Linting & Formatting Compliance: 'ruff check .' and 'ruff format .' report zero errors, warnings, or unformatted files.

4\. Migration Inspection Completed: If database models were added or modified, 'sqlmigrate' was executed, output was reviewed by the user, and explicit authorization was granted before running 'migrate'.

5\. Clean Hand-off: Git status is clean, feature commit message adheres to Conventional Commits ('feat(\<scope\>): \<description\>'), and user pushes branch to GitHub before checking out develop for the next feature.