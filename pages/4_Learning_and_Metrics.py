"""What the system learns from reviewers, and how well it performs."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from components import page_header, setup
from core import database as db, feedback

setup("Learning & Metrics")
page_header("Learning and metrics",
            "What the system learns from reviewers, and how it performs on the labelled test set.")

m = feedback.metrics()
c = st.columns(4)
c[0].metric("Human reviews", m["reviews"], border=True)
c[1].metric("Final decisions", m["final_decisions"], border=True)
rate = m["disagreement_rate"]
c[2].metric("AI–human disagreement", "–" if rate is None else f"{rate:.0%}", border=True)
c[3].metric("Corrections captured", m["corrections"], border=True)

st.subheader("How the system uses reviewer feedback")
st.markdown("""
| Component | How it changes | When |
|---|---|---|
| AI document extraction | Recent reviewer corrections for the same document type are added to the prompt as examples | **Immediately**, next extraction |
| Form auto-fill | Uses the same AI extraction, so those corrections improve it too. Edits to auto-filled values are tracked per field (below) | **Immediately** |
| Review queue order | Per-check false-alarm rates (from "which checks were wrong") reorder cases inside a tier | **Immediately**, next page load |
| Check history shown to reviewers | "Reviewers marked this wrong in X of Y cases" appears on each finding | **Immediately** |
| Validation and decision rules | **Never automatically.** A person changes them in code, then re-runs the test set | Manual, after evaluation |
| The AI model itself | Not retrained in this MVP. Stored corrections could be exported for fine-tuning, then evaluated before use | Periodic (future) |
""")
st.caption("Saving a decision does not mean the model has learned. Human decisions can also be "
           "wrong, so they never weaken compliance rules automatically.")

left, right = st.columns(2)
with left:
    st.subheader("Check reliability (from reviewer feedback)")
    rel = m["check_reliability"]
    if rel:
        st.dataframe(pd.DataFrame([{
            "Check": cid, "Times raised in reviewed cases": r["raised"],
            "Marked wrong by reviewer": r["marked_wrong"],
            "False-alarm rate": f"{r['false_alarm_rate']:.0%}",
        } for cid, r in sorted(rel.items(), key=lambda kv: -kv[1]["false_alarm_rate"])]),
            hide_index=True)
    else:
        st.write("No reviews yet.")

with right:
    st.subheader("Corrections by field")
    if m["corrections_by_field"]:
        st.dataframe(pd.DataFrame(m["corrections_by_field"], columns=["Document / field", "Count"]),
                     hide_index=True)
    else:
        st.write("No corrections yet.")

st.subheader("Auto-fill: which fields people had to fix")
auto = feedback.automation_metrics()
if auto["by_field"]:
    st.dataframe(pd.DataFrame([{
        "Field": r["field"].replace("_", " "), "Kept as filled": r["kept"],
        "Edited by a person": r["edited"],
        "Kept rate": f"{r['kept'] / (r['kept'] + r['edited']):.0%}",
    } for r in auto["by_field"]]), hide_index=True)
    st.caption("Fields that people often edit show where the AI's reading needs work. "
               "Edits to auto-filled values are captured whether made before submitting "
               "or later by a reviewer.")
else:
    st.write("No auto-filled submissions yet. Use 'Fill empty fields from these documents' "
             "on the Submit page.")

st.subheader("Correction examples the AI will see next")
recent = db.list_corrections(limit=10)
if recent:
    st.dataframe(pd.DataFrame([{
        "Document type": c["doc_type"], "Field": c["field_name"], "Extracted": c["extracted_value"],
        "Corrected to": c["corrected_value"], "When (UTC)": c["timestamp"]} for c in recent]),
        hide_index=True)
else:
    st.write("None yet. Correct a value on a vendor's Review tab to add one.")

st.subheader("Labelled test set results")
results = Path(__file__).resolve().parent.parent / "evaluation" / "results.json"
if results.exists():
    runs = json.loads(results.read_text())
    st.dataframe(pd.DataFrame([{
        "When (UTC)": r["timestamp"], "Method": r["method"],
        "Used corrections": r["used_correction_examples"], "Cases": r["cases"],
        "Field accuracy": f"{r['field_accuracy']:.0%}",
        "Recommendation accuracy": f"{r['recommendation_accuracy']:.0%}",
    } for r in reversed(runs)]), hide_index=True)
    with st.expander("Misses in the latest run"):
        for e in runs[-1]["errors"] or ["None"]:
            st.write(e)
    st.caption(f"{runs[-1]['cases']} synthetic cases is a small test set. Treat differences "
               "between runs as indicative, not proof of improvement.")
else:
    st.info("Not run yet. In the terminal:  python evaluation/evaluate.py")
