"""One vendor: summary, form vs documents, checks, documents, review actions, history."""

from pathlib import Path

import pandas as pd
import streamlit as st

from components import (
    STATE_LABELS, STATUS_COLORS, badge_md, page_header, setup, show_actions, show_finding,
)
from core import database as db, feedback
from core.decision import NOT_VERIFIED, open_issues
from core.models import (
    DOC_LABELS, EXTRACTED_FIELD_NAMES, DocumentType, ReviewAction, Severity, Status,
    VendorSubmission,
)
from core.pipeline import run_checks
from core.storage import save_upload
from core.validation import FIELD_LABELS

setup("Vendor Detail")

vendors = db.list_vendors()
if not vendors:
    st.info("No vendors yet.")
    st.stop()

ids = [v["id"] for v in vendors]
names = {v["id"]: f"#{v['id']} {v['vendor_name']} ({v['status']})" for v in vendors}
wanted = st.session_state.get("selected_vendor_id", ids[0])
vendor_id = st.selectbox("Choose a vendor", ids, index=ids.index(wanted) if wanted in ids else 0,
                         format_func=names.get)
st.session_state["selected_vendor_id"] = vendor_id

v = db.get_vendor(vendor_id)
rec, s = v["recommendation"], v["submission"]
reliability = feedback.check_reliability()

# ---------- header ----------
page_header(v["vendor_name"], f"Vendor #{v['id']} · submitted {v['created_at'][:16].replace('T', ' ')} UTC")
badges = [badge_md(f"Status: {v['status']}", STATUS_COLORS[v["status"]])]
if rec:
    badges.append(badge_md(f"System recommends: {rec.status.value}", STATUS_COLORS[rec.status.value]))
badges.append(badge_md(STATE_LABELS.get(v["review_state"], v["review_state"]), "gray"))
st.markdown(" &nbsp; ".join(badges))

if rec is None:
    st.warning("Checks have not run for this vendor.")
    if st.button("Run checks now"):
        run_checks(vendor_id)
        st.rerun()
    st.stop()

with st.expander("What this system does NOT verify"):
    for item in NOT_VERIFIED:
        st.markdown(f"- {item}")

tabs = st.tabs(["Summary", "Form vs documents", "All checks", "Documents & extraction",
                "Review", "History"])

# ---------- Summary ----------
with tabs[0]:
    st.subheader(rec.headline)
    issues = open_issues(v["findings"])
    c = st.columns(4)
    c[0].metric("Checks run", len(v["findings"]), border=True)
    c[1].metric("Open issues", len(issues), border=True)
    c[2].metric("Critical", sum(f.severity == Severity.CRITICAL for f in issues), border=True)
    c[3].metric("Documents", len(v["documents"]), border=True)
    show_actions(rec)
    st.markdown("**Why**")
    st.markdown("\n".join(f"- {r}" for r in rec.reasons))

# ---------- Form vs documents ----------
with tabs[1]:
    comps = [f for f in v["findings"] if f.check_id.startswith("compare.")
             or f.check_id.startswith("document.readable")]
    if not comps:
        st.info("No documents were compared.")
    else:
        st.dataframe(pd.DataFrame([{
            "Result": {"pass": "✅ match", "fail": "❌ mismatch",
                       "needs_review": "⚠️ check"}[f.outcome.value],
            "Check": f.label, "Severity": f.severity.value, "Details": f.message,
            "Evidence": f.evidence, "Source": f.source} for f in comps]),
            hide_index=True)
    st.caption("A match means the document says the same as the form. It does not prove the "
               "document is genuine.")

# ---------- All checks ----------
with tabs[2]:
    show = st.radio("Show", ["Open issues", "All checks"], horizontal=True)
    for f in (issues if show == "Open issues" else v["findings"]):
        show_finding(f, reliability)
    if show == "Open issues" and not issues:
        st.success("No open issues.")

# ---------- Documents ----------
with tabs[3]:
    if not v["documents"]:
        st.info("No documents uploaded.")
    for d in v["documents"]:
        ex = d["extraction"]
        with st.container(border=True):
            st.markdown(f"**{DOC_LABELS[DocumentType(d['doc_type'])]}** · {d['original_filename']} "
                        f"· {d['size_bytes'] / 1024:.0f} KB")
            path = Path(d["stored_path"])
            if path.exists():
                st.download_button("Download PDF", path.read_bytes(), file_name=d["original_filename"],
                                   mime="application/pdf", key=f"dl_{d['id']}")
            else:
                st.warning("File no longer on disk (expected on cloud hosting after a restart).")
            if ex is None:
                st.write("Not read yet.")
            elif not ex.readable:
                st.error(f"Unreadable: {ex.problem}")
            else:
                if ex.read_from_images:
                    st.warning("Scanned document read by AI from page images. Confirm these values "
                               "against the PDF before relying on them.")
                st.caption(f"Read with {ex.method} · {ex.page_count} page(s) · {ex.text_chars} characters")
                st.dataframe(pd.DataFrame([{
                    "Field": name, "Value": getattr(ex.fields, name).value,
                    "Confidence": getattr(ex.fields, name).confidence,
                    "Page": getattr(ex.fields, name).page,
                    "Quote from document": getattr(ex.fields, name).evidence_quote,
                } for name in EXTRACTED_FIELD_NAMES if getattr(ex.fields, name).value]),
                    hide_index=True)
                if ex.fields.notes:
                    st.caption(f"Notes: {ex.fields.notes}")

