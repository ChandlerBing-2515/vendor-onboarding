"""Submission: upload documents, optionally auto-fill the form from them,
check the details, then submit and watch every stage run live."""

import hashlib

import streamlit as st

from components import open_vendor, page_header, setup, show_actions, status_badge
from core import database as db
from core.autofill import suggest
from core.models import DOC_LABELS, DocumentType, VendorSubmission, VendorType
from core.pipeline import read_upload, run_checks
from core.samples import load_scenarios, sample_files
from core.storage import save_upload
from core.validation import COUNTRY_NAMES, COUNTRY_RULES, tax_types_for

setup("Submit Vendor")
page_header("Submit a vendor",
            "Upload the documents, let the system fill what it can, check the details, then "
            "submit. Use synthetic test data only.")

FORM_FIELDS = [f for f in VendorSubmission.model_fields if f != "autofilled"]
OTHER = "Other…"


# ---------- helpers that write values into the form's widgets ----------

def set_form_value(field: str, value: str) -> None:
    """Put a value into the right widget(s) for a form field (before they are drawn)."""
    if field in ("country", "bank_country"):
        listed = value in COUNTRY_NAMES or value == ""
        st.session_state[f"{field}_choice"] = (value or None) if listed else OTHER
        st.session_state[f"{field}_other"] = "" if listed else value
    elif field == "tax_id_type":
        country = current_country("country")
        listed = value in tax_types_for(country) or value == ""
        st.session_state["tax_type_choice"] = (value or None) if listed else OTHER
        st.session_state["tax_type_other"] = "" if listed else value
    else:
        st.session_state[f"f_{field}"] = value


def current_country(key: str) -> str:
    choice = st.session_state.get(f"{key}_choice")
    if choice == OTHER:
        return st.session_state.get(f"{key}_other", "").strip().upper()
    return choice or ""


def current_values() -> dict:
    values = {f: st.session_state.get(f"f_{f}", "") for f in FORM_FIELDS}
    values["vendor_type"] = values["vendor_type"] or VendorType.COMPANY.value
    values["country"] = current_country("country")
    values["bank_country"] = current_country("bank_country")
    tax_choice = st.session_state.get("tax_type_choice")
    values["tax_id_type"] = (st.session_state.get("tax_type_other", "").strip()
                             if tax_choice == OTHER else tax_choice or "")
    return values


# Values queued by "Load sample" or "Fill from documents" are applied here,
# at the top of the run, before any widget is drawn. Country goes first so the
# tax ID type list matches it.
pending = st.session_state.pop("pending_values", {})
for field in sorted(pending, key=lambda f: f != "country"):
    set_form_value(field, pending[field])


# ---------- optional: fill the form with a synthetic sample ----------
scenarios = load_scenarios()
with st.expander("Demo: use a synthetic sample", expanded=not st.session_state.get("sample_name")):
    if not scenarios:
        st.warning("No samples yet. In the terminal run:  python sample_data/make_samples.py")
    else:
        choice = st.selectbox("Sample scenario", list(scenarios),
                              format_func=lambda n: f"{n} – {scenarios[n]['description']}")
        c1, c2 = st.columns(2)
        if c1.button("Load sample (form + PDFs)"):
            st.session_state["pending_values"] = dict(scenarios[choice]["form"])
            st.session_state["sample_name"] = choice
            st.session_state.pop("autofill", None)
            st.rerun()
        if c2.button("Load sample PDFs only (empty form)",
                     help="Try auto-fill: the form stays empty, then use "
                          "'Fill empty fields from these documents'."):
            st.session_state["pending_values"] = {f: "" for f in FORM_FIELDS if f != "vendor_type"}
            st.session_state["sample_name"] = choice
            st.session_state.pop("autofill", None)
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


def chosen_files() -> list[tuple[DocumentType, str, bytes]]:
    """Uploaded PDFs, plus the sample's PDFs for any slot left empty."""
    files = []
    for doc_type in DocumentType:
        up = st.session_state.get(f"up_{doc_type.value}")
        if up is not None:
            files.append((doc_type, up.name, up.getvalue()))
    if sample_name and st.session_state.get("attach_sample", True):
        have = {t for t, _, _ in files}
        files += [(t, p.name, p.read_bytes()) for t, p in sample_files(sample_name)
                  if t not in have]
    return files


def file_key(doc_type: DocumentType, data: bytes) -> str:
    return f"{doc_type.value}:{hashlib.sha1(data).hexdigest()}"


