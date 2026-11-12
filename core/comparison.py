"""
Compares what the vendor TYPED with what their DOCUMENTS say.

A match means "the document says the same thing as the form". It does NOT
mean the document is genuine. We say this in every message.

Rules for each comparison:
  - document unreadable            -> needs_review (OCR / new copy needed)
  - value not found in document    -> needs_review
  - low-confidence extraction      -> needs_review (a human must look)
  - clear match                    -> pass
  - clear mismatch                 -> fail, with the severity set below
"""

from core.models import (
    DOC_LABELS, Category, CheckOutcome, DocumentExtraction, DocumentType, Finding, Severity,
    VendorSubmission,
)
from core.validation import compact, name_similarity, normalize_name, NAME_MATCH_THRESHOLD

# (field in document, field in form, how to compare, severity if they disagree)
COMPARISONS = {
    DocumentType.BUSINESS_REGISTRATION: [
        ("company_name", "vendor_name", "name", Severity.CRITICAL),
        ("registration_number", "registration_number", "id", Severity.MAJOR),
        ("address", "address", "address", Severity.MINOR),
    ],
    DocumentType.TAX_REGISTRATION: [
        ("tax_id", "tax_id", "id", Severity.CRITICAL),
        ("company_name", "vendor_name", "name", Severity.MAJOR),
    ],
    DocumentType.BANK_EVIDENCE: [
        ("bank_account_holder", "bank_account_holder", "name", Severity.CRITICAL),
        ("bank_account_number", "bank_account_number", "id", Severity.CRITICAL),
        ("bank_code", "bank_code", "id", Severity.MAJOR),
    ],
    DocumentType.ADDRESS_PROOF: [
        ("address", "address", "address", Severity.MAJOR),
        ("company_name", "vendor_name", "name", Severity.MINOR),
    ],
    DocumentType.OTHER: [],
}

FIELD_TITLES = {
    "company_name": "Company name", "registration_number": "Registration number",
    "tax_id": "Tax ID", "address": "Address", "bank_account_holder": "Account holder",
    "bank_account_number": "Account number", "bank_code": "Bank code",
}


ADDRESS_PARTS = ["address_line", "city", "postal_code"]


def form_value(s: VendorSubmission, field: str) -> str:
    if field == "address":
        return ", ".join(p for p in [s.address_line, s.city, s.postal_code] if p)
    return getattr(s, field)


def values_match(kind: str, form: str, doc: str, s: VendorSubmission) -> bool:
    if kind == "name":
        return name_similarity(form, doc) >= NAME_MATCH_THRESHOLD
    if kind == "id":
        a, b = compact(form), compact(doc)
        if a == b:
            return True
        # allow a country prefix on one side only: "GB123456789" vs "123456789"
        shorter, longer = sorted([a, b], key=len)
        return len(shorter) >= 6 and longer.endswith(shorter) and len(longer) - len(shorter) <= 2
    if kind == "address":
        doc_c = compact(doc)
        postal_ok = bool(s.postal_code) and compact(s.postal_code) in doc_c
        city_ok = bool(s.city) and normalize_name(s.city) in normalize_name(doc)
        return postal_ok and city_ok
    raise ValueError(kind)


# Short everyday names, used inside action sentences
DOC_SHORT = {
    DocumentType.BUSINESS_REGISTRATION: "registration certificate",
    DocumentType.TAX_REGISTRATION: "tax certificate",
    DocumentType.BANK_EVIDENCE: "bank letter or statement",
    DocumentType.ADDRESS_PROOF: "proof of address",
    DocumentType.OTHER: "document",
}


def soft_lower(text: str) -> str:
    """'Tax ID' -> 'tax ID' (keeps acronyms in capitals)."""
    return " ".join(w if w.isupper() else w.lower() for w in text.split())


