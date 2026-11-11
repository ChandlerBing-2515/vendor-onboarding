"""Step 4 check: reading a normal PDF and detecting a scanned one.
Run first:  python sample_data/make_samples.py
Then:       python checks/check_3_pdfs.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.pdf_text import extract_text  # noqa: E402

for name in ["01_happy_path_gb/bank_evidence.pdf", "03_scanned_tax_doc_in/tax_registration.pdf"]:
    result = extract_text(str(ROOT / "sample_data" / name))
    print(f"{name}: readable={result.readable}, characters={result.char_count}")
    if result.readable:
        print("   first lines:", result.pages[0].splitlines()[:3])
    else:
        print("   problem:", result.problem)
