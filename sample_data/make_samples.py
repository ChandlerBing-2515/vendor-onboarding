"""
Creates SYNTHETIC test vendors and PDFs. All names, numbers and addresses are
invented. Run once:  python sample_data/make_samples.py

Output:
  sample_data/scenarios.json         form values + true document values (labels)
  sample_data/<scenario>/<doc>.pdf   the PDFs
"""

import json
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent

GB_HAPPY = {
    "vendor_name": "Northwind Test Supplies Ltd", "vendor_type": "company", "country": "GB",
    "registration_number": "09876543", "tax_id": "GB123456789", "tax_id_type": "VAT",
    "address_line": "12 Example Street", "city": "Manchester", "postal_code": "M1 2AB",
    "contact_name": "Asha Patel", "contact_email": "asha@northwind-test.example",
    "contact_phone": "+44 161 000 0000", "bank_country": "GB",
    "bank_account_holder": "Northwind Test Supplies Ltd",
    "bank_account_number": "GB82WEST12345698765432", "bank_code": "WESTGB2L",
}


def company_docs(form: dict, overrides: dict | None = None) -> dict:
    """True document contents for a company. `overrides` simulates documents
    that disagree with the form (the edge cases)."""
    o = overrides or {}
    address = f"{form['address_line']}, {form['city']}, {form['postal_code']}"
    return {
        "business_registration": {
            "company_name": o.get("company_name", form["vendor_name"]),
            "registration_number": o.get("registration_number", form["registration_number"]),
            "address": o.get("address", address), "issue_date": "14 March 2021"},
        "tax_registration": {
            "company_name": o.get("company_name", form["vendor_name"]),
            "tax_id": o.get("tax_id", form["tax_id"]), "issue_date": "02 May 2021"},
        "bank_evidence": {
            "bank_account_holder": o.get("bank_account_holder", form["bank_account_holder"]),
            "bank_account_number": o.get("bank_account_number", form["bank_account_number"]),
            "bank_code": o.get("bank_code", form["bank_code"]), "issue_date": "01 October 2026"},
    }


SCENARIOS = {
    "01_happy_path_gb": {
        "description": "Everything complete and consistent. Expect: Approved (awaiting authorisation).",
        "expected_recommendation": "Approved",
        "form": GB_HAPPY, "scanned": [], "documents": company_docs(GB_HAPPY)},
    "02_bank_holder_mismatch_gb": {
        "description": "Bank letter is in a different person's name. Expect: Pending, critical.",
        "expected_recommendation": "Pending",
        "form": {**GB_HAPPY, "vendor_name": "Brightline Test Components Ltd",
                 "registration_number": "11223344",
                 "bank_account_holder": "Brightline Test Components Ltd",
                 "contact_email": "ops@brightline-test.example"},
        "scanned": [],
        "documents": None},  # filled below
    "03_scanned_tax_doc_in": {
        "description": "Tax certificate is a scanned image (no text). Expect: Pending, OCR needed.",
        "expected_recommendation": "Pending",
        "form": {"vendor_name": "Sitara Test Textiles Pvt Ltd", "vendor_type": "company",
                 "country": "IN", "registration_number": "U17110MH2019PTC123456",
                 "tax_id": "27AAPFU0939F1ZV", "tax_id_type": "GSTIN",
                 "address_line": "4 Sample Mill Road", "city": "Mumbai", "postal_code": "400001",
                 "contact_name": "Ravi Iyer", "contact_email": "ravi@sitara-test.example",
                 "contact_phone": "+91 22 0000 0000", "bank_country": "IN",
                 "bank_account_holder": "Sitara Test Textiles Pvt Ltd",
                 "bank_account_number": "50100123456789", "bank_code": "HDFC0001234"},
        "scanned": ["tax_registration"], "documents": None},
    "04_tax_id_mismatch_de": {
        "description": "VAT number on the certificate differs from the form. Expect: Pending, critical.",
        "expected_recommendation": "Pending",
        "form": {"vendor_name": "Rheinwerk Test GmbH", "vendor_type": "company", "country": "DE",
                 "registration_number": "HRB 123456", "tax_id": "DE123456789", "tax_id_type": "VAT",
                 "address_line": "Beispielstrasse 5", "city": "Koeln", "postal_code": "50667",
                 "contact_name": "Lena Vogel", "contact_email": "lena@rheinwerk-test.example",
                 "contact_phone": "+49 221 000000", "bank_country": "DE",
                 "bank_account_holder": "Rheinwerk Test GmbH",
                 "bank_account_number": "DE89370400440532013000", "bank_code": "COBADEFFXXX"},
        "scanned": [], "documents": None},
    "05_incomplete_us": {
        "description": "Tax ID missing and only one document uploaded. Expect: Pending, missing info.",
        "expected_recommendation": "Pending",
        "form": {"vendor_name": "Lakeside Test Logistics LLC", "vendor_type": "company",
                 "country": "US", "registration_number": "C1234567", "tax_id": "",
                 "tax_id_type": "EIN", "address_line": "77 Sample Ave", "city": "Chicago",
                 "postal_code": "60601", "contact_name": "Sam Ortiz",
                 "contact_email": "sam@lakeside-test.example", "contact_phone": "+1 312 000 0000",
                 "bank_country": "US", "bank_account_holder": "Lakeside Test Logistics LLC",
                 "bank_account_number": "000123456789", "bank_code": "021000021"},
        "scanned": [], "documents": None, "only_docs": ["business_registration"]},
    "06_blocked_party": {
        "description": "Name is on the synthetic blocked-party list. Expect: Rejected (to confirm).",
        "expected_recommendation": "Rejected",
        "form": {**GB_HAPPY, "vendor_name": "Blocked Test Vendor Ltd",
                 "bank_account_holder": "Blocked Test Vendor Ltd",
                 "contact_email": "info@blocked-test.example"},
        "scanned": [], "documents": None},
}

