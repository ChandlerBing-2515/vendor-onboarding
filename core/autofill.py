"""
Suggests form values from what was read in uploaded documents.

Rules (kept deliberately simple and transparent):
  - Only EMPTY form fields are filled. Anything already typed is never changed,
    so a typed value that disagrees with a document is still caught later.
  - Low-confidence values are not used; they are listed as "not filled".
  - Each filled field remembers its source document. A match against that same
    document is then labelled "not an independent check" (see comparison.py).
  - Country, bank country and tax ID type are worked out only where it is
    unambiguous: bank country from the IBAN prefix or the bank code's format
    (IFSC, US routing number, SWIFT/BIC); country from a VAT prefix or from the
    tax ID format (using the bank country only to break a tie); tax ID type from
    the configured format patterns.
"""

import re

from core.models import DocumentExtraction, DocumentType
from core.validation import COUNTRY_NAMES, COUNTRY_RULES, aba_is_valid, compact

# form field <- (document type, document field), in order of preference
SOURCES = {
    "vendor_name": [(DocumentType.BUSINESS_REGISTRATION, "company_name"),
                    (DocumentType.TAX_REGISTRATION, "company_name")],
    "registration_number": [(DocumentType.BUSINESS_REGISTRATION, "registration_number")],
    "tax_id": [(DocumentType.TAX_REGISTRATION, "tax_id")],
    "bank_account_holder": [(DocumentType.BANK_EVIDENCE, "bank_account_holder")],
    "bank_account_number": [(DocumentType.BANK_EVIDENCE, "bank_account_number")],
    "bank_code": [(DocumentType.BANK_EVIDENCE, "bank_code")],
}
ADDRESS_SOURCES = [DocumentType.BUSINESS_REGISTRATION, DocumentType.ADDRESS_PROOF]

POSTCODE_PATTERNS = [
    r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b",   # UK, e.g. BS1 4XY
    r"\b\d{6}\b",                               # India
    r"\b\d{5}(?:-\d{4})?\b",                    # US / Germany / many others
]


def split_address(address: str) -> dict:
    """'8 Quay Side, Bristol BS1 4XY' -> street, city, postal code (best effort)."""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 2:
        return {"address_line": address.strip()}
    street, rest = parts[0], " ".join(parts[1:])
    postal = ""
    for pattern in POSTCODE_PATTERNS:
        m = re.search(pattern, rest.upper())
        if m:
            postal = rest[m.start():m.end()]
            rest = (rest[:m.start()] + rest[m.end():]).strip(" ,")
            break
    out = {"address_line": street, "city": rest.strip(" ,")}
    if postal:
        out["postal_code"] = postal
    return {k: v for k, v in out.items() if v}


def guess_tax_type(country: str, tax_id: str) -> str:
    for name, pattern in COUNTRY_RULES.get(country, {}).get("tax_types", {}).items():
        if re.fullmatch(pattern, compact(tax_id)):
            return name
    return ""


def bank_country_from(account: str, bank_code: str) -> tuple[str, str] | None:
    """Country of the bank, from the IBAN prefix or the bank code's format."""
    iban, code = compact(account), compact(bank_code)
    if re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,}$", iban) and iban[:2] in COUNTRY_NAMES:
        return iban[:2], "IBAN prefix"
    if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", code):
        return "IN", "IFSC code format"
    if aba_is_valid(code):
        return "US", "US routing number"
    if re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", code) and code[4:6] in COUNTRY_NAMES:
        return code[4:6], "SWIFT/BIC code"
    return None


def country_from_tax_id(tax_id: str, bank_country: str) -> tuple[str, str] | None:
    """Country whose tax ID format matches. If several match (a 9-digit number fits a
    US EIN and a UK VAT number), the bank's country decides; otherwise leave it empty."""
    raw, flat = tax_id.strip().upper(), compact(tax_id)
    if flat[:2].isalpha() and flat[:2] in COUNTRY_RULES:
        return flat[:2], "VAT prefix"
    matches = [c for c, rules in COUNTRY_RULES.items()
               if any(re.fullmatch(p, raw) or re.fullmatch(p, flat)
                      for p in rules["tax_types"].values())]
    if len(matches) == 1:
        return matches[0], "tax ID format"
    if bank_country in matches:
        return bank_country, "tax ID format + bank country"
    return None


def suggest(extractions: list[DocumentExtraction], current: dict) -> tuple[dict, list[str]]:
    """Returns ({field: (value, source document type, filename)}, notes).
    `current` holds the form's present values; only empty ones are filled."""
    by_type = {ex.doc_type: ex for ex in extractions if ex.readable and ex.fields}
    fills, notes = {}, []

    def usable(ex: DocumentExtraction, field: str):
        ev = getattr(ex.fields, field)
        if ev.value is None:
            return None
        if ev.confidence == "low":
            notes.append(f"Not filled: {field.replace('_', ' ')} in {ex.filename} was read "
                         "with low confidence.")
            return None
        return ev.value.strip()

    def empty(field: str) -> bool:
        return not str(current.get(field, "")).strip() and field not in fills

    for form_field, sources in SOURCES.items():
        if not empty(form_field):
            continue
        for doc_type, doc_field in sources:
            ex = by_type.get(doc_type)
            value = usable(ex, doc_field) if ex else None
            if value:
                if form_field == "bank_account_number":
                    value = compact(value)        # 'GB29 NWBK ...' -> 'GB29NWBK...'
                fills[form_field] = (value, doc_type.value, ex.filename)
                break

    for doc_type in ADDRESS_SOURCES:
        ex = by_type.get(doc_type)
        value = usable(ex, "address") if ex else None
        if value:
            for field, part in split_address(value).items():
                if empty(field):
                    fills[field] = (part, doc_type.value, ex.filename)
            break

    # Derived values, only when unambiguous
    def value(field: str) -> str:
        return str(current.get(field) or fills.get(field, ("",))[0])

    bank = bank_country_from(value("bank_account_number"), value("bank_code"))
    if empty("bank_country") and bank:
        fills["bank_country"] = (bank[0], DocumentType.BANK_EVIDENCE.value, bank[1])

    tax_id = value("tax_id")
    if empty("country") and tax_id:
        country = country_from_tax_id(tax_id, value("bank_country"))
        if country:
            fills["country"] = (country[0], DocumentType.TAX_REGISTRATION.value, country[1])

    if empty("tax_id_type") and value("country") and tax_id:
        guessed = guess_tax_type(value("country"), tax_id)
        if guessed:
            fills["tax_id_type"] = (guessed, DocumentType.TAX_REGISTRATION.value, "tax ID format")
    return fills, notes
