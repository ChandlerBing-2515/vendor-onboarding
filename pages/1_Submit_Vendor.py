"""Submission form, PDF uploads and the live run view."""

import streamlit as st

from components import open_vendor, page_header, setup, show_actions, status_badge
from core import database as db
from core.models import DOC_LABELS, DocumentType, VendorSubmission, VendorType
from core.pipeline import run_checks
from core.samples import load_scenarios, sample_files
from core.storage import save_upload
from core.validation import COUNTRY_NAMES, COUNTRY_RULES, tax_types_for

setup("Submit Vendor")
page_header("Submit a vendor",
            "Use synthetic test data only. Everything entered is checked, not assumed to be true.")

FIELDS = list(VendorSubmission.model_fields)
OTHER = "Other…"

# ---------- optional: fill the form from a synthetic sample ----------
scenarios = load_scenarios()
with st.expander("Demo: fill the form with a synthetic sample", expanded=not st.session_state.get("sample_name")):
    if not scenarios:
        st.warning("No samples yet. In the terminal run:  python sample_data/make_samples.py")
    else:
        choice = st.selectbox("Sample scenario", list(scenarios),
                              format_func=lambda n: f"{n} – {scenarios[n]['description']}")
        if st.button("Load sample"):
            form = scenarios[choice]["form"]
            for field, value in form.items():
                st.session_state[f"f_{field}"] = value
            # dropdowns: pick the listed option, or "Other…" plus the typed value
            for field in ("country", "bank_country"):
                code = form.get(field, "")
                st.session_state[f"{field}_choice"] = code if code in COUNTRY_NAMES else OTHER
                st.session_state[f"{field}_other"] = "" if code in COUNTRY_NAMES else code
            tax_type = form.get("tax_id_type", "")
            listed = tax_type in tax_types_for(form.get("country", ""))
            st.session_state["tax_type_choice"] = tax_type if listed else OTHER
            st.session_state["tax_type_other"] = "" if listed else tax_type
            st.session_state["sample_name"] = choice
            st.rerun()

sample_name = st.session_state.get("sample_name")


def text(field: str, label: str, **kw) -> str:
    return st.text_input(label, key=f"f_{field}", **kw)


def country_picker(label: str, key: str) -> str:
    """Dropdown of countries plus 'Other…' with a free-text code. Returns e.g. 'GB'."""
    options = list(COUNTRY_NAMES) + [OTHER]
    choice = st.selectbox(label, options, index=None, key=f"{key}_choice",
                          placeholder="Choose a country",
                          format_func=lambda c: c if c == OTHER else f"{COUNTRY_NAMES[c]} ({c})")
    if choice == OTHER:
        code = st.text_input("Country code (2 letters, e.g. KE)", key=f"{key}_other",
                             max_chars=2).strip().upper()
    else:
        code = choice or ""
    if code and code not in COUNTRY_RULES:
        st.caption(f":orange[No rules configured for {COUNTRY_NAMES.get(code, code)}: "
                   "this will be sent to a specialist.]")
    return code


def tax_type_picker(country: str) -> str:
    """Tax ID types for the chosen country, plus 'Other…'."""
    options = tax_types_for(country) + [OTHER]
    if st.session_state.get("tax_type_choice") not in options:
        st.session_state["tax_type_choice"] = None   # country changed: reset
    choice = st.selectbox("Tax ID type *", options, index=None, key="tax_type_choice",
                          placeholder="Choose the tax ID type")
    if choice == OTHER:
        return st.text_input("Tax ID type name", key="tax_type_other").strip()
    return choice or ""


# ---------- the form ----------
# Not an st.form on purpose: the tax ID types must update as soon as the
# country changes, and "Other…" must open its text box straight away.
with st.container(border=True):
    st.subheader("Company")
    c1, c2, c3 = st.columns(3)
    with c1:
        text("vendor_name", "Vendor / company name *")
        st.selectbox("Vendor type *", [t.value for t in VendorType], key="f_vendor_type")
    with c2:
        country = country_picker("Country of registration *", "country")
        text("registration_number", "Company registration number (companies)")
    with c3:
        text("tax_id", "Tax ID *")
        tax_id_type = tax_type_picker(country)

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
        bank_country = country_picker("Bank country *", "bank_country")
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

    submitted = st.button("Submit and run checks", type="primary")

# ---------- on submit: save, then run every stage live ----------
if submitted:
    raw = {f: st.session_state.get(f"f_{f}", "") for f in FIELDS}
    raw["country"], raw["bank_country"], raw["tax_id_type"] = country, bank_country, tax_id_type
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