SCENARIOS["02_bank_holder_mismatch_gb"]["documents"] = company_docs(
    SCENARIOS["02_bank_holder_mismatch_gb"]["form"],
    {"bank_account_holder": "J. Harper Consulting"})
SCENARIOS["03_scanned_tax_doc_in"]["documents"] = company_docs(SCENARIOS["03_scanned_tax_doc_in"]["form"])
SCENARIOS["04_tax_id_mismatch_de"]["documents"] = company_docs(
    SCENARIOS["04_tax_id_mismatch_de"]["form"], {"tax_id": "DE987654321"})
SCENARIOS["05_incomplete_us"]["documents"] = {
    k: v for k, v in company_docs(SCENARIOS["05_incomplete_us"]["form"]).items()
    if k in SCENARIOS["05_incomplete_us"]["only_docs"]}
SCENARIOS["06_blocked_party"]["documents"] = company_docs(SCENARIOS["06_blocked_party"]["form"])


# ---------------- Harder documents: messy layouts and a blurry scan ----------------
# These are what a pattern matcher cannot read, so they show what the AI adds.
# "needs_ai": the expected outcome assumes AI extraction is switched on.

HARBOUR = {
    "vendor_name": "Harbour Test Foods Ltd", "vendor_type": "company", "country": "GB",
    "registration_number": "12345678", "tax_id": "GB987654321", "tax_id_type": "VAT",
    "address_line": "8 Quay Side", "city": "Bristol", "postal_code": "BS1 4XY",
    "contact_name": "Mia Clarke", "contact_email": "mia@harbour-test.example",
    "contact_phone": "+44 117 000 0000", "bank_country": "GB",
    "bank_account_holder": "Harbour Test Foods Ltd",
    "bank_account_number": "GB29NWBK60161331926819", "bank_code": "NWBKGB2L",
}
COPPERLEAF = {**HARBOUR, "vendor_name": "Copperleaf Test Studio Ltd", "registration_number": "87654321",
              "tax_id": "GB123987456", "address_line": "21 Sample Row", "city": "Leeds",
              "postal_code": "LS1 5AB", "contact_name": "Owen Hart",
              "contact_email": "owen@copperleaf-test.example",
              "bank_account_holder": "Copperleaf Test Studio Ltd"}
