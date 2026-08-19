#!/usr/bin/env python3
"""Test script to verify IFRS 15 and Milestone Billing extraction fixes."""
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
    print(f"❌ Error: {ifrs15_data['_extraction_error']}")
else:
    lines = ifrs15_data.get("ProjectContractLines", [])
    if lines:
        line = lines[0]
        print(f"✓ Contract ID: {line.get('ProjectContractId', 'MISSING')}")
        print(f"✓ BillingMethod: {line.get('BillingMethod', 'MISSING')} (should be 'FixedPriceMilestone')")
        print(f"✓ RevenueRecognitionMethod: {line.get('RevenueRecognitionMethod', 'MISSING')}")
        print(f"✓ ProgressMeasurement: {line.get('ProgressMeasurement', 'MISSING')}")
        print(f"✓ ContractLineNumber: {line.get('ContractLineNumber', 'MISSING')}")
        print(f"✓ LineAmountExcludingTax: {line.get('LineAmountExcludingTax', 'MISSING')}")
        print(f"✓ DataAreaId: {line.get('dataAreaId', 'MISSING')}")
        print(f"✓ Total lines: {len(lines)}")
    else:
        print("❌ No ProjectContractLines found")

# Check Milestone Billing extraction
print("\n✅ Milestone Billing Schedule Check:")
print("-" * 80)
milestone_data = results.get("milestone_billing", {})
if "_extraction_error" in milestone_data:
    print(f"❌ Error: {milestone_data['_extraction_error']}")
else:
    lines = milestone_data.get("ProjectBillingScheduleLines", [])
    schedules = milestone_data.get("ProjectBillingSchedules", [])
    
    if schedules:
        sched = schedules[0]
        print(f"✓ Contract ID: {sched.get('ProjectContractId', 'MISSING')}")
        print(f"✓ BillingScheduleId: {sched.get('BillingScheduleId', 'MISSING')}")
        print(f"✓ DataAreaId: {sched.get('dataAreaId', 'MISSING')}")
        print(f"✓ Total Amount: {sched.get('TotalAmountExcludingTax', 'MISSING')}")
    
    if lines:
        line = lines[0]
        print(f"\nFirst milestone:")
        print(f"✓ MilestoneId: {line.get('MilestoneId', 'MISSING')}")
        print(f"✓ BillingScheduleId: {line.get('BillingScheduleId', 'MISSING')}")
        print(f"✓ Amount: {line.get('AmountExcludingTax', 'MISSING')}")
        print(f"✓ DataAreaId: {line.get('dataAreaId', 'MISSING')}")
        print(f"✓ Total milestones: {len(lines)}")
    else:
        print("❌ No ProjectBillingScheduleLines found")

print("\n" + "=" * 80)
print("✅ Extraction test completed!")
print("\n📋 Full IFRS15 output sample:")
print(json.dumps(results.get("ifrs15_obligations", {}).get("ProjectContractLines", [])[:1], indent=2))
print("\n📋 Full Milestone output sample:")
print(json.dumps(results.get("milestone_billing", {}).get("ProjectBillingScheduleLines", [])[:2], indent=2))