# ---------- Review ----------
with tabs[4]:
    if v["review_state"] == db.DECIDED:
        st.info(f"This case was decided: {v['status']}. A new review will be added to the history.")

    st.subheader("Reviewer decision")
    readable_docs = [d for d in v["documents"] if d["extraction"] and d["extraction"].readable]
    correction_rows = [{
        "document_id": d["id"], "Document": d["original_filename"], "doc_type": d["doc_type"],
        "Field": name, "Extracted": getattr(d["extraction"].fields, name).value or "",
        "Correct value": getattr(d["extraction"].fields, name).value or "",
    } for d in readable_docs for name in EXTRACTED_FIELD_NAMES]

    with st.form("review_form"):
        reviewer = st.text_input("Your name *")
        action = st.radio("Decision", [a.value for a in ReviewAction], horizontal=True,
                          format_func=lambda a: {"approve": "Approve", "request_info": "Request information",
                                                 "reject": "Reject", "escalate": "Escalate"}[a])
        reason = st.text_area("Reason (required unless you approve a case the system also "
                              "recommends approving)")
        wrong = st.multiselect(
            "Which flagged checks were wrong? (feeds the learning metrics)",
            [f.check_id for f in issues], format_func=lambda cid: next(
                f.label for f in issues if f.check_id == cid))
        st.markdown("**Correct extracted values** (edit the 'Correct value' column only)")
        if correction_rows:
            edited = st.data_editor(
                pd.DataFrame(correction_rows), hide_index=True,
                disabled=["Document", "Field", "Extracted"],
                column_order=["Document", "Field", "Extracted", "Correct value"],
                key="corr_editor")
        else:
            st.caption("Nothing to correct: no values were extracted, because this vendor has "
                       "no readable documents.")
            edited = pd.DataFrame(columns=["document_id", "doc_type", "Field", "Extracted",
                                           "Correct value"])
        has_critical = any(f.severity == Severity.CRITICAL for f in issues)
        confirm = st.checkbox("I have manually checked every open critical issue") if has_critical else True
        save = st.form_submit_button("Save decision", type="primary")

    if save:
        act = ReviewAction(action)
        corrections = [{
            "document_id": int(r["document_id"]), "doc_type": r["doc_type"], "field_name": r["Field"],
            "extracted_value": r["Extracted"] or None, "corrected_value": str(r["Correct value"]).strip(),
        } for _, r in edited.iterrows()
            if str(r["Correct value"]).strip() and str(r["Correct value"]).strip() != r["Extracted"]]
        if act == ReviewAction.APPROVE and has_critical and not confirm:
            st.error("Tick the confirmation box before approving a case with critical issues.")
        else:
            try:
                feedback.record_review(vendor_id, reviewer, act, reason, corrections, wrong)
                st.success(f"Saved. {len(corrections)} correction(s) recorded.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.divider()
    with st.expander("Vendor sent new information: update and re-run checks"):
        with st.form("update_form"):
            new_vals = {}
            cols = st.columns(3)
            for i, field in enumerate(f for f in VendorSubmission.model_fields
                                      if f not in ("vendor_type", "autofilled",
                                                   "autofill_edited")):
                with cols[i % 3]:
                    new_vals[field] = st.text_input(FIELD_LABELS.get(field, field),
                                                    value=getattr(s, field), key=f"upd_{field}")
            new_type = st.selectbox("Document type of new file", list(DocumentType),
                                    format_func=DOC_LABELS.get)
            new_file = st.file_uploader("New or replacement PDF (optional; replaces any earlier "
                                        "file of the same type)", type=["pdf"])
            rerun = st.form_submit_button("Save changes and re-run checks")
        if rerun:
            cleaned = {k: val.strip().upper() if k in ("country", "bank_country") else val.strip()
                       for k, val in new_vals.items()}
            # A field edited by the reviewer is no longer "auto-filled from a document"
            still_auto = {f: d for f, d in s.autofilled.items() if cleaned.get(f) == getattr(s, f)}
            now_edited = s.autofill_edited + [f for f in s.autofilled if f not in still_auto]
            updated = VendorSubmission(vendor_type=s.vendor_type, autofilled=still_auto,
                                       autofill_edited=now_edited, **cleaned)
            db.update_submission(vendor_id, updated, "reviewer")
            if new_file is not None:
                try:
                    db.supersede_documents(vendor_id, new_type.value)
                    db.add_document(vendor_id, save_upload(vendor_id, new_type, new_file.name,
                                                           new_file.getvalue()))
                except ValueError as exc:
                    st.error(str(exc))
            with st.status("Re-running checks…", expanded=True) as status:
                new_rec = run_checks(vendor_id, progress=lambda m: st.write(f"✓ {m}"))
                status.update(label=f"Done: {new_rec.status.value}", state="complete")
            db.set_status(vendor_id, Status.PENDING, db.AWAITING_REVIEW)
            st.rerun()

# ---------- History ----------
with tabs[5]:
    st.subheader("Reviewer decisions")
    if v["reviews"]:
        st.dataframe(pd.DataFrame([{
            "When (UTC)": r["timestamp"], "Reviewer": r["reviewer"], "Action": r["action"],
            "System said": r["system_status"], "Final": r["final_status"],
            "Overrode system": "yes" if not r["agreed_with_system"] else "no",
            "Reason": r["reason"], "Checks marked wrong": ", ".join(r["incorrect_checks"]),
        } for r in v["reviews"]]), hide_index=True)
    else:
        st.write("No reviews yet.")
    st.subheader("Audit log")
    st.dataframe(pd.DataFrame([{
        "When (UTC)": e["timestamp"], "Who": e["actor"], "Event": e["event_type"],
        "Details": ", ".join(f"{k}: {val}" for k, val in e["details"].items()),
    } for e in v["events"]]), hide_index=True)