def compare_document(s: VendorSubmission, ex: DocumentExtraction) -> list[Finding]:
    src = ex.filename
    doc_name = DOC_LABELS[ex.doc_type].lower()
    if not ex.readable or ex.fields is None:
        return [Finding(
            check_id=f"document.readable.{ex.doc_type.value}",
            label=f"{ex.doc_type.value.replace('_', ' ').capitalize()} readable",
            outcome=CheckOutcome.NEEDS_REVIEW, severity=Severity.MAJOR,
            category=Category.DOCUMENT,
            message=f"Could not read '{src}': {ex.problem}",
            next_action=(f"Ask the vendor to send a text-based (digital) PDF of the {doc_name}; "
                         "a reviewer must read the scan manually in the meantime") if ex.needs_ocr
            else f"Ask the vendor to re-upload the {doc_name} as a valid, unlocked PDF",
            source=src)]

    findings = [Finding(
        check_id=f"document.readable.{ex.doc_type.value}",
        label=f"{ex.doc_type.value.replace('_', ' ').capitalize()} readable",
        outcome=CheckOutcome.PASS, severity=Severity.INFO, category=Category.DOCUMENT,
        message=(f"Scanned document: {ex.page_count} page(s) read from images using {ex.method}."
                 if ex.read_from_images else
                 f"Read {ex.text_chars} characters from {ex.page_count} page(s) using {ex.method}."),
        source=src)]

    if ex.read_from_images:
        findings.append(Finding(
            check_id=f"document.image_read.{ex.doc_type.value}",
            label=f"{ex.doc_type.value.replace('_', ' ').capitalize()} read from scan",
            outcome=CheckOutcome.NEEDS_REVIEW, severity=Severity.MINOR, category=Category.UNCERTAIN,
            message="This document is a scan, so the AI read it from page images. Its quotes "
                    "cannot be checked automatically against the file.",
            next_action="Reviewer to open the PDF and confirm the extracted values.",
            source=src))

    for doc_field, form_field, kind, severity in COMPARISONS[ex.doc_type]:
        title = FIELD_TITLES[doc_field]
        check_id = f"compare.{ex.doc_type.value}.{doc_field}"
        label = f"{title}: form vs {ex.doc_type.value.replace('_', ' ')}"
        form_val = form_value(s, form_field)
        if not form_val:
            continue  # missing form value is already reported by validation
        ev = getattr(ex.fields, doc_field)
        source_fields = ADDRESS_PARTS if form_field == "address" else [form_field]
        if any(s.autofilled.get(f) == ex.doc_type.value for f in source_fields):
            findings.append(Finding(
                check_id=check_id, label=label, outcome=CheckOutcome.PASS,
                severity=Severity.INFO, category=Category.MISMATCH,
                message=f"{title} on the form was auto-filled from this document, so this "
                        "is not an independent check. It is still compared with the other "
                        "documents.",
                evidence=f"Form: '{form_val}' (auto-filled)", source=src))
            continue
        evidence = f"Form: '{form_val}'"
        if ev.value is None:
            findings.append(Finding(
                check_id=check_id, label=label, outcome=CheckOutcome.NEEDS_REVIEW,
                severity=Severity.MAJOR if severity == Severity.CRITICAL else Severity.MINOR,
                category=Category.UNCERTAIN,
                message=f"{title} was not found in '{src}'.",
                next_action=f"Reviewer to check the document for the {title.lower()}.",
                evidence=evidence, source=src))
            continue

        evidence += f" | Document p.{ev.page}: \"{ev.evidence_quote}\" (confidence: {ev.confidence})"
        match = values_match(kind, form_val, ev.value, s)

        if ev.confidence == "low":
            findings.append(Finding(
                check_id=check_id, label=label, outcome=CheckOutcome.NEEDS_REVIEW,
                severity=Severity.MAJOR, category=Category.UNCERTAIN,
                message=f"{title} extracted with low confidence ('{ev.value}'); it "
                        f"{'seems to match' if match else 'does not seem to match'} the form.",
                next_action=f"Reviewer to read the {title.lower()} in the document and confirm.",
                evidence=evidence, source=src))
        elif match:
            findings.append(Finding(
                check_id=check_id, label=label, outcome=CheckOutcome.PASS,
                severity=Severity.INFO, category=Category.MISMATCH,
                message=f"{title} in the document matches the form. (Consistency only; "
                        "the document itself is not verified as genuine.)",
                evidence=evidence, source=src))
        else:
            findings.append(Finding(
                check_id=check_id, label=label, outcome=CheckOutcome.FAIL,
                severity=severity, category=Category.MISMATCH,
                message=f"{title} differs: form says '{form_val}', document says '{ev.value}'.",
                next_action=f"Ask the vendor to correct the {soft_lower(title)} on the form, or "
                            f"send a {DOC_SHORT[ex.doc_type]} that matches it; a reviewer must confirm the "
                            f"correct {soft_lower(title)}",
                evidence=evidence, source=src))
    return findings


def compare_all(s: VendorSubmission, extractions: list[DocumentExtraction]) -> list[Finding]:
    out = []
    if s.autofilled:
        filled = ", ".join(f"{f.replace('_', ' ')} (from {d.replace('_', ' ')})"
                           for f, d in s.autofilled.items())
        out.append(Finding(
            check_id="form.autofilled", label="Fields auto-filled from documents",
            outcome=CheckOutcome.PASS, severity=Severity.INFO, category=Category.UNCERTAIN,
            message=f"These form values were filled from uploaded documents and confirmed by "
                    f"the submitter: {filled}.", source="form"))
    for ex in extractions:
        out.extend(compare_document(s, ex))
    return out
