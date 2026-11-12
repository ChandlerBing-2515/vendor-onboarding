"""
Data models: the "shape" of every record the app works with.

Pydantic checks that data has the right types before we save or use it.
Most submission fields default to "" on purpose: an incomplete form is still
saved (as Pending) so we can tell the vendor exactly what is missing.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    """Current time in UTC as text, e.g. 2026-11-10T09:30:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Fixed choices ----------

class VendorType(str, Enum):
    COMPANY = "company"
    INDIVIDUAL = "individual"


class Status(str, Enum):
    APPROVED = "Approved"
    PENDING = "Pending"
    REJECTED = "Rejected"


class DocumentType(str, Enum):
    BUSINESS_REGISTRATION = "business_registration"
    TAX_REGISTRATION = "tax_registration"
    BANK_EVIDENCE = "bank_evidence"
    ADDRESS_PROOF = "address_proof"
    OTHER = "other"


DOC_LABELS = {
    DocumentType.BUSINESS_REGISTRATION: "Business registration certificate",
    DocumentType.TAX_REGISTRATION: "Tax registration document",
    DocumentType.BANK_EVIDENCE: "Bank account evidence",
    DocumentType.ADDRESS_PROOF: "Proof of business address",
    DocumentType.OTHER: "Other compliance document",
}


class CheckOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"  # inconclusive: a human must look


class Severity(str, Enum):
    CRITICAL = "critical"  # blocks approval on its own
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class Category(str, Enum):
    MISSING_INFO = "missing_info"          # vendor must send something
    FORMAT = "format"                      # value looks wrong
    MISMATCH = "mismatch"                  # form and document disagree
    DOCUMENT = "document"                  # file missing/unreadable
    UNCERTAIN = "uncertain"                # extraction not confident
    SPECIALIST = "specialist"              # needs manual/specialist check
    RISK = "risk"                          # possible risk indicator
    REJECTION_RULE = "rejection_rule"      # defined rejection condition


class ReviewAction(str, Enum):
    APPROVE = "approve"
    REQUEST_INFO = "request_info"
    REJECT = "reject"
    ESCALATE = "escalate"


# ---------- What the vendor submits ----------

class VendorSubmission(BaseModel):
    vendor_name: str = ""
    vendor_type: VendorType = VendorType.COMPANY
    country: str = ""               # ISO 2-letter code, e.g. "GB", "IN", "US"
    registration_number: str = ""   # company number (companies only)
    tax_id: str = ""
    tax_id_type: str = ""           # e.g. "VAT", "GSTIN", "EIN"

    address_line: str = ""
    city: str = ""
    postal_code: str = ""

    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""

    bank_country: str = ""
    bank_account_holder: str = ""
    bank_account_number: str = ""   # IBAN or local account number
    bank_code: str = ""             # SWIFT/BIC, IFSC, routing number

    # Fields filled automatically from an uploaded document: {field: document type}.
    # A match against that same document is then NOT an independent check.
    autofilled: dict[str, str] = {}
    # Auto-filled values that a person then changed (before submitting, or a reviewer later)
    autofill_edited: list[str] = []


class UploadedDocument(BaseModel):
    """Metadata about one uploaded PDF. The file itself lives on disk."""
    doc_type: DocumentType
    original_filename: str
    stored_path: str
    size_bytes: int
    uploaded_at: str = Field(default_factory=utc_now)


# ---------- What we extract from documents ----------
# No default values here on purpose: OpenAI "structured outputs" needs every
# field to be required. "None" means "not found in the document".

class ExtractedValue(BaseModel):
    value: str | None
    evidence_quote: str | None   # exact text copied from the document
    page: int | None
    confidence: Literal["high", "medium", "low"]


class DocumentFields(BaseModel):
    detected_document_type: str
    company_name: ExtractedValue
    registration_number: ExtractedValue
    tax_id: ExtractedValue
    address: ExtractedValue
    bank_account_holder: ExtractedValue
    bank_account_number: ExtractedValue
    bank_code: ExtractedValue
    issue_date: ExtractedValue
    notes: str


EXTRACTED_FIELD_NAMES = [
    "company_name", "registration_number", "tax_id", "address",
    "bank_account_holder", "bank_account_number", "bank_code", "issue_date",
]


class DocumentExtraction(BaseModel):
    """Result of reading one document: text status + extracted fields."""
    document_id: int
    doc_type: DocumentType
    filename: str
    readable: bool
    needs_ocr: bool = False
    read_from_images: bool = False   # True = scanned pages read by the AI from images
    page_count: int = 0
    text_chars: int = 0
    method: str = ""        # "openai:<model>", "pattern-fallback" or "none"
    fields: DocumentFields | None = None
    problem: str = ""       # why reading failed, if it did


# ---------- What checks produce ----------

class Finding(BaseModel):
    """The result of one check, written so a human can act on it."""
    check_id: str            # stable ID, e.g. "required.tax_id"
    label: str               # short name, e.g. "Tax ID provided"
    outcome: CheckOutcome
    severity: Severity
    category: Category
    message: str             # what we found
    next_action: str = ""    # what someone must do about it
    evidence: str = ""       # quote or values that support the finding
    source: str = "form"     # "form", "rules" or a document filename


class Recommendation(BaseModel):
    status: Status
    headline: str
    reasons: list[str]
    next_actions: list[str]                 # all actions, vendor first (kept for compatibility)
    blocking_check_ids: list[str]
    requires_human_authorization: bool = True
    vendor_requests: list[str] = []         # what the vendor must send or fix
    reviewer_tasks: list[str] = []          # what a human reviewer must check
