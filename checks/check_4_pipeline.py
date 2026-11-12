"""
End-to-end check of all core logic, without the UI.
Runs every sample scenario through the full pipeline in a TEMPORARY database
and upload folder, then records one human review.

Run with:  python checks/check_4_pipeline.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

tmp = Path(tempfile.mkdtemp(prefix="vendor_check_"))
os.environ["VENDOR_DB_PATH"] = str(tmp / "test.db")
os.environ["VENDOR_UPLOAD_DIR"] = str(tmp / "uploads")

from core import database as db, feedback  # noqa: E402
from core.extraction import ai_available  # noqa: E402
from core.models import ReviewAction  # noqa: E402
from core.pipeline import run_checks  # noqa: E402
from core.prioritization import build_queue  # noqa: E402
from core.samples import load_scenarios, submit_scenario  # noqa: E402

db.init_db()
scenarios = load_scenarios()
if not scenarios:
    raise SystemExit("No samples found. Run first:  python sample_data/make_samples.py")

print("Scenario                      Expected   Got        Result")
print("-" * 62)
all_ok = True
ids = {}
for name, sc in scenarios.items():
    vendor_id = submit_scenario(name)
    ids[name] = vendor_id
    rec = run_checks(vendor_id)
    ok = rec.status.value == sc["expected_recommendation"]
    needs_ai = sc.get("needs_ai") and not ai_available()
    if not needs_ai:
        all_ok &= ok
    result = "OK" if ok else ("needs AI" if needs_ai else "MISMATCH")
    print(f"{name:29} {sc['expected_recommendation']:10} {rec.status.value:10} {result}")
    print(f"    -> {rec.headline}")

print("\nReview queue (highest priority first):")
for q in build_queue():
    print(f"  tier {q['tier']} | {q['vendor_name']:32} | {q['why']}")

# Simulate a reviewer approving the happy path and correcting one value
vendor = db.get_vendor(ids["01_happy_path_gb"])
bank_doc = next(d for d in vendor["documents"] if d["doc_type"] == "bank_evidence")
feedback.record_review(
    vendor["id"], reviewer="Test Reviewer", action=ReviewAction.APPROVE,
    reason="All documents consistent; checked manually.",
    corrections=[{"document_id": bank_doc["id"], "doc_type": "bank_evidence",
                  "field_name": "bank_code", "extracted_value": "WESTGB2L",
                  "corrected_value": "WESTGB2L", "note": "example correction"}])

# A reject without a reason must be refused
try:
    feedback.record_review(ids["06_blocked_party"], "Test Reviewer", ReviewAction.REJECT, "")
    print("ERROR: rejection without a reason was accepted")
    all_ok = False
except ValueError as e:
    print(f"\nRejection without reason correctly refused: {e}")

m = feedback.metrics()
print(f"Reviews: {m['reviews']} | corrections: {m['corrections']} | "
      f"disagreement rate: {m['disagreement_rate']}")
print(f"Happy-path vendor status now: {db.get_vendor(ids['01_happy_path_gb'])['status']}")

shutil.rmtree(tmp, ignore_errors=True)
print("\nAll core checks passed." if all_ok else "\nSOME CHECKS FAILED - see above.")
