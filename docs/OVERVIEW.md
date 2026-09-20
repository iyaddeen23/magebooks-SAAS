# Mage Books SAAS — High-Level Project Overview

> **A Cloud Accounting Platform Engineered Specifically for Ghanaian Businesses & Accounting Professionals**

---

## 1. Executive Summary

**Mage Books** is a multi-tenant Software-as-a-Service (SaaS) accounting platform purpose-built to solve the acute bookkeeping, tax compliance, and financial management challenges faced by businesses in Ghana. 

While generic international accounting software (such as QuickBooks, Xero, or FreshBooks) assumes Western tax structures and requires deep accounting knowledge, Mage Books is designed with **two distinct user experiences**:
1. **Simple Mode ("Keep it simple")**: Tailored for Ghanaian shop owners, traders, service providers, and non-accountant entrepreneurs. Complex double-entry bookkeeping (debits and credits) is automated completely in the background, presenting clean, jargon-free workflows ("Money I Owe", "Money Owed to Me", "Staff Pay", "Fix a Past Mistake").
2. **Professional Mode ("I know accounting")**: Built for Chartered Accountants, CFOs, external auditors, and finance teams. Unlocks full access to general ledgers, manual journal entries, customizable Ghanaian Chart of Accounts, fixed asset registers, prior-period adjustments, and audit trails.

Furthermore, Mage Books natively embeds **Ghanaian statutory requirements** from day one—including Ghana Revenue Authority (GRA) Taxpayer Identification Numbers (TIN), the national Ghana Card ID system, and the multi-tier Ghanaian Value Added Tax (VAT), National Health Insurance Levy (NHIL), Ghana Education Trust Fund (GETFund), and COVID-19 Health Recovery Levy.

---

## 2. Target Market & The Problem Solved

### The Problem
- **Fragmented Spreadsheets & Paper Ledgers**: The vast majority of Ghanaian Small and Medium Enterprises (SMEs) track sales, inventory, and expenses using physical exercise books or disjointed Excel files.
- **Complex Statutory Tax Compliance**: Calculating Ghanaian VAT is notoriously error-prone due to compounding levies (NHIL 2.5%, GETFund 2.5%, COVID-19 1%, and VAT 15%) and the distinction between Standard and Flat Rate schemes. Non-compliance results in severe GRA penalties.
- **Payment Disconnect**: International platforms lack direct integration with Ghana's dominant payment channels: **Mobile Money (MTN MoMo, Telecel Cash, AT Money)** and **local Bank Point-of-Sale (POS) settlement systems**.
- **The Accounting Knowledge Barrier**: Small business owners avoid software that requires them to understand debits, credits, and ledger balancing.

### The Mage Books Solution
- **Zero-Friction Dual Experience**: Start simple without knowing accounting; transition to professional mode anytime without data loss.
- **Automated GRA Tax Engine**: Built-in calculations for VAT, levies, withholding taxes (WHT), and PAYE/SSNIT payroll deductions.
- **Local Payment Rails**: Designed to ingest transactions from Mobile Money, bank POS terminals, bank transfers, and cash receipts.
- **On-Demand Certified Accountants**: Built-in "Hire An Expert" marketplace allowing businesses to outsource bookkeeping, audits, and GRA tax filing to certified Ghanaian accountants directly within the app.

---

## 3. Core Architectural Concept: Dual-Experience Modes

Mage Books bridges the gap between the business owner and their accountant through an instant runtime mode switch:

```mermaid
graph TD
    User([User selects experience]) -->|Toggle in Navigation| ModeSwitch{Active Mode}
    
    ModeSwitch -->|Simple Mode| SimpleView[Plain-English UI]
    SimpleView --> S1["'Money Owed to Me' (Receivables)"]
    SimpleView --> S2["'Money I Owe' (Payables)"]
    SimpleView --> S3["'What I Own / My Share' (Assets/Equity)"]
    SimpleView --> S4["'Staff Pay' (Payroll)"]
    SimpleView --> S5["'Fix a Past Mistake' (Rectifications)"]
    
    ModeSwitch -->|Professional Mode| FullView[Standard Accounting UI]
    FullView --> F1["Accounts Receivable & Aging"]
    FullView --> F2["Accounts Payable & Vouchers"]
    FullView --> F3["Chart of Accounts & General Ledgers"]
    FullView --> F4["Formal Payroll & Statutory PAYE/SSNIT"]
    FullView --> F5["Prior Period Adjustments & Audit Trail"]
    
    S1 -.->|Automated in Background| CoreLedger[(Double-Entry Financial Engine)]
    F1 --> CoreLedger
    S2 -.->|Automated in Background| CoreLedger
    F2 --> CoreLedger
```

- In **Simple Mode**, users never see debit or credit inputs. The application translates intuitive business events (e.g., "Customer bought goods on credit") into balanced double-entry ledger transactions behind the scenes.
- In **Professional Mode**, the full chart of accounts, journal entry creation, ledger reconciliations, and trial balance reports are exposed.
- All underlying data is unified: switching modes does not alter or corrupt historical data.

---

## 4. Current Technology Stack

| Layer | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Framework** | Next.js (App Router) | 16.3.0 | Modern server/client hybrid React framework |
| **Library** | React | 19.2.8 | UI component library with concurrent features |
| **Language** | TypeScript | 5.x | Strict type safety across the entire codebase |
| **Styling** | Tailwind CSS (via PostCSS) | 4.x | Utility-first styling using inline theme variables |
| **Typography** | Inter (Google Fonts) | Next Font | Optimized primary typeface |
| **Icons & Assets** | Figma Vector SVGs & PNGs | Custom | 69 bespoke assets for metrics, navigation, and logos |
| **State Context** | React Context (`ModeContext`) | Native | Local state and `localStorage` persistence for mode |

---

## 5. High-Level System Architecture

```mermaid
flowchart TB
    subgraph Client["Frontend Application (Next.js 16)"]
        Splash["Splash / Loading Screen (/)"]
        AuthModule["Authentication ((auth)/login, signup)"]
        OnboardingModule["6-Step Onboarding ((onboarding)/onboarding)"]
        DashboardLayout["Dashboard Shell & Layout ((dashboard)/layout)"]
        SideNav["Dynamic SideNavBar (Simple vs Professional)"]
        TopNav["TopNavBar (Search, Alerts, Profile)"]
        DashboardPages["18 Business & Accounting Modules"]
    end

    subgraph FutureBackend["Target Backend Architecture (To Be Implemented)"]
        Gateway["API Gateway / Middleware (Auth, Tenant Context)"]
        AuthService["Auth & RBAC Service (JWT, Multi-Factor)"]
        LedgerEngine["Double-Entry Accounting Core"]
        TaxEngine["Ghana Tax Engine (GRA, VAT, Levies, WHT)"]
        PayrollEngine["Ghana Payroll Engine (PAYE, SSNIT)"]
        Integrations["Payment & Banking Gateway Integrations"]
    end

    subgraph DataStore["Data Storage & External Services"]
        DB[(Primary Relational DB - PostgreSQL)]
        Cache[(Redis Cache & Task Queue)]
        MoMo["Mobile Money APIs (MTN, Telecel, AT)"]
        BankPOS["Bank POS & Settlement Feeds"]
        GRA["GRA E-VAT Integration"]
    end

    Client -->|REST / GraphQL Requests| Gateway
    Gateway --> AuthService
    Gateway --> LedgerEngine
    Gateway --> TaxEngine
    Gateway --> PayrollEngine
    Gateway --> Integrations
    
    LedgerEngine --> DB
    Integrations --> MoMo
    Integrations --> BankPOS
    TaxEngine --> GRA
    AuthService --> DB
    LedgerEngine --> Cache
```

---

## 6. Functional Module Directory

The frontend is organized into distinct user journeys:

### 1. Splash & Authentication
- **`/`**: Branded splash loading screen highlighting *"Welcome to Mage Accounting Software — Built for Ghanaian Businesses"* with a 2.8-second progress animation that routes users to login.
- **`/login`**: Secure login supporting email or Ghanaian telephone numbers.
- **`/signup`**: User registration with password confirmation leading directly into the onboarding wizard.

### 2. The 6-Step Onboarding Wizard (`/onboarding`)
A structured multi-step flow that collects all legal, fiscal, and operational parameters necessary to instantiate a Ghanaian business account:
1. **Step 1: Company Details**: Business name, Ghana TIN, Ghana Card ID (`GHA-XXXXXXXXX-X`), physical address, Ghanaian telephone (`+233`), and business email.
2. **Step 2: VAT Status**: GRA VAT registration status with contextual guidance on the GHS 200,000 threshold.
3. **Step 3: Choose Experience**: Explicit choice between "Keep it simple" and "I know accounting".
4. **Step 4: Fiscal Calendar**: Period length (Monthly, Quarterly, Annually) and an interactive calendar to define the fiscal year-end date.
5. **Step 5: Chart of Accounts**: Selection between a standard Ghanaian SME template or custom CSV/Excel upload.
6. **Step 6: Contacts**: Initial customer and supplier capture with tax identification.

### 3. Dashboard & Operations (`/dashboard`)
Comprises 18 integrated business sections:
1. **Main Dashboard**: High-level financial KPIs (Payables, Receivables, Petty Cash, Tax Liabilities), 7-month cash snapshot bar chart, and recent activity feed.
2. **Transactions / Transaction Entries**: Complete ledger of all monetary movements and double-entry journals.
3. **Chart of Accounts / My Categories**: Structured view of Assets, Liabilities, Equity, Revenue, and Expenses.
4. **Ledgers**: Account-by-account postings and balances (Professional Mode).
5. **Receipts**: Inbound payment receipts and document attachments.
6. **Payments**: Outgoing disbursement records.
7. **Accounts Receivable / Money Owed to Me**: Customer invoices, aging, and overdue tracking.
8. **Accounts Payable / Money I Owe**: Supplier bills and due dates.
9. **Reports**: Core financial statements (P&L, Balance Sheet, Cash Flow, Tax Summary, Aged Balances).
10. **Customers & Suppliers (Contacts)**: CRM directory with Ghanaian TIN and phone contact details.
11. **Payroll / Staff Pay**: Employee compensation, PAYE tax computation, and SSNIT contributions.
12. **Fixed Asset Register / Equipment & Property**: Asset registry, depreciation schedules, and disposals.
13. **Inventory Management**: Stock catalog, valuations, and SKU tracking.
14. **Users & Access**: Team collaboration and role-based permissions.
15. **Hire An Expert**: Marketplace connecting users with certified Mage accountants for tax filing, audits, and bookkeeping.
16. **Activity Log / Audit Trail**: Immutable record of all system events.
17. **Security Log**: Audit of logins, device fingerprints, and IP addresses.
18. **Prior Period Rectification / Fix a Past Mistake**: Compliant adjustment workflows for closed financial periods.
19. **Setup & Settings**: Company profile, tax parameters, currencies, and integrations.

---

## 7. Next Phase: Backend Development

Currently, Mage Books has a responsive, clean, and complete frontend UI shell with mock state. The critical next phase is **building the production backend** to provide:
- True multi-tenant isolation and secure authentication.
- A hardened double-entry relational database engine (PostgreSQL).
- Automatic calculation of complex Ghanaian taxes (GRA VAT, NHIL, GETFund, COVID-19 Levy, WHT, PAYE).
- Real-time integrations with Ghanaian Mobile Money, Bank POS systems, and card processors.

*For complete technical specifications, full database schemas, API endpoint listings, and historical logs, consult [`DETAILED_DOCUMENTATION.md`](file:///M:/CODES/Work/magebooks-SAAS/DETAILED_DOCUMENTATION.md).*
