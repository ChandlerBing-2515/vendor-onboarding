"""
Measures the system on the labelled synthetic test set (sample_data/scenarios.json).

For each scenario it runs the full pipeline in a THROWAWAY copy of the
database and measures:
  - field accuracy: extracted values vs the true values printed in the PDFs
  - recommendation accuracy: system recommendation vs the expected one

Run:
  python evaluation/evaluate.py               (uses past reviewer corrections)
  python evaluation/evaluate.py --no-examples (ignores them, for comparison)

Results are appended to evaluation/results.json and shown in the app.
Compare runs only on the same test set and the same extraction method.
With the pattern fallback (no API key), corrections cannot change results.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser()
parser.add_argument("--no-examples", action="store_true",
                    help="Do not add reviewer corrections to the AI prompt.")
args = parser.parse_args()

tmp = Path(tempfile.mkdtemp(prefix="vendor_eval_"))
real_db = ROOT / "data" / "vendors.db"
if real_db.exists():                       # copy so we can use stored corrections
    shutil.copy(real_db, tmp / "eval.db")  # without touching real data
os.environ["VENDOR_DB_PATH"] = str(tmp / "eval.db")
os.environ["VENDOR_UPLOAD_DIR"] = str(tmp / "uploads")

try:  # load the API key from .streamlit/secrets.toml if it is not in the environment
    import tomllib
    secrets = ROOT / ".streamlit" / "secrets.toml"
    if secrets.exists():
        for k, val in tomllib.loads(secrets.read_text()).items():
            os.environ.setdefault(k, str(val))
except Exception:
    pass

from core import database as db  # noqa: E402
from core.comparison import values_match  # noqa: E402
from core.extraction import method_label  # noqa: E402
from core.models import VendorSubmission  # noqa: E402
from core.pipeline import run_checks  # noqa: E402
from core.samples import load_scenarios, submit_scenario  # noqa: E402

KIND = {"company_name": "name", "bank_account_holder": "name", "address": "address",
        "issue_date": "name"}

db.init_db()
scenarios = load_scenarios()
fields_total = fields_correct = rec_correct = 0
errors = []
methods = Counter()  # what ACTUALLY read each document

for n, (name, sc) in enumerate(scenarios.items(), start=1):
    print(f"[{n}/{len(scenarios)}] {name}", flush=True)
    form = VendorSubmission(**sc["form"])
    vendor_id = submit_scenario(name)
    # One pass: run_checks reads each PDF once and stores what it extracted
    rec = run_checks(vendor_id, progress=lambda msg: print(f"      {msg}", flush=True),
                     use_examples=not args.no_examples)
    for doc in db.list_documents(vendor_id):
        truth = sc["documents"][doc["doc_type"]]
        ex = doc["extraction"]
        methods[ex.method] += 1
        if "AI error" in ex.method and ex.fields:
            errors.append(f"{name}/{doc['doc_type']}: AI call failed -> {ex.fields.notes.strip()[-200:]}")
        for field, true_value in truth.items():
            fields_total += 1
            got = getattr(ex.fields, field).value if ex.readable and ex.fields else None
            ok = got is not None and values_match(KIND.get(field, "id"), true_value, got, form)
            fields_correct += ok
            if not ok:
                errors.append(f"{name}/{doc['doc_type']}/{field}: expected '{true_value}', got '{got}'")
    rec_correct += rec.status.value == sc["expected_recommendation"]
    if rec.status.value != sc["expected_recommendation"]:
        errors.append(f"{name}: expected {sc['expected_recommendation']}, got {rec.status.value}")

print()
shutil.rmtree(tmp, ignore_errors=True)

result = {
    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "method": method_label(),
    "documents_read_with": dict(methods),
    "used_correction_examples": not args.no_examples,
    "cases": len(scenarios),
    "field_accuracy": fields_correct / fields_total if fields_total else 0,
    "fields_checked": fields_total,
    "recommendation_accuracy": rec_correct / len(scenarios) if scenarios else 0,
    "errors": errors,
}
out = ROOT / "evaluation" / "results.json"
history = json.loads(out.read_text()) if out.exists() else []
history.append(result)
out.write_text(json.dumps(history, indent=2))

print(f"Method: {result['method']} | correction examples: {result['used_correction_examples']}")
print("Documents actually read with:", ", ".join(f"{m} x{n}" for m, n in methods.items()))
if any("AI error" in m for m in methods):
    print("WARNING: some AI calls failed, so those documents used the pattern fallback. "
          "See the 'AI call failed' lines below.")
print(f"Field accuracy:          {fields_correct}/{fields_total} = {result['field_accuracy']:.0%}")
print(f"Recommendation accuracy: {rec_correct}/{len(scenarios)} = {result['recommendation_accuracy']:.0%}")
if methods.get("none"):
    print("Note: a scanned document could not be read (no AI configured, or the AI call failed), "
          "so its fields count as missed.")
for e in errors:
    print("  miss:", e)
print(f"Saved to {out}")
