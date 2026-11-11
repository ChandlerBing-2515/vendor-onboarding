"""Step 3 check: the rule-based validation on a deliberately flawed vendor.
Run:  python checks/check_2_rules.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import VendorSubmission  # noqa: E402
from core.validation import run_form_checks  # noqa: E402

flawed = VendorSubmission(
    vendor_name="Northwind Test Supplies Ltd", country="GB", registration_number="09876543",
    tax_id="GB12345", tax_id_type="VAT",                      # too short
    address_line="12 Example Street", city="Manchester", postal_code="M1 2AB",
    contact_name="Asha Patel", contact_email="asha(at)example",  # bad email
    bank_country="GB", bank_account_holder="Someone Else Trading",  # different holder
    bank_account_number="GB82WEST12345698765433",               # last digit changed
)
findings = run_form_checks(flawed, uploaded_types=["business_registration"])
for f in findings:
    if f.outcome != "pass":
        print(f"[{f.outcome.value:12}] [{f.severity.value:8}] {f.label}: {f.message}")
print(f"\n{len(findings)} checks run, {sum(f.outcome != 'pass' for f in findings)} open issues.")
