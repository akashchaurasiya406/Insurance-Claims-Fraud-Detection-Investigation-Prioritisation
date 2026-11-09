"""
Run the whole project end to end:

    1. generate data      -> data/raw/*.csv
    2. SQL layer          -> data/insurance_claims.db, reports/*.md, data/processed/claim_features.csv
    3. model              -> models/, reports/, data/processed/scored_claims_2025.csv
    4. Power BI export    -> powerbi/data/*.csv

Usage:
    python run_pipeline.py              # full run
    python run_pipeline.py --skip-data  # reuse existing data/raw
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    ("Generate synthetic claims data", "src/generate_data.py"),
    ("Build SQLite DB, run SQL checks, EDA & features", "src/build_database.py"),
    ("Train, compare & explain models", "src/train_model.py"),
    ("Export Power BI star schema", "src/export_powerbi.py"),
]

if __name__ == "__main__":
    skip_data = "--skip-data" in sys.argv
    for i, (label, script) in enumerate(STEPS, 1):
        if skip_data and script.endswith("generate_data.py"):
            continue
        print(f"\n{'=' * 70}\n[{i}/{len(STEPS)}] {label}\n{'=' * 70}")
        t = time.time()
        subprocess.run([sys.executable, str(ROOT / script)], check=True, cwd=ROOT)
        print(f"-- done in {time.time() - t:.0f}s")
    print("\nPipeline complete. Open notebooks/ for the walkthrough and powerbi/ for the dashboard guide.")
