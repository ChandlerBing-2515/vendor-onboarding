"""
Review queue ordering: transparent tiers, not an AI confidence score.

Tier 1  Rejection condition or critical issue
Tier 2  Escalated case, or an important field read with low confidence
Tier 3  Needs specialist / manual verification (unsupported country, OCR, risk)
Tier 4  Missing information (not yet requested from the vendor)
Tier 5  All checks passed: waiting for human authorisation
Tier 6  Information requested: waiting on the vendor

Inside a tier: cases whose issues reviewers have usually CONFIRMED in the
past come first (from feedback.check_reliability), then the oldest case.
Decided cases (approved/rejected by a human) leave the queue.
"""

from core import database as db
from core.decision import open_issues
from core.models import Category, CheckOutcome, Severity, Status

TIER_NAMES = {
    1: "Critical issue / rejection condition",
    2: "Escalated or low-confidence key field",
    3: "Specialist or manual verification",
    4: "Missing information",
    5: "Ready for authorisation",
    6: "Waiting on vendor",
}


def tier_for(vendor: dict) -> tuple[int, str]:
    rec = vendor["recommendation"]
    issues = open_issues(vendor["findings"])
    if rec is None:
        return 4, "Checks have not run yet"
    if rec.status == Status.REJECTED or any(f.severity == Severity.CRITICAL for f in issues):
        crit = [f.label for f in issues if f.severity == Severity.CRITICAL]
        return 1, "; ".join(crit[:2]) or rec.headline
    if vendor["review_state"] == db.ESCALATED:
        return 2, "Escalated by a reviewer"
    if vendor["review_state"] == db.INFO_REQUESTED:
        return 6, "Information requested from vendor"
    low_conf = [f for f in issues if f.category == Category.UNCERTAIN and f.severity == Severity.MAJOR]
    if low_conf:
        return 2, low_conf[0].label
    special = [f for f in issues if f.category in (Category.SPECIALIST, Category.RISK)
               or (f.category == Category.DOCUMENT and f.outcome == CheckOutcome.NEEDS_REVIEW)]
    if special:
        return 3, special[0].label
    if issues:
        return 4, f"{len(issues)} item(s) missing or to fix"
    return 5, "All configured checks passed"


def build_queue(reliability: dict[str, dict] | None = None) -> list[dict]:
    reliability = reliability or {}
    queue = []
    for v in db.list_vendors():
        if v["review_state"] == db.DECIDED:
            continue
        tier, why = tier_for(v)
        # Expected "real" issues: each open issue counts 1 minus its past false-alarm rate
        confirmed_weight = sum(1 - reliability.get(f.check_id, {}).get("false_alarm_rate", 0.0)
                               for f in open_issues(v["findings"]))
        queue.append({
            "id": v["id"], "vendor_name": v["vendor_name"], "tier": tier,
            "priority": TIER_NAMES[tier], "why": why,
            "open_issues": len(open_issues(v["findings"])),
            "recommendation": v["recommendation"].status.value if v["recommendation"] else "-",
            "review_state": v["review_state"], "submitted": v["created_at"],
            "_weight": round(confirmed_weight, 2),
        })
    queue.sort(key=lambda q: (q["tier"], -q["_weight"], q["submitted"]))
    return queue