# ---------- 1. Documents ----------
# Not an st.form on purpose: the tax ID types must follow the country straight away,
# and "Other…" must open its text box as soon as it is chosen.
with st.container(border=True):
    st.subheader("1. Documents (PDF, max 10 MB each)")
    cols = st.columns(len(DocumentType))
    for col, doc_type in zip(cols, DocumentType):
        with col:
            st.file_uploader(DOC_LABELS[doc_type], type=["pdf"], key=f"up_{doc_type.value}")
    if sample_name:
        names = ", ".join(p.name for _, p in sample_files(sample_name))
        st.checkbox(f"Use the sample PDFs for '{sample_name}' in empty slots ({names})",
                    value=True, key="attach_sample")

    files = chosen_files()
    fill = st.button("Fill empty fields from these documents", icon=":material/auto_fix_high:",
                     disabled=not files,
                     help="Reads the documents and fills only the fields that are still empty. "
                          "Nothing you have typed is changed.")
    if fill:
        cache = st.session_state.setdefault("read_cache", {})
        with st.status("Reading documents to fill the form…", expanded=True) as status:
            extractions = []
            for doc_type, name, data in files:
                key = file_key(doc_type, data)
                if key not in cache:
                    st.write(f"Reading {name}…")
                    cache[key] = read_upload(data, doc_type, name)
                ex = cache[key]
                if ex.readable:
                    st.write(f"✓ {name} read ({ex.method})")
                else:
                    st.write(f"✗ {name}: {ex.problem}")
                extractions.append(ex)
            fills, notes = suggest(extractions, current_values())
            status.update(label=f"Filled {len(fills)} empty field(s)", state="complete",
                          expanded=False)
        st.session_state["autofill"] = {"fills": fills, "notes": notes}
        st.session_state["pending_values"] = {f: v for f, (v, _, _) in fills.items()}
        st.rerun()

    af = st.session_state.get("autofill")
    if af:
        if af["fills"]:
            st.info(f"Filled {len(af['fills'])} field(s) from the documents. "
                    "**Check them before submitting**: they are what the documents say, "
                    "not verified facts.", icon=":material/info:")
            st.caption(" · ".join(f"{f.replace('_', ' ')} ← {src}"
                                  for f, (_, _, src) in af["fills"].items()))
        else:
            st.warning("No empty fields could be filled from these documents.")
        for note in af["notes"]:
            st.caption(note)

# ---------- 2. Vendor details ----------
with st.container(border=True):
    st.subheader("2. Vendor details")
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

    st.markdown("**Address and contact**")
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

    submitted = st.button("Submit and run checks", type="primary")

# ---------- on submit: save, then run every stage live ----------
if submitted:
    raw = {k: (v.strip() if isinstance(v, str) else v) for k, v in current_values().items()}
    # Remember which values still equal what auto-fill put there (not edited since)
    fills = (st.session_state.get("autofill") or {}).get("fills", {})
    raw["autofilled"] = {f: src for f, (val, src, _) in fills.items()
                         if str(raw.get(f, "")).strip() == str(val).strip()}
    raw["autofill_edited"] = [f for f in fills if f not in raw["autofilled"]]
    submission = VendorSubmission(**raw)

    with st.status("Processing submission…", expanded=True) as status:
        vendor_id = db.create_vendor(submission)
        st.write(f"✓ Saved submission as vendor #{vendor_id}")
        if submission.autofilled:
            st.write(f"✓ {len(submission.autofilled)} field(s) were auto-filled from documents "
                     "and confirmed by the submitter")

        cache = st.session_state.get("read_cache", {})
        reused = False
        for doc_type, name, data in chosen_files():
            try:
                doc_id = db.add_document(vendor_id, save_upload(vendor_id, doc_type, name, data))
                st.write(f"✓ Stored {name} as {DOC_LABELS[doc_type].lower()}")
                earlier = cache.get(file_key(doc_type, data))
                if earlier is not None:   # already read during auto-fill: don't pay twice
                    db.save_extraction(doc_id, earlier.model_copy(
                        update={"document_id": doc_id, "filename": name}))
                    reused = True
            except ValueError as exc:
                st.write(f"✗ {exc}")

        rec = run_checks(vendor_id, progress=lambda msg: st.write(f"✓ {msg}"),
                         reextract=not reused)
        status.update(label=f"Done: system recommends {rec.status.value}", state="complete",
                      expanded=True)

    for key in ("sample_name", "autofill", "read_cache"):
        st.session_state.pop(key, None)
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
