"""
Transparent, rule-based checks on the submitted form.

Every rule is written out here in plain Python so a reviewer (or interviewer)
can read exactly what is checked. No AI is used in this file.

The POLICY section at the top is the "configuration": change it there,
not inside the check functions.
"""

import re
from difflib import SequenceMatcher

from core.models import (
    Category, CheckOutcome, DocumentType, Finding, Severity, VendorSubmission, VendorType,
)

# ======================= POLICY (edit here) =======================

# Countries with configured rules. Anything else is accepted but flagged for a
# specialist, because we have not implemented that country's requirements.
COUNTRY_RULES = {
    "GB": {"name": "United Kingdom", "tax_types": {"VAT": r"^(GB)?\d{9}$"},
           "bank": "iban"},
    "DE": {"name": "Germany", "tax_types": {"VAT": r"^(DE)?\d{9}$"},
           "bank": "iban"},
    "IN": {"name": "India",
           "tax_types": {"GSTIN": r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
                         "PAN": r"^[A-Z]{5}\d{4}[A-Z]$"},
           "bank": "ifsc"},
    "US": {"name": "United States", "tax_types": {"EIN": r"^\d{2}-?\d{7}$"},
           "bank": "aba"},
}

REQUIRED_FIELDS = {
    VendorType.COMPANY: ["vendor_name", "country", "registration_number", "tax_id",
                         "tax_id_type", "address_line", "city", "postal_code",
                         "contact_name", "contact_email", "bank_country",
                         "bank_account_holder", "bank_account_number"],
    VendorType.INDIVIDUAL: ["vendor_name", "country", "tax_id", "tax_id_type",
                            "address_line", "city", "postal_code", "contact_email",
                            "bank_country", "bank_account_holder", "bank_account_number"],
}

REQUIRED_DOCUMENTS = {
    VendorType.COMPANY: [DocumentType.BUSINESS_REGISTRATION, DocumentType.TAX_REGISTRATION,
                         DocumentType.BANK_EVIDENCE],
    VendorType.INDIVIDUAL: [DocumentType.TAX_REGISTRATION, DocumentType.BANK_EVIDENCE,
                            DocumentType.ADDRESS_PROOF],
}

# The ONLY automatic rejection condition in this MVP: an exact match against a
# blocked-party list. This list is SYNTHETIC test data, not a real sanctions list.
BLOCKED_PARTIES = {"blocked test vendor ltd", "sanctioned example corp"}

NAME_MATCH_THRESHOLD = 0.90   # similarity needed to call two names "the same"

# Dropdown choices for the form. These are only SUGGESTIONS: a country here
# without an entry in COUNTRY_RULES is still flagged for a specialist.
COUNTRY_NAMES = {
    "GB": "United Kingdom", "DE": "Germany", "IN": "India", "US": "United States",
    "AE": "United Arab Emirates", "AU": "Australia", "BR": "Brazil", "CA": "Canada",
    "CN": "China", "ES": "Spain", "FR": "France", "IE": "Ireland", "IT": "Italy",
    "JP": "Japan", "NL": "Netherlands", "SG": "Singapore",
}
TAX_TYPE_SUGGESTIONS = {
    "AE": ["TRN"], "AU": ["ABN"], "BR": ["CNPJ"], "CA": ["BN", "GST/HST"],
    "CN": ["USCC"], "ES": ["NIF", "VAT"], "FR": ["VAT", "SIREN"], "IE": ["VAT"],
    "IT": ["VAT"], "JP": ["Corporate Number"], "NL": ["VAT", "KvK"], "SG": ["UEN", "GST"],
}


def tax_types_for(country: str) -> list[str]:
    """Tax ID types to offer for a country: checked ones first, then suggestions."""
    c = (country or "").upper()
    checked = list(COUNTRY_RULES.get(c, {}).get("tax_types", {}))
    return checked + [t for t in TAX_TYPE_SUGGESTIONS.get(c, []) if t not in checked]


# ===================================================================

FIELD_LABELS = {
    "vendor_name": "Vendor name", "country": "Country of registration",
    "registration_number": "Company registration number", "tax_id": "Tax ID",
    "tax_id_type": "Tax ID type", "address_line": "Address", "city": "City",
    "postal_code": "Postal code", "contact_name": "Contact person",
    "contact_email": "Contact email", "contact_phone": "Contact phone",
    "bank_country": "Bank country", "bank_account_holder": "Bank account holder",
    "bank_account_number": "Bank account number", "bank_code": "Bank code",
}

LEGAL_SUFFIXES = r"\b(ltd|limited|plc|llc|inc|incorporated|corp|corporation|gmbh|ag|" \
                 r"pvt|private|co|company|llp)\b"


