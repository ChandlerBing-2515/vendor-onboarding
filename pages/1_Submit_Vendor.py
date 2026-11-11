"""Submission form, PDF uploads and the live run view."""

import streamlit as st

from components import open_vendor, page_header, setup, show_actions, status_badge
from core import database as db
from core.models import DOC_LABELS, DocumentType, VendorSubmission, VendorType
from core.pipeline import run_checks
from core.samples import load_scenarios, sample_files
from core.storage import save_upload

setup("Submit Vendor")
page_header("Submit a vendor",
            "Use synthetic test data only. Everything entered is checked, not assumed to be true.")

FIELDS = list(VendorSubmission.model_fields)

# ---------- optional: fill the form from a synthetic sample ----------
scenarios = load_scenarios()
with st.expander("Demo: fill the form with a synthetic sample", expanded=not st.session_state.get("sample_name")):
    if not scenarios:
        st.warning("No samples yet. In the terminal run:  python sample_data/make_samples.py")
    else:
        choice = st.selectbox("Sample scenario", list(scenarios),
                              format_func=lambda n: f"{n} – {scenarios[n]['description']}")
        if st.button("Load sample"):
            for field, value in scenarios[choice]["form"].items():
                st.session_state[f"f_{field}"] = value
            st.session_state["sample_name"] = choice
            st.rerun()

sample_name = st.session_state.get("sample_name")


def text(field: str, label: str, **kw) -> str:
    return st.text_input(label, key=f"f_{field}", **kw)


# ---------- the form ----------
with st.form("vendor_form"):
    st.subheader("Company")
    c1, c2, c3 = st.columns(3)
    with c1:
        text("vendor_name", "Vendor / company name *")
        st.selectbox("Vendor type *", [t.value for t in VendorType], key="f_vendor_type")
    with c2:
        text("country", "Country of registration * (2-letter code, e.g. GB)", max_chars=2)
        text("registration_number", "Company registration number (companies)")
    with c3:
        text("tax_id", "Tax ID *")
        text("tax_id_type", "Tax ID type * (VAT, GSTIN, PAN, EIN)")

    st.subheader("Address and contact")
    c1, c2, c3 = st.columns(3)
    with c1:
        text("address_line", "Street address *")
        text("city", "City *")
        text("postal_code", "Postal code *")
    with c2:
        text("contact_name", "Contact person")
        text("contact_email", "Contact email *")
        text("contact_phone", "Contact phone")
    with c3:
        text("bank_country", "Bank country * (2-letter code)", max_chars=2)
        text("bank_account_holder", "Bank account holder name *")
        text("bank_account_number", "Account number / IBAN *")
        text("bank_code", "Bank code (SWIFT/BIC, IFSC, routing no.)")

    st.subheader("Documents (PDF, max 10 MB each)")
    uploads = {}
    cols = st.columns(len(DocumentType))
    for col, doc_type in zip(cols, DocumentType):
        with col:
            uploads[doc_type] = st.file_uploader(DOC_LABELS[doc_type], type=["pdf"],
                                                 key=f"up_{doc_type.value}")
    attach_sample = False
    if sample_name:
        names = ", ".join(p.name for _, p in sample_files(sample_name))
        attach_sample = st.checkbox(f"Also attach the sample PDFs for '{sample_name}' ({names})",
                                    value=True)

    submitted = st.form_submit_button("Submit and run checks", type="primary")

# ---------- on submit: save, then run every stage live ----------
if submitted:
    raw = {f: st.session_state.get(f"f_{f}", "") for f in FIELDS}
    raw["country"] = raw["country"].upper().strip()
    raw["bank_country"] = raw["bank_country"].upper().strip()
    submission = VendorSubmission(**{k: (v.strip() if isinstance(v, str) else v)
                                     for k, v in raw.items()})

    with st.status("Processing submission…", expanded=True) as status:
        vendor_id = db.create_vendor(submission)
        st.write(f"✓ Saved submission as vendor #{vendor_id}")

        files = [(t, f.name, f.getvalue()) for t, f in uploads.items() if f is not None]
        if attach_sample:
            uploaded_types = {t for t, _, _ in files}
            files += [(t, p.name, p.read_bytes()) for t, p in sample_files(sample_name)
                      if t not in uploaded_types]
        for doc_type, name, data in files:
            try:
                db.add_document(vendor_id, save_upload(vendor_id, doc_type, name, data))
                st.write(f"✓ Stored {name} as {DOC_LABELS[doc_type].lower()}")
            except ValueError as exc:
                st.write(f"✗ {exc}")

        rec = run_checks(vendor_id, progress=lambda msg: st.write(f"✓ {msg}"))
        status.update(label=f"Done: system recommends {rec.status.value}", state="complete",
                      expanded=True)

    st.session_state.pop("sample_name", None)
    st.session_state["last_submitted"] = vendor_id

# ---------- result of the last submission ----------
last = st.session_state.get("last_submitted")
if last:
    vendor = db.get_vendor(last)
    rec = vendor["recommendation"]
    with st.container(border=True):
        st.subheader(f"Result for {vendor['vendor_name']}")
        status_badge(rec.status.value, "System recommendation: ")
        st.write(f"**{rec.headline}**")
        show_actions(rec)
        if st.button("Open full vendor record", type="primary"):
            open_vendor(last)
