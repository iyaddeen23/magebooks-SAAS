<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Mage Books SAAS — Autonomous Developer & Agent Playbook

Mage Books is a specialized enterprise accounting, invoicing, and statutory tax clearance platform designed for Ghanaian MSMEs, sole traders, and external Chartered Accountants.

---

## 1. Golden Operational Directives (Strict Rules for Agents)

Every autonomous coding agent working in this repository must strictly adhere to these 7 rules:

1. **Feature-by-Feature Branching, PR Merge Gate & Cleanup Protocol:**
   * Never implement multiple features at once.
   * Never commit directly to `main` or `develop`.
   * **Branch Naming**: Omit sprint prefixes; name branches cleanly: `feat/<feature-name>`.
   * **Human-in-the-Loop Push Gate**: Complete implementation, ensure 100% test pass rates and zero linter warnings, then **halt and present the Git commit and push commands to the user**. Wait for user confirmation that the branch has been pushed and a PR opened.
   * **Mandatory Pre-Feature PR Merge Check & Branch Cleanup**:
     Before moving onto or creating a branch for any new feature, **ALWAYS check if the PR opened for the previous feature has been merged into `develop`**:
     1. If the PR has been merged:
        - Switch to `develop` and pull latest upstream changes:
          ```bash
          git checkout develop
          git pull origin develop
          ```
        - Delete the merged **local branch**:
          ```bash
          git branch -d feat/<previous-feature-name>
          ```
        - Delete the merged **remote branch**:
          ```bash
          git push origin --delete feat/<previous-feature-name>
          ```
     2. If the PR has NOT yet been merged, halt and wait for user confirmation that the PR has been merged into `develop`. Do NOT begin work on the next feature until previous branches are cleaned up and `develop` is up to date.
2. **Human-in-the-Loop Database Migration Gate:**
   * **NEVER automatically run `python manage.py migrate`** against PostgreSQL or production databases.
   * Generate migration files with `makemigrations <app>`, inspect the raw SQL with `sqlmigrate <app> <number>`, display the SQL to the user, and explicitly pause for user authorization before running `migrate`.
3. **Single Unified Configuration (`config/settings.py`):**
   * Do NOT split settings into `base.py`, `local.py`, or `production.py`.
   * Maintain exactly one clean `config/settings.py` file utilizing `django-environ` with explicit type casting and safe fallback defaults.
4. **SQLite In-Memory Testing Isolation:**
   * All automated unit and integration tests must run against SQLite in-memory (`:memory:`), dynamically routed by `IS_TESTING` in `settings.py`.
   * Automated test suites must complete in under 5 seconds. PostgreSQL is reserved strictly for local development and production.
5. **Deterministic Mock Service Adapters:**
   * When integrating external APIs (Paystack, Hubtel, GRA E-VAT, Cloudflare R2), prompt the user for live credentials.
   * Concurrently, always maintain and use deterministic Mock Service Adapters (`MockPaystackGateway`, `MockHubtelGateway`, `MockGraEvatClient`, `MockR2Storage`) so tests and local builds never depend on external network availability.
6. **Modern Tooling & Virtual Environment Execution via `uv` and `ruff`:**
   * **Strict Virtual Environment Execution**: NEVER run `python` or `manage.py` directly using system/global Python. Always execute all backend scripts, management commands, and test runners through `uv run` (e.g. `uv run python manage.py <command>`) or from within the active virtual environment (`.venv`). Running with global Python will trigger `ModuleNotFoundError` for project dependencies.
   * Use `uv` (`uv init`, `uv add`, `uv run`, `uv sync`) for all Python package management.
   * Enforce linting and formatting via `uv run ruff check .` and `uv run ruff format .` prior to every commit.
7. **Exhaustive Documentation Review & Future-Proofing Analysis in Implementation Plans:**
   * **Zero Missed Context**: Before drafting an implementation plan or writing code for any new task or feature, the agent MUST thoroughly examine all specification files in `docs/` (`DETAILED_DOCUMENTATION.md`, `Architecture Manual`, `Master 5-Sprint Implementation Plan`, `Sequence Diagrams & Lifecycle Specification`, `OVERVIEW.md`, etc.). The agent must ensure no detail, statutory requirement, accounting rule, or database constraint is overlooked.
   * **Forward-Looking Impact & Breakage Analysis**: The agent MUST actively inspect upcoming sprint features and downstream integrations (e.g., Invoicing, Mobile Money webhooks, GRA E-VAT clearance, General Ledger balancing, Audit/PBC package generation, multi-currency, and RBAC) to verify that current implementations will not break future systems or create technical debt.
   * **Mandatory Plan & Approval Gate**: The implementation plan must document this future-proofing analysis (highlighting potential future breakage points and concrete architectural safeguards) and be presented in `implementation_plan.md` with proposed solutions or options for explicit user approval before modifying code.

---

## 2. Technical Stack & Repository Structure

### Tech Stack Overview
* **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS v4, `ModeContext` (Simple vs. Professional Mode), Lucide & Phosphor icons.
* **Backend:** Python 3.12 (or 3.14), Django 5.1+, Django REST Framework, PostgreSQL with Row-Level Security (RLS), Redis, Celery.
* **Storage & Infrastructure:** Cloudflare R2 (S3-compatible, zero egress), Docker, Render/Cloud Run.
* **Statutory Standards:** Ghana Value Added Tax Act, 2025 (Act 1151) & GRA E-VAT clearance.

### Target Directory Layout
```text
├── apps/
│   ├── core/           # BaseTenantModel (UUIDv7), PublicShareableMixin (UUIDv4)
│   ├── authentication/ # CustomUser model, HttpOnly JWT session cookies
│   ├── tenancy/        # Organization, OrganizationMembership, TenantSecurityMiddleware
│   ├── ledger/         # FiscalCalendar, ChartOfAccounts (1000-5999), JournalEntry, JournalLine
│   ├── tax/            # Act 1151 TaxCalculationEngine (15% VAT, 2.5% NHIL, 2.5% GETFund), GRA tasks
│   ├── invoicing/      # Invoice, Customer Snapshots, Luhn sequence generator, Air-gapped PDF
│   ├── payments/       # MomoWebhookView, HMAC verification, Redis idempotency, Suspense 2150
│   ├── payroll/        # PayrollRun, Maker-Checker segregation, Tier 1/2 SSNIT, PAYE, TOTP 2FA
│   └── audit/          # Auditor read-only permissions, PBC package compiler, SHA-256 manifest
├── config/
│   ├── __init__.py
│   ├── asgi.py
│   ├── celery.py
│   ├── settings.py     # Single unified django-environ settings
│   ├── urls.py
│   └── wsgi.py
├── pyproject.toml      # uv & ruff configuration
└── .env.example        # Reference environment variables