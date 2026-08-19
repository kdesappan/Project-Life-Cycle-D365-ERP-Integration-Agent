#!/usr/bin/env python3
"""Test script to verify ProjOnaccounttrans and ProjOnaccounttranssale extraction."""
import json
from pathlib import Path
from backend.services.excel_extractor import extract_all

# Find a sample Excel file
uploads_dir = Path("uploads")
sample_excel = None

for subdir in uploads_dir.iterdir():
    if subdir.is_dir():
        excel_files = list(subdir.glob("*.xlsx"))
        if excel_files:
            sample_excel = excel_files[0]
            break

if not sample_excel:
    print("ERROR: No sample Excel file found in uploads/")
    exit(1)

print(f"Testing with: {sample_excel}")
print("=" * 80)

# Extract data
results = extract_all(str(sample_excel))

# Check IFRS 15 extraction
print("\nIFRS 15 Performance Obligations Check:")
print("-" * 80)
ifrs15_data = results.get("ifrs15_obligations", {})
if "_extraction_error" in ifrs15_data:
    print(f"ERROR: {ifrs15_data['_extraction_error']}")
else:
    lines = ifrs15_data.get("ProjectContractLines", [])
    if lines:
        line = lines[0]
        print(f"OK Contract ID: {line.get('ProjectContractId', 'MISSING')}")
        print(f"OK BillingMethod: {line.get('BillingMethod', 'MISSING')}")
        print(f"OK Total lines: {len(lines)}")
    else:
        print("ERROR: No ProjectContractLines found")

# Check Milestone Billing extraction with NEW entities
print("\nMilestone On-Account Transaction Check (NEW):")
print("-" * 80)
milestone_data = results.get("milestone_billing", {})
if "_extraction_error" in milestone_data:
    print(f"ERROR: {milestone_data['_extraction_error']}")
else:
    trans_lines = milestone_data.get("ProjOnaccounttrans", [])
    sale_lines = milestone_data.get("ProjOnaccounttranssale", [])
    
    print(f"OK ProjOnaccounttrans count: {len(trans_lines)}")
    print(f"OK ProjOnaccounttranssale count: {len(sale_lines)}")
    
    if trans_lines:
        trans = trans_lines[0]
        print(f"\nFirst on-account transaction (ProjOnaccounttrans):")
        print(f"OK ProjectId: {trans.get('ProjectId', 'MISSING')}")
        print(f"OK Description: {trans.get('Description', 'MISSING')}")
        print(f"OK Amount: {trans.get('Amount', 'MISSING')}")
        print(f"OK TransactionType: {trans.get('TransactionType', 'MISSING')}")
        print(f"OK MilestoneId: {trans.get('MilestoneId', 'MISSING')}")
    
    if sale_lines:
        sale = sale_lines[0]
        print(f"\nFirst customer on-account transaction (ProjOnaccounttranssale):")
        print(f"OK ProjectId: {sale.get('ProjectId', 'MISSING')}")
        print(f"OK Description: {sale.get('Description', 'MISSING')}")
        print(f"OK Amount: {sale.get('Amount', 'MISSING')}")
        print(f"OK ProjectContractId: {sale.get('ProjectContractId', 'MISSING')}")
        print(f"OK PaymentTerms: {sale.get('PaymentTerms', 'MISSING')}")
        print(f"OK MilestoneStatus: {sale.get('MilestoneStatus', 'MISSING')}")

print("\n" + "=" * 80)
print("Extraction test completed!")

print("\nFull ProjOnaccounttrans output (first 2):")
print(json.dumps(results.get("milestone_billing", {}).get("ProjOnaccounttrans", [])[:2], indent=2))

print("\nFull ProjOnaccounttranssale output (first 2):")
print(json.dumps(results.get("milestone_billing", {}).get("ProjOnaccounttranssale", [])[:2], indent=2))