def normalize_name(name: str) -> str:
    """'Northwind Supplies Ltd.' -> 'northwind supplies' (for comparing names)."""
    name = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    name = re.sub(LEGAL_SUFFIXES, " ", name)
    return re.sub(r"\s+", " ", name).strip()


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def compact(value: str) -> str:
    """Remove spaces/dashes and upper-case: 'gb 12-34' -> 'GB1234'."""
    return re.sub(r"[\s\-]", "", value or "").upper()


def iban_is_valid(iban: str) -> bool:
    """Standard IBAN mod-97 checksum. Valid checksum != account exists."""
    iban = compact(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def aba_is_valid(routing: str) -> bool:
    """US ABA routing number checksum."""
    r = compact(routing)
    if not re.fullmatch(r"\d{9}", r):
        return False
    d = [int(c) for c in r]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


# ---------------------------- checks ----------------------------

def check_required_fields(s: VendorSubmission) -> list[Finding]:
    findings = []
    for field in REQUIRED_FIELDS[s.vendor_type]:
        label = FIELD_LABELS[field]
        if str(getattr(s, field)).strip():
            findings.append(Finding(
                check_id=f"required.{field}", label=f"{label} provided",
                outcome=CheckOutcome.PASS, severity=Severity.INFO,
                category=Category.MISSING_INFO, message=f"{label} is filled in."))
        else:
            findings.append(Finding(
                check_id=f"required.{field}", label=f"{label} provided",
                outcome=CheckOutcome.FAIL, severity=Severity.MAJOR,
                category=Category.MISSING_INFO, message=f"{label} is missing.",
                next_action=f"Ask the vendor to provide their {label.lower()}."))
    return findings


def check_email(s: VendorSubmission) -> list[Finding]:
    if not s.contact_email:
        return []  # already reported as missing
    ok = re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", s.contact_email.strip())
    return [Finding(
        check_id="format.email", label="Email format",
        outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        severity=Severity.INFO if ok else Severity.MINOR, category=Category.FORMAT,
        message="Email looks valid." if ok else f"'{s.contact_email}' is not a valid email.",
        next_action="" if ok else "Ask the vendor for a working contact email.",
        evidence=s.contact_email)]


def check_country_supported(s: VendorSubmission) -> list[Finding]:
    if not s.country:
        return []
    c = s.country.upper()
    if c in COUNTRY_RULES:
        return [Finding(
            check_id="policy.country_supported", label="Country rules configured",
            outcome=CheckOutcome.PASS, severity=Severity.INFO, category=Category.SPECIALIST,
            message=f"Rules for {COUNTRY_RULES[c]['name']} are configured.")]
    return [Finding(
        check_id="policy.country_supported", label="Country rules configured",
        outcome=CheckOutcome.NEEDS_REVIEW, severity=Severity.MAJOR, category=Category.SPECIALIST,
        message=f"No country-specific rules are configured for '{c}'. Tax ID and bank "
                f"formats could not be checked automatically.",
        next_action="Send to a specialist to verify local tax and banking requirements.")]


def check_tax_id_format(s: VendorSubmission) -> list[Finding]:
    c = s.country.upper()
    if not s.tax_id or c not in COUNTRY_RULES:
        return []
    patterns = COUNTRY_RULES[c]["tax_types"]
    tax_type = s.tax_id_type.upper().strip()
    if tax_type not in patterns:
        return [Finding(
            check_id="format.tax_id", label="Tax ID format",
            outcome=CheckOutcome.NEEDS_REVIEW, severity=Severity.MAJOR, category=Category.FORMAT,
            message=f"Tax ID type '{s.tax_id_type}' is not one we check for {c} "
                    f"(expected one of: {', '.join(patterns)}).",
            next_action="Confirm the correct tax ID type with the vendor.",
            evidence=f"{s.tax_id_type}: {s.tax_id}")]
    ok = re.fullmatch(patterns[tax_type], compact(s.tax_id))
    return [Finding(
        check_id="format.tax_id", label="Tax ID format",
        outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        severity=Severity.INFO if ok else Severity.MAJOR, category=Category.FORMAT,
        message=(f"{tax_type} number has the expected format for {c}. "
                 "(Format only: not checked against a government register.)") if ok else
                f"{tax_type} number '{s.tax_id}' does not match the expected format for {c}.",
        next_action="" if ok else f"Ask the vendor to re-check their {tax_type} number.",
        evidence=s.tax_id)]


def check_bank_details(s: VendorSubmission) -> list[Finding]:
    bc = s.bank_country.upper()
    if not s.bank_account_number or bc not in COUNTRY_RULES:
        return []
    kind = COUNTRY_RULES[bc]["bank"]
    if kind == "iban":
        ok = iban_is_valid(s.bank_account_number)
        msg_ok = "IBAN checksum is valid."
        msg_bad = f"IBAN '{s.bank_account_number}' fails the checksum (likely a typo)."
        evidence = s.bank_account_number
    elif kind == "ifsc":
        ok = bool(re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", compact(s.bank_code)))
        msg_ok = "IFSC code has the expected format."
        msg_bad = f"IFSC code '{s.bank_code}' does not have the expected format."
        evidence = s.bank_code
    else:
        ok = aba_is_valid(s.bank_code)
        msg_ok = "Routing number checksum is valid."
        msg_bad = f"Routing number '{s.bank_code}' fails the ABA checksum."
        evidence = s.bank_code
    return [Finding(
        check_id="format.bank", label="Bank details format",
        outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        severity=Severity.INFO if ok else Severity.MAJOR, category=Category.FORMAT,
        message=(msg_ok + " This does not prove the account exists or who owns it.") if ok
        else msg_bad,
        next_action="" if ok else "Ask the vendor to re-check their bank details.",
        evidence=evidence)]


def check_bank_holder_name(s: VendorSubmission) -> list[Finding]:
    if not (s.vendor_name and s.bank_account_holder):
        return []
    sim = name_similarity(s.vendor_name, s.bank_account_holder)
    ok = sim >= NAME_MATCH_THRESHOLD
    return [Finding(
        check_id="consistency.bank_holder_vs_vendor", label="Bank holder matches vendor name",
        outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        severity=Severity.INFO if ok else Severity.CRITICAL, category=Category.RISK,
        message="Bank account holder name matches the vendor name." if ok else
                "Bank account holder name is different from the vendor name. Payments could "
                "go to a third party.",
        next_action="" if ok else "Ask the vendor to explain or provide an account in the "
                                  "vendor's own name; a reviewer must confirm.",
        evidence=f"Vendor: '{s.vendor_name}' | Holder: '{s.bank_account_holder}' "
                 f"| similarity {sim:.2f}")]


def check_bank_country(s: VendorSubmission) -> list[Finding]:
    if not (s.country and s.bank_country) or s.country.upper() == s.bank_country.upper():
        return []
    return [Finding(
        check_id="risk.bank_country_differs", label="Bank country matches registration",
        outcome=CheckOutcome.NEEDS_REVIEW, severity=Severity.MAJOR, category=Category.RISK,
        message=f"Bank is in {s.bank_country.upper()} but the vendor is registered in "
                f"{s.country.upper()}. This can be legitimate but needs a reason.",
        next_action="Reviewer to confirm the business reason for a foreign bank account.",
        evidence=f"Registered: {s.country.upper()} | Bank: {s.bank_country.upper()}")]


def check_blocked_parties(s: VendorSubmission) -> list[Finding]:
    names = {normalize_name(s.vendor_name), normalize_name(s.bank_account_holder)}
    blocked = {normalize_name(b) for b in BLOCKED_PARTIES}
    hit = names & blocked - {""}
    return [Finding(
        check_id="policy.blocked_party", label="Not on blocked-party list (test list)",
        outcome=CheckOutcome.FAIL if hit else CheckOutcome.PASS,
        severity=Severity.CRITICAL if hit else Severity.INFO,
        category=Category.REJECTION_RULE,
        message=f"Name matches the blocked-party test list: {', '.join(hit)}." if hit else
                "No match on the synthetic blocked-party test list. (A real deployment "
                "needs a licensed sanctions-screening service.)",
        next_action="Reviewer to confirm the match and reject." if hit else "")]


def check_documents_present(s: VendorSubmission, uploaded_types: list[str]) -> list[Finding]:
    findings = []
    for doc_type in REQUIRED_DOCUMENTS[s.vendor_type]:
        present = doc_type.value in uploaded_types
        label = doc_type.value.replace("_", " ")
        findings.append(Finding(
            check_id=f"document.present.{doc_type.value}", label=f"{label.capitalize()} uploaded",
            outcome=CheckOutcome.PASS if present else CheckOutcome.FAIL,
            severity=Severity.INFO if present else Severity.MAJOR, category=Category.DOCUMENT,
            message=f"{label.capitalize()} uploaded." if present else
                    f"Required document missing: {label}.",
            next_action="" if present else f"Ask the vendor to upload their {label}."))
    return findings


def run_form_checks(s: VendorSubmission, uploaded_types: list[str]) -> list[Finding]:
    """All rule-based checks on the form. Order = order shown to reviewers."""
    return (check_blocked_parties(s) + check_required_fields(s) + check_documents_present(
        s, uploaded_types) + check_country_supported(s) + check_email(s)
        + check_tax_id_format(s) + check_bank_details(s) + check_bank_holder_name(s)
        + check_bank_country(s))
