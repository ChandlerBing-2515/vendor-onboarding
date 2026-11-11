"""Step 2 check: models load and the database tables can be created.
Run:  python checks/check_1_database.py"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "import core" works
os.environ["VENDOR_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "check.db")

from core import database as db  # noqa: E402
from core.models import VendorSubmission  # noqa: E402

db.init_db()
vendor_id = db.create_vendor(VendorSubmission(vendor_name="Check Test Ltd", country="GB"))
vendor = db.get_vendor(vendor_id)
print("Saved and read back:", vendor["vendor_name"], "| status:", vendor["status"])
print("Audit log:", [e["event_type"] for e in vendor["events"]])
print("Database OK.")
