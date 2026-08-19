#!/usr/bin/env python3
"""Debug script to examine the sample Excel file structure."""
import pandas as pd
from pathlib import Path

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
    print("ERROR: No sample Excel file found")
    exit(1)

print(f"Analyzing: {sample_excel}")
print("=" * 80)

xl = pd.ExcelFile(sample_excel, engine="openpyxl")
print(f"\nSheet Names: {xl.sheet_names}\n")

# Check each sheet
for i, sheet_name in enumerate(xl.sheet_names):
    print(f"\n{'='*80}")
    print(f"Sheet {i}: '{sheet_name}'")
    print(f"{'='*80}")
    
    df = pd.read_excel(sample_excel, sheet_name=sheet_name)
    print(f"Shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(f"\nFirst 3 rows:")
    print(df.head(3).to_string())
