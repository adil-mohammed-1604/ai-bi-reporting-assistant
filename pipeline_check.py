"""End-to-end check: file -> quality -> SQL Server -> Python vs SQL KPIs.

Usage (from the project root, venv active):
    python pipeline_check.py
    python pipeline_check.py data/sample_retail_transactions.csv
"""
import sys
from pathlib import Path

from src.analytics import compute_kpis
from src.data_loader import load_file
from src.data_quality import run_quality_checks
from src.database import (DatabaseError, check_schema, file_sha256, reconcile,
                          run_sql_kpis, save_run)

path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/sample_retail_transactions.csv")

try:
    result = run_quality_checks(load_file(path))
    py = compute_kpis(result)
    print(f"Python KPIs ready ({result.summary['eligible_rows']} eligible rows)")

    check_schema()
    run_id = save_run(path.name, result, file_hash=file_sha256(path))
    print(f"Run stored in SQL Server with RunID = {run_id} "
          "(if this file was loaded before, the earlier run is reused)")

    rec = reconcile(py, run_sql_kpis(run_id))
    print(rec["checks"].to_string(index=False))
    if rec["ok"]:
        print("\nRECONCILED: Python and SQL agree.")
    else:
        print("\nMISMATCH: report must be marked as needing review.")
        print(rec["monthly_mismatches"].to_string(index=False))
except DatabaseError as exc:
    print("Database problem:", exc)
    sys.exit(1)