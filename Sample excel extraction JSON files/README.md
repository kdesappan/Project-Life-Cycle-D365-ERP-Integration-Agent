# D365 F&O Project Lifecycle Payloads — Engagement Letter No. 01 (R100 Platform)

REST/OData JSON extracted from `Project agent 1a - Engagement Letter - Presight and Daypop_IFRS15_Analysis.xlsx`, shaped for the Dynamics 365 Finance & Operations **Project management and accounting** module.

**Contract:** Engagement Letter No. 01 — R100 Crisis and Emergency Management Platform
**Customer:** G42 Sky1 Technology Projects LLC (Presight) · **Supplier:** Daypop Technology Projects LLC
**Transaction price:** AED 116,051,000 excl. VAT (AED 121,853,550 incl. 5% UAE VAT) · **Term:** 1 Apr 2023 – 31 Mar 2026

## Files

| File | Contents | D365 entities |
|---|---|---|
| `00_reference_data.json` | Prerequisite master data — legal entity, customer, payment terms, VAT group, project group, ledger account mapping, Performance Bond tracking | `LegalEntities`, `CustomersV3`, `PaymentTerms`, `TaxGroups`, `ProjectGroups` |
| `01_project_contract.json` | Contract header, funding source, funding rule, plus all legal terms as extension data (LDs, warranty, liability cap, IP, governing law, FX, financing component) | `ProjectContractHeaders`, `ProjectContractFundingSources`, `ProjectContractFundingRules` |
| `02_project_master.json` | Parent project + one sub-project per performance obligation + 7 milestone WBS tasks | `ProjectsV2`, `ProjectWorkBreakdownStructureTasks` |
| `03_ifrs15_performance_obligations.json` | POB-1 and POB-2 as contract lines with SSP allocation, plus the 5-step model, transaction price build-up and significant judgements | `ProjectContractLines` + extension |
| `04_milestone_billing_schedule.json` | 7 milestones — dates, acceptance criteria, recognition triggers, value split by POB, VAT | `ProjectBillingSchedules`, `ProjectBillingScheduleLines` |
| `05_invoice_schedule.json` | 7 invoices as on-account proposals with per-POB lines, VAT, due dates, cash-flow priority | `ProjectInvoiceProposalHeaders`, `ProjectInvoiceProposalOnAccountLines` |
| `06_revenue_recognition.json` | 38 monthly periods: revenue by POB, cumulative % complete, contract asset/liability roll-forward, journal templates, month-end checklist | `ProjectEstimateProjects` + period estimate process |
| `call_sequence.yaml` | OpenAPI-style POST sequence, dependencies, auth, error handling, rollback, go-live preconditions | — |

## Model mapping

IFRS 15 concept → D365 object:

```
Contract (Engagement Letter)   →  Project contract  PC-EL01-R100
  Performance obligation POB-1 →  Sub-project  R100-EL01-01  + contract line 1  (AED 59,832,268 / 51.57%)
  Performance obligation POB-2 →  Sub-project  R100-EL01-02  + contract line 2  (AED 56,218,732 / 48.43%)
  Milestone M0–M6              →  Billing schedule line + WBS milestone task
  Revenue recognition trigger  →  Milestone acceptance → completion % → period estimate
  Transaction price            →  Funding limit  AED 116,051,000
  VAT                          →  Sales tax, outside the transaction price (IFRS 15.47)
```

Both POBs are satisfied **over time** using an **output** measure of progress (accepted milestone value). This matters operationally: D365 fixed-price projects default to a **cost-based** completion percentage, which would not reflect the IFRS 15 conclusion. `ProjectEstimateProjects` is therefore set to a manual completion percentage, fed from the schedule in file 06.

## Running it

Auth is Azure AD client credentials against `https://{env}.operations.dynamics.com/data`. Execute steps in the order in `call_sequence.yaml` — every step depends on keys from the previous one. Load sequentially; F&O throttles parallel OData writes. Idempotency is by natural key, so a 409 on replay is safe to treat as success.

**Step 0 is not optional.** F&O public entity names vary by version and by which features are enabled. Every entity flagged `x-verify: true` must be confirmed against your environment's `$metadata` before use. `ProjectBillingSchedules`, `ProjectBillingScheduleLines`, `ProjectContractLines` and `ProjectEstimateProjects` are the most likely to differ — in some versions fixed-price funding is carried on the project rather than on a separate contract-line entity.

## Open items — resolve before production

These come out of the source analysis and cannot be closed from the workbook alone.

1. **Per-milestone POB split is an estimate.** The workbook does not state how M1–M6 divide between P&I and Backbone. M0 is allocated 100% to POB-2 (licence delivery); M1–M6 are split pro-rata on residual POB value (POB-1 58.79% / POB-2 41.21%), with rounding absorbed in M6 so each POB ties exactly to its allocated price. This drives revenue by POB in every period — replace with the actual per-package split from Commercial Proposal Appendix B.

2. **AED 1,422 rounding variance.** The workbook's invoice schedule totals AED 116,052,422 ex-VAT against a TCV of AED 116,051,000, from AED/USD conversion rounding. Payloads carry both `amountExcludingTaxAsAnalysed` (original) and `amountExcludingTaxReconciled` (variance absorbed in M6, ties to TCV). Agree the treatment with Daypop before INV-005 is raised.

3. **Retroactive commencement.** Services began 1 Apr 2023; the Engagement Letter was signed 19 Sep 2023. File 06 recognises nothing before the M0 acceptance date and contains **no catch-up amount**, because the workbook does not quantify one. Quantify with the auditors and insert it.

4. **M6 falls outside the contract period.** INV-007 / M6 is dated May 2026 against a contract end of 31 Mar 2026. D365 will reject a billing schedule line outside the contract period — extend `ContractEndDate` or agree a revised date.

5. **Milestone percentages in the source are inconsistent.** The workbook's "% of POB value" column sums to 112.3% and M0 is stated as 24.7% where its invoice value implies 12.3% of TCV. Weights in these payloads are derived from invoice values and reconcile to 100.00%; the originals are retained as `sourcePercentOfPobValue`.

6. **Placeholders to confirm:** `DataAreaId` (DPTP), `CustomerAccount` (C-G42SKY1-001), project IDs, tax group codes, the ledger accounts in file 00, the fiscal calendar (Apr–Mar vs Jan–Dec), and the project manager `WorkerResponsibleId`, which is currently null.

## Ongoing lifecycle

Per milestone, on formal acceptance: set the WBS task to 100%, flip the billing schedule line to Completed, create the invoice proposal from file 05, then update the completion percentage from file 06. Next due is **M4 / INV-005 (May 2025)**, then M5 / INV-006 (Nov 2025) and M6 / INV-007 (May 2026).

At each period close, re-assess the liquidated damages constraint. LDs are negative variable consideration currently constrained to nil (IFRS 15.56); if an LD becomes highly probable, reduce the transaction price, re-allocate proportionally across both POBs and post a cumulative catch-up. LDs are non-VAT items and must never be netted inside a VAT-bearing invoice line.