NORDLICHT = {
    "vendor_name": "Nordlicht Test Logistik GmbH", "vendor_type": "company", "country": "DE",
    "registration_number": "HRB 654321", "tax_id": "DE234567891", "tax_id_type": "VAT",
    "address_line": "Hafenweg 12", "city": "Hamburg", "postal_code": "20457",
    "contact_name": "Jonas Weber", "contact_email": "jonas@nordlicht-test.example",
    "contact_phone": "+49 40 000000", "bank_country": "DE",
    "bank_account_holder": "Nordlicht Test Logistik GmbH",
    "bank_account_number": "DE89370400440532013000", "bank_code": "COBADEFFXXX",
}


def messy_docs(form: dict, reg_name: str | None = None) -> dict:
    """Truth values exactly as printed in the messy documents."""
    spaced_iban = " ".join(form["bank_account_number"][i:i + 4]
                           for i in range(0, len(form["bank_account_number"]), 4))
    return {
        "business_registration": {
            "company_name": reg_name or form["vendor_name"],
            "registration_number": form["registration_number"],
            "address": f"{form['address_line']}, {form['city']} {form['postal_code']}",
            "issue_date": "21 June 2019"},
        "tax_registration": {
            "company_name": form["vendor_name"].upper(),
            "tax_id": form["tax_id"][:2] + " " + form["tax_id"][2:5] + " " + form["tax_id"][5:9]
                      + " " + form["tax_id"][9:],
            "issue_date": "4 July 2019"},
        "bank_evidence": {
            "bank_account_holder": form["bank_account_holder"],
            "bank_account_number": spaced_iban,
            "bank_code": form["bank_code"], "issue_date": "2 November 2026"},
    }


SCENARIOS.update({
    "07_messy_layouts_gb": {
        "description": "Consistent, but in messy layouts (table, sentence, letter). "
                       "Expect with AI: Approved (awaiting authorisation).",
        "expected_recommendation": "Approved", "needs_ai": True, "layout": "messy",
        "form": HARBOUR, "scanned": [], "documents": messy_docs(HARBOUR)},
    "08_blurry_scan_gb": {
        "description": "Bank letter is a blurry scan. Expect with AI: Pending, scan to confirm.",
        "expected_recommendation": "Pending", "needs_ai": True, "layout": "messy",
        "form": COPPERLEAF, "scanned": ["bank_evidence"], "blurry": True,
        "documents": messy_docs(COPPERLEAF)},
    "09_entity_mismatch_de": {
        "description": "Registration table names a different legal entity. "
                       "Expect with AI: Pending, critical.",
        "expected_recommendation": "Pending", "needs_ai": True, "layout": "messy",
        "form": NORDLICHT, "scanned": [],
        "documents": messy_docs(NORDLICHT, reg_name="Nordlicht Test Holding GmbH")},
})

TITLES = {
    "business_registration": ("CERTIFICATE OF INCORPORATION", "Issued by: Example Companies Registry (SYNTHETIC)"),
    "tax_registration": ("TAX REGISTRATION CERTIFICATE", "Issued by: Example Tax Office (SYNTHETIC)"),
    "bank_evidence": ("BANK ACCOUNT CONFIRMATION LETTER", "Example Bank plc (SYNTHETIC)"),
}
LINE_LABELS = {
    "company_name": "Company name", "registration_number": "Company number",
    "address": "Registered office address", "issue_date": "Date of issue",
    "tax_id": "Tax ID", "bank_account_holder": "Account holder",
    "bank_account_number": "Account number", "bank_code": "Bank code",
}


def write_pdf(path: Path, doc_type: str, fields: dict, scanned: bool) -> None:
    title, issuer = TITLES[doc_type]
    lines = [title, issuer, "", "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD", ""]
    lines += [f"{LINE_LABELS[k]}: {v}" for k, v in fields.items()]
    lines += ["", "This document was generated for software testing only."]

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4
    y = 80
    for i, line in enumerate(lines):
        page.insert_text((60, y), line, fontsize=16 if i == 0 else 11)
        y += 26 if i == 0 else 18

    save(doc, path, scanned)


