<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Mage Books SAAS — Autonomous Developer & Agent Playbook

See [`backend/AGENTS.md`](file:///m:/CODES/Work/magebooks-SAAS/backend/AGENTS.md) for full operational directives.

## Mandatory Implementation Planning Directive
Whenever an agent starts a new task or feature:
1. **Exhaustive Document Review (Zero Missed Context):**
   The agent MUST thoroughly examine all specification files in `docs/` (`DETAILED_DOCUMENTATION.md`, `Architecture Manual`, `Master 5-Sprint Implementation Plan`, `Sequence Diagrams & Lifecycle Specification`, `OVERVIEW.md`, etc.). Ensure no detail, statutory requirement, accounting invariant, or database constraint is missed.
2. **Forward-Looking Impact & Breakage Analysis:**
   The agent MUST actively inspect upcoming sprint features and downstream integrations (e.g., Invoicing, Mobile Money webhooks, GRA E-VAT clearance, General Ledger balancing, Audit/PBC exports, multi-currency, and RBAC) to verify that current implementations will not break future systems or create technical debt.
3. **Mandatory Implementation Plan & Approval Gate:**
   The implementation plan must document this future-proofing analysis (highlighting potential future breakage points and concrete architectural safeguards) and be presented in `implementation_plan.md` for explicit user approval before modifying code.

