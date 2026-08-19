# D365 Project Life Cycle Integration Agent

This project automates the end-to-end project setup flow for Microsoft Dynamics 365 Finance and Operations from contract workbook input through validated entity posting, with human approval at each critical stage.

## End-to-End Goal

The goal of this agent is to convert contract-driven project data into reliable D365 project records with full traceability and guardrails.

End-to-end outcomes:

1. Upload a project contract workbook.
2. Extract structured payloads for each business step.
3. Validate and stage payloads for user approval.
4. Post approved records to D365 OData entities in process order.
5. Handle tenant differences with smart fallback and defer behavior.
6. Provide step-level diagnostics for faster issue resolution.
7. Support project closure readiness review and ERP status update planning after lifecycle completion.

## Core Process Steps

The integration flow runs in seven business steps:

1. Reference Data
- Legal entity checks
- Customer lookup and create
- Customer postal address handling with duplicate-skip behavior
- Payment terms and project group checks

2. Project Contract
- Contract header
- Funding source
- Funding rules

3. Project Master
- Parent and child project hierarchy
- Project-level dependencies and checks

4. IFRS 15 Obligations
- Contract line extraction and posting
- Revenue recognition method fields

5. Milestone Billing
- Milestone rows mapped to on-account transactions
- Uses tenant-available Project module entity paths
- Includes diagnostics for permission and validation errors

6. Invoice Schedule
- Invoice proposal related extraction and posting path checks

7. Revenue Recognition
- Revenue recognition schedule extracted for review
- D365 Revenue Recognition automation batch handles revenue recognition based on the schedule
- No separate posting agent is required for this step

Post-completion: Project Closure & ERP Status Update
- Confirm project setup, on-account forecasts, invoice schedule, and D365 revenue recognition batch handoff are complete
- Review open D365 follow-up items and deferred/manual activities
- Prepare ERP project status update from active/in-process to closed where tenant governance permits
- Keep closure/status update separate from invoice posting; no customer invoice is posted by this app

## Architecture

- Backend: FastAPI orchestration and D365 posting logic
- Frontend: Streamlit operator UI for upload, review, approval, and call logs
- Extraction: Pandas/OpenPyXL based workbook parsers
- Posting: Azure AD service principal authentication + D365 OData

## Important Behaviors

- Human-in-the-loop approvals before each posting step.
- Session-based processing with per-step status and call logs.
- Idempotent customer address handling:
  - If the same customer address already exists, skip duplicate creation.
  - If address is new or changed, create new address record.
- Detailed defer/error payloads for blocked tenant fields or permissions.

## Clone, Install, and Run Locally

Use these steps when sharing this project with another developer or operator.

### Prerequisites

- Python 3.11 or newer
- Git
- Access to the target D365 F&O environment
- Azure AD app/service principal with permission to call the D365 OData endpoint
- A project contract workbook in `.xlsx` format

### 1. Clone the repository

```powershell
git clone <repository-url>
cd "Project Life Cycle D365 ERP Integration Agent"
```

Replace `<repository-url>` with the GitHub repository URL.

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example environment file:

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

Update `.env` with the real D365 values:

```env
D365_ENVIRONMENT=your-env
D365_TENANT_ID=your-tenant-id
D365_CLIENT_ID=your-client-id
D365_CLIENT_SECRET=your-client-secret
D365_DATA_AREA_ID=2020
```

Do not commit `.env`. It contains credentials.

If your D365 base URL does not follow the default `https://<D365_ENVIRONMENT>.operations.dynamics.com` pattern, add:

```env
D365_BASE_URL=https://your-environment.operations.dynamics.com
```

### 5. Start the FastAPI backend

Recommended local backend port is `8001` if another app is already using `8000`.