def save(doc, path: Path, scanned: bool, dpi: int = 110) -> None:
    """Save normally, or as a 'scan': a picture of the page with no text layer.
    A low dpi makes the scan blurry."""
    if scanned:
        img_doc = pymupdf.open()
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img_page = img_doc.new_page(width=595, height=842)
            img_page.insert_image(img_page.rect, pixmap=pix)
        img_doc.save(path)
        img_doc.close()
    else:
        doc.save(path)
    doc.close()


def write_messy(path: Path, doc_type: str, f: dict, scanned: bool, dpi: int) -> None:
    """Realistic layouts: a registry table, a sentence-style certificate, a bank letter."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    synthetic = "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD"
    if doc_type == "business_registration":
        page.insert_text((60, 80), "Companies Registry (SYNTHETIC)", fontsize=10)
        page.insert_text((60, 110), "Extract of company details", fontsize=17)
        page.insert_text((60, 130), synthetic, fontsize=8)
        rows = [("Registered name", f["company_name"]), ("Company no.", f["registration_number"]),
                ("Registered office", f["address"]), ("Incorporated on", f["issue_date"]),
                ("Status", "Active")]
        y = 160
        for label, value in rows:  # two-column table with ruled lines, no colons
            page.draw_rect(pymupdf.Rect(60, y, 535, y + 30), color=(0.6, 0.6, 0.6), width=0.6)
            page.draw_line((220, y), (220, y + 30), color=(0.6, 0.6, 0.6), width=0.6)
            page.insert_text((68, y + 19), label, fontsize=10)
            page.insert_text((228, y + 19), value, fontsize=10)
            y += 30
    elif doc_type == "tax_registration":
        page.insert_text((60, 80), "Example Tax Office (SYNTHETIC)", fontsize=10)
        page.insert_text((60, 112), "VAT Registration", fontsize=17)
        page.insert_text((60, 132), synthetic, fontsize=8)
        body = (f"This is to certify that {f['company_name']} is registered for Value Added Tax "
                f"under registration number {f['tax_id']} with effect from 1 July 2019. "
                "Please quote this number on all invoices and correspondence.")
        page.insert_textbox(pymupdf.Rect(60, 160, 535, 300), body, fontsize=11)
        page.insert_text((60, 330), f"Issued: {f['issue_date']}", fontsize=10)
    elif doc_type == "bank_evidence":
        page.insert_text((60, 80), "Example Bank plc (SYNTHETIC) - Business Banking", fontsize=10)
        page.insert_text((400, 110), f["issue_date"], fontsize=10)
        page.insert_text((60, 130), synthetic, fontsize=8)
        body = ("Dear Sir or Madam,\n\n"
                f"We are pleased to confirm that {f['bank_account_holder']} maintains a business "
                "current account with us, opened in 2019 and in good standing. For payments, "
                f"please use the International Bank Account Number {f['bank_account_number']}; "
                f"our BIC is {f['bank_code']}.\n\n"
                "This letter is provided at the request of our customer and does not constitute "
                "a guarantee.\n\nYours faithfully,\n\nBusiness Banking Team")
        page.insert_textbox(pymupdf.Rect(60, 160, 535, 520), body, fontsize=11)
    save(doc, path, scanned, dpi)


def main() -> None:
    for name, sc in SCENARIOS.items():
        folder = HERE / name
        folder.mkdir(exist_ok=True)
        for doc_type, fields in sc["documents"].items():
            scanned = doc_type in sc["scanned"]
            if sc.get("layout") == "messy":
                write_messy(folder / f"{doc_type}.pdf", doc_type, fields, scanned,
                            dpi=60 if sc.get("blurry") else 110)
            else:
                write_pdf(folder / f"{doc_type}.pdf", doc_type, fields, scanned)
    (HERE / "scenarios.json").write_text(json.dumps(SCENARIOS, indent=2))
    print(f"Created {len(SCENARIOS)} synthetic scenarios in {HERE}")
    for name, sc in SCENARIOS.items():
        print(f"  {name}: {len(sc['documents'])} PDF(s) - {sc['description']}")


if __name__ == "__main__":
    main()
