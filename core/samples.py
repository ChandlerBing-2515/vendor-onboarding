"""
Helpers for the synthetic sample vendors in sample_data/.
Used by the Submit page (demo button), the checks and the evaluation.
"""

import json
from pathlib import Path

from core import database as db
from core.models import DocumentType, VendorSubmission
from core.storage import save_upload

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def load_scenarios() -> dict:
    path = SAMPLE_DIR / "scenarios.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def sample_files(name: str) -> list[tuple[DocumentType, Path]]:
    folder = SAMPLE_DIR / name
    return [(DocumentType(p.stem), p) for p in sorted(folder.glob("*.pdf"))]


def submit_scenario(name: str) -> int:
    """Create a vendor from a sample scenario and attach its PDFs. Returns vendor ID."""
    sc = load_scenarios()[name]
    vendor_id = db.create_vendor(VendorSubmission(**sc["form"]))
    for doc_type, path in sample_files(name):
        doc = save_upload(vendor_id, doc_type, path.name, path.read_bytes())
        db.add_document(vendor_id, doc)
    return vendor_id