```powershell
uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Backend health check:

```text
http://127.0.0.1:8001/health
```

API docs:

```text
http://127.0.0.1:8001/docs
```

### 6. Start the Streamlit frontend

Open a second terminal, activate the same virtual environment, then run:

Windows PowerShell:

```powershell
$env:D365_AGENT_BACKEND_URL='http://127.0.0.1:8001'
streamlit run frontend/app.py --server.port 8502
```

macOS/Linux:

```bash
export D365_AGENT_BACKEND_URL='http://127.0.0.1:8001'
streamlit run frontend/app.py --server.port 8502
```

Open the app:

```text
http://localhost:8502
```

### 7. Run the workflow

1. Upload the contract workbook.
2. Click Extract & Process.
3. Review each step payload.
4. Approve each step in order.
5. Review D365 call logs and any deferred/manual follow-up messages.

### Optional: quick start scripts

The repository also includes scripts for local startup:

- Windows: `start.bat`
- Unix-like: `start.sh`

Review the ports in those scripts before use. If port `8000` is occupied, prefer the manual commands above with backend `8001` and frontend `8502`.

### Optional: smoke test

After the backend is running on `8001`, run:

```powershell
python -c "import smoke_test_full_api as s; s.BASE_URL='http://127.0.0.1:8001'; raise SystemExit(s.main())"
```

The smoke test uploads a sample workbook, extracts all steps, approves them in order, and prints a final status summary.

## Key Files

- backend/main.py: API endpoints and session flow
- backend/agents/orchestrator.py: session and step orchestration
- backend/agents/d365_agent.py: D365 entity posting plans
- backend/services/excel_extractor.py: workbook extraction logic
- frontend/app.py: Streamlit UI

## Security

- Service principal credentials are read from environment settings.
- Secret and environment files are excluded by .gitignore.
- Keep .env.example as the shareable template.

## Current Operational Note

Depending on tenant configuration, some Project entities may be writable while others are permission-restricted. The agent surfaces these conditions with explicit diagnostics so security/admin updates can be applied quickly.

## Project Closure & ERP Status Update

Project closure is treated as a post-completion control activity after the seven-step lifecycle flow has completed. The current app prepares the data trail and diagnostics needed for closure review; it does not post customer invoices or force-close projects without the required D365 governance.

Recommended closure checklist:

1. Confirm Step 1 through Step 7 are completed or explicitly deferred with accepted business reasons.
2. Confirm parent project and sub-projects exist in D365 and use the correct project contract.
3. Confirm milestone on-account forecasts were created under the correct sub-projects.
4. Confirm Invoice Schedule data was extracted and reviewed; draft invoice proposal creation remains a future/custom D365 service activity where required.
5. Confirm D365 Revenue Recognition automation batch owns the revenue recognition schedule and no separate posting agent is required.
6. Review the final D365 call log for any manual follow-up activity, including the standard copy/manual invoice proposal notes.
7. Validate there are no open project setup exceptions, missing funding rules, missing customer data, or blocked permissions.
8. When business closure is approved, update the ERP project lifecycle/status according to tenant policy.

Suggested ERP status update targets:

- Parent project: move from active/in-process to a closure-ready or closed status when all sub-projects are complete.
- Sub-projects: close each POB-level sub-project after milestones, invoice schedule review, and revenue recognition handoff are complete.
- Project contract: retain active or update to completed/closed only when contract governance, billing, revenue recognition, and audit requirements are satisfied.

Future automation option:

- Add a custom D365 service/action such as `updateProjectClosureStatus`.
- The action should validate open transactions, forecasts, invoice proposal state, and revenue recognition/batch status before changing the project stage/status.
- The action should return a clear success/failure response and should not bypass D365 workflow, audit, or financial controls.

Suggested request shape:

```json
{
  "dataAreaId": "2020",
  "projectContractId": "PC-000037",
  "parentProjectId": "PROJ-000036",
  "subProjectIds": [
    "PROJ-000036-01",
    "PROJ-000036-02"
  ],
  "targetProjectStatus": "Closed",
  "closureDate": "2026-05-31",
  "closureReason": "Contract lifecycle completed and revenue recognition handed off to D365 automation batch"
}
```

Suggested response shape:

```json
{
  "success": true,
  "message": "Project closure status updated successfully.",
  "updatedProjects": [
    "PROJ-000036",
    "PROJ-000036-01",
    "PROJ-000036-02"
  ]
}
```

## Future Enhancement: Draft Project Invoice Proposal Creation

The current tenant does not expose writable OData entities for Project Invoice Proposal header and on-account proposal lines. Step 6 therefore extracts and displays the Invoice Schedule, then defers D365 posting with an explicit diagnostic.

To automate Step 6 in a future release, create a custom D365 F&O service class/action that creates a draft Project Invoice Proposal only. It should not post or finalize the customer invoice.

Recommended D365 design:

- Service class: `ProjectInvoiceProposalIntegrationService`
- Method/action: `createProposal`
- Purpose: create Project Invoice Proposal header and on-account lines from the approved Step 6 payload
- Behavior: create proposal/draft only; do not post invoice
- OData/custom service exposure: publish the action so it appears in tenant metadata or has a documented callable endpoint

Suggested request shape:

```json
{
  "dataAreaId": "2020",
  "projectContractId": "PC-000037",
  "proposalId": "PIP-INV-003",
  "invoiceDate": "2024-05-31",
  "customerReference": "INV-003",
  "currencyCode": "AED",
  "postInvoice": false,
  "lines": [
    {
      "projectId": "PROJ-000036-01",
      "description": "Package 2 Delivery",
      "amountExcludingTax": 13522092.57,
      "taxAmount": 676104.63,
      "amountIncludingTax": 14198197.20
    },
    {
      "projectId": "PROJ-000036-02",
      "description": "Package 2 Delivery",
      "amountExcludingTax": 12705433.43,
      "taxAmount": 635271.67,
      "amountIncludingTax": 13340705.10
    }
  ]
}
```

Suggested response shape:

```json
{
  "success": true,
  "proposalId": "PIP-000123",
  "message": "Project invoice proposal created. Invoice not posted."
}
```

Once the D365 service/action is deployed and visible to this app, wire Step 6 to call it as the final posting activity instead of deferring `ProjectInvoiceProposalHeaders` and `ProjectInvoiceProposalOnAccountLines`.

## Future Enhancement: WBS, Project Budget, and Cost Forecast Automation

The active Step 3 flow creates the parent project and sub-project hierarchy only. Work breakdown structure tasks, project budget, and project cost forecast automation are intentionally kept out of the current posting flow.

Future D365 automation can be added through custom service/actions similar to the draft Project Invoice Proposal approach.

Recommended future service/actions:

- `createProjectWorkBreakdownStructure`
- `createProjectBudget`
- `createProjectCostForecast`

Suggested WBS request shape:

```json
{
  "dataAreaId": "2020",
  "projectId": "PROJ-000036-01",
  "tasks": [
    {
      "taskId": "M2",
      "taskName": "Package 2 Delivery",
      "isMilestone": true,
      "scheduledEndDate": "2024-05-31"
    }
  ]
}
```

Suggested Project Budget request shape:

```json
{
  "dataAreaId": "2020",
  "projectId": "PROJ-000036-01",
  "budgetModelId": "BUDGET",
  "currencyCode": "AED",
  "budgetLines": [
    {
      "categoryId": "SERVICES",
      "amount": 13522092.57,
      "fromDate": "2024-05-01",
      "toDate": "2024-05-31"
    }
  ]
}
```

Suggested Project Cost Forecast request shape:

```json
{
  "dataAreaId": "2020",
  "projectId": "PROJ-000036-01",
  "forecastModelId": "PLO",
  "forecastLines": [
    {
      "categoryId": "SERVICES",
      "transactionDate": "2024-05-31",
      "costAmount": 0.0,
      "salesAmount": 13522092.57
    }
  ]
}
```

These future actions should call D365 standard business logic where possible rather than inserting directly into underlying tables.
