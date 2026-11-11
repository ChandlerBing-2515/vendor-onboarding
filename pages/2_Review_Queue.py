"""Prioritised review queue for procurement reviewers."""

import pandas as pd
import streamlit as st

from components import STATE_LABELS, open_vendor, page_header, setup, status_text
from core import feedback
from core.prioritization import TIER_NAMES, build_queue

setup("Review Queue")
page_header("Review queue",
            "Ordered by transparent rules, not by AI confidence. A confident extraction can "
            "still reveal a serious mismatch, so mismatches come first.")

with st.expander("How the queue is ordered"):
    for tier, name in TIER_NAMES.items():
        st.markdown(f"**{tier}. {name}**")
    st.markdown("Within a tier, cases whose issues reviewers have usually confirmed in past "
                "reviews come first, then the oldest case. Approved and rejected cases leave "
                "the queue.")

queue = build_queue(feedback.check_reliability())
if not queue:
    st.success("Nothing waiting for review.")
    st.stop()

rows = [{
    "Priority": f"{q['tier']}. {q['priority']}", "Vendor": q["vendor_name"], "Why": q["why"],
    "Open issues": q["open_issues"], "System recommends": status_text(q["recommendation"]),
    "Stage": STATE_LABELS.get(q["review_state"], q["review_state"]),
    "Submitted (UTC)": q["submitted"][:16].replace("T", " "), "ID": q["id"],
} for q in queue]

event = st.dataframe(pd.DataFrame(rows), hide_index=True, on_select="rerun",
                     selection_mode="single-row", key="queue_table")
if event.selection.rows:
    chosen = rows[event.selection.rows[0]]
    if st.button(f"Review {chosen['Vendor']}", type="primary"):
        open_vendor(chosen["ID"])
else:
    st.caption("Select a row to review that vendor.")
