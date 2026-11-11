"""
Small Streamlit helpers shared by every page (the only UI code outside pages/).
"""

import os

import streamlit as st

from core import database as db
from core.models import CheckOutcome, Finding

STATUS_COLORS = {"Approved": "green", "Pending": "orange", "Rejected": "red"}
STATUS_DOTS = {"Approved": "🟢", "Pending": "🟠", "Rejected": "🔴"}

# Light-touch styling: narrower page, calmer headings, consistent metric cards
CSS = """
<style>
.block-container {max-width: 1240px; padding-top: 2.2rem; padding-bottom: 3rem;}
h1 {font-size: 2rem !important; font-weight: 700 !important; padding-bottom: 0 !important;}
h2 {font-size: 1.35rem !important; font-weight: 650 !important;}
h3 {font-size: 1.15rem !important; font-weight: 650 !important;}
[data-testid="stMetricValue"] {font-size: 1.75rem;}
[data-testid="stMetricLabel"] p {font-size: 0.85rem; opacity: 0.75;}
.section-label {font-size: 0.78rem; font-weight: 600; letter-spacing: .06em;
                text-transform: uppercase; opacity: .6; margin: 0 0 .35rem 0;}
</style>
"""
OUTCOME_ICONS = {CheckOutcome.PASS: "✅", CheckOutcome.FAIL: "❌", CheckOutcome.NEEDS_REVIEW: "⚠️"}
STATE_LABELS = {
    db.AWAITING_REVIEW: "Awaiting review", db.INFO_REQUESTED: "Info requested from vendor",
    db.ESCALATED: "Escalated", db.DECIDED: "Decided by reviewer",
}


def setup(title: str) -> None:
    """Call at the top of every page."""
    st.set_page_config(page_title=f"{title} · Vendor Onboarding", page_icon="📋", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    _load_secrets()
    db.init_db()


def page_header(title: str, subtitle: str = "") -> None:
    """Same title block on every page: title, one-line purpose, AI status."""
    left, right = st.columns([4, 1.4], vertical_alignment="bottom")
    with left:
        st.title(title)
        if subtitle:
            st.caption(subtitle)
    with right:
        ai_status_badge()
    st.write("")


def section(label: str) -> None:
    st.markdown(f'<p class="section-label">{label}</p>', unsafe_allow_html=True)


def status_text(status: str) -> str:
    """'Pending' -> '🟠 Pending' for tables."""
    return f"{STATUS_DOTS.get(status, '⚪')} {status}"


def _load_secrets() -> None:
    """Copy keys from .streamlit/secrets.toml into environment variables,
    so code in core/ can read them without importing Streamlit."""
    try:
        for key in ("AI_PROVIDER", "AI_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL",
                    "GEMINI_API_KEY"):
            if key in st.secrets and not os.environ.get(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass  # no secrets file: the app runs with the pattern fallback


def status_badge(status: str, prefix: str = "") -> None:
    st.badge(f"{prefix}{status}", color=STATUS_COLORS.get(status, "gray"))


def badge_md(text: str, color: str) -> str:
    """Inline badge for st.markdown, so several badges sit on one line."""
    return f":{color}-badge[{text}]"


def ai_status_badge() -> None:
    from core.extraction import ai_available, get_model, get_provider
    if ai_available():
        st.badge(f"{get_provider().capitalize()} · {get_model()}", icon=":material/smart_toy:",
                 color="blue")
    else:
        st.badge("Pattern fallback (no AI key)", icon=":material/warning:", color="orange")


def show_finding(f: Finding, reliability: dict | None = None) -> None:
    icon = OUTCOME_ICONS[f.outcome]
    with st.container(border=True):
        st.markdown(f"{icon} **{f.label}** · `{f.severity.value}` · _{f.category.value}_")
        st.write(f.message)
        if f.evidence:
            st.caption(f"Evidence: {f.evidence}")
        if f.source != "form":
            st.caption(f"Source: {f.source}")
        if f.next_action:
            st.markdown(f"**Next action:** {f.next_action}")
        stats = (reliability or {}).get(f.check_id)
        if stats and stats["raised"]:
            st.caption(f"History: reviewers marked this check wrong in "
                       f"{stats['marked_wrong']} of {stats['raised']} past reviewed cases.")


def show_actions(rec) -> None:
    """Two short lists: what the vendor must send, what the reviewer must check."""
    vendor, reviewer = rec.vendor_requests, rec.reviewer_tasks
    if not vendor and not reviewer:          # records saved before this change
        vendor, reviewer = [], rec.next_actions
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("**:material/outgoing_mail: The vendor needs to**")
        if vendor:
            st.markdown("\n".join(f"- {a}" for a in vendor))
        else:
            st.caption("Nothing. The vendor's submission is complete.")
    with right, st.container(border=True):
        st.markdown("**:material/fact_check: The reviewer needs to**")
        if reviewer:
            st.markdown("\n".join(f"- {a}" for a in reviewer))
        else:
            st.caption("Nothing yet. Wait for the vendor's reply.")


def open_vendor(vendor_id: int) -> None:
    st.session_state["selected_vendor_id"] = vendor_id
    st.switch_page("pages/3_Vendor_Detail.py")
