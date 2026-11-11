"""Home page: the dashboard. Start the app with:  streamlit run Dashboard.py"""

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from components import STATE_LABELS, open_vendor, page_header, section, setup, status_text
from core import database as db, feedback
from core.decision import open_issues

setup("Dashboard")
page_header("Vendor onboarding",
            "Every submission is checked by transparent rules and AI document reading. "
            "A human makes every final decision.")

vendors = db.list_vendors()
if not vendors:
    with st.container(border=True):
        st.subheader("No vendors yet")
        st.write("Submit a vendor to see the checks run live. The demo samples fill the form "
                 "for you.")
        st.page_link("pages/1_Submit_Vendor.py", label="Submit a vendor", icon=":material/add:")
    st.stop()

counts = Counter(v["status"] for v in vendors)
awaiting = sum(v["review_state"] in (db.AWAITING_REVIEW, db.ESCALATED) for v in vendors)
waiting_vendor = sum(v["review_state"] == db.INFO_REQUESTED for v in vendors)
m = feedback.metrics()

# ---------- 1. Headline numbers, grouped ----------
section("Pipeline")
c = st.columns(4)
c[0].metric("Submitted", len(vendors), border=True)
c[1].metric("Approved", counts.get("Approved", 0), border=True)
c[2].metric("Pending", counts.get("Pending", 0), border=True)
c[3].metric("Rejected", counts.get("Rejected", 0), border=True)

left, right = st.columns([2, 3])
with left:
    section("Reviewer workload")
    c = st.columns(2)
    c[0].metric("Awaiting review", awaiting, border=True)
    c[1].metric("Waiting on vendor", waiting_vendor, border=True)
with right:
    section("Quality and learning")
    c = st.columns(3)
    rate = m["disagreement_rate"]
    c[0].metric("Disagreement", "–" if rate is None else f"{rate:.0%}", border=True,
                help="AI–human disagreement: share of final human decisions (approve/reject) that differ from the "
                     "system recommendation. '–' until a final decision is made.")
    c[1].metric("Corrections captured", m["corrections"], border=True)
    results_path = Path(__file__).parent / "evaluation" / "results.json"
    if results_path.exists():
        last = json.loads(results_path.read_text())[-1]
        c[2].metric("Test-set accuracy", f"{last['recommendation_accuracy']:.0%}", border=True,
                    help=f"Recommendation accuracy on {last['cases']} labelled synthetic cases. "
                         f"Last run {last['timestamp'][:16].replace('T', ' ')} UTC "
                         f"({last['method']}).")
    else:
        c[2].metric("Test-set accuracy", "not run", border=True,
                    help="Run: python evaluation/evaluate.py")

st.write("")

# ---------- 2. All vendors ----------
with st.container(border=True):
    st.subheader("All vendors")
    rows = [{
        "ID": v["id"],
        "Vendor": v["vendor_name"],
        "Status": status_text(v["status"]),
        "System recommends": status_text(v["recommendation"].status.value)
        if v["recommendation"] else "–",
        "Stage": STATE_LABELS.get(v["review_state"], v["review_state"]),
        "Open issues": len(open_issues(v["findings"])),
        "Submitted (UTC)": v["created_at"][:16].replace("T", " "),
    } for v in vendors]
    event = st.dataframe(
        pd.DataFrame(rows), hide_index=True, on_select="rerun", selection_mode="single-row",
        key="dash_table",
        column_config={
            "ID": st.column_config.NumberColumn(width="small"),
            "Vendor": st.column_config.TextColumn(width="medium"),
            "Open issues": st.column_config.NumberColumn(width="small"),
        })
    if event.selection.rows:
        chosen = rows[event.selection.rows[0]]
        if st.button(f"Open {chosen['Vendor']}", type="primary", icon=":material/open_in_new:"):
            open_vendor(chosen["ID"])
    else:
        st.caption("Tick a row to open that vendor.")

# ---------- 3. Why cases are pending + recent activity ----------
left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.subheader("Why cases are pending")
        pending = [v for v in vendors if v["status"] == "Pending"]
        reasons = Counter(f.label for v in pending for f in open_issues(v["findings"]))
        if reasons:
            st.dataframe(
                pd.DataFrame(reasons.most_common(8), columns=["Reason", "Cases"]),
                hide_index=True,
                column_config={"Cases": st.column_config.ProgressColumn(
                    format="%d", min_value=0, max_value=max(len(pending), 1))})
            st.caption(f"Open issues across {len(pending)} pending case(s).")
        else:
            st.write("No pending cases.")

with right:
    with st.container(border=True):
        st.subheader("Recent activity")
        events = db.list_recent_events(8)
        st.dataframe(pd.DataFrame([{
            "When (UTC)": e["timestamp"][5:16].replace("T", " "),
            "Vendor": e["vendor_name"],
            "Event": e["event_type"].replace("_", " "),
            "By": e["actor"],
        } for e in events]), hide_index=True,
            column_config={"When (UTC)": st.column_config.TextColumn(width="small"),
                           "By": st.column_config.TextColumn(width="small")})
