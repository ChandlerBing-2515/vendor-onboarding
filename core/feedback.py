"""
Human-in-the-loop feedback: records reviewer decisions and corrections, and
turns them into signals the system can use.

What adapts, and how (be precise about this in the demo):
  IMMEDIATELY  - Reviewer corrections are added as examples to the next AI
                 extraction prompt for the same document type.
               - Per-check "false alarm" rates update after every review and
                 are shown to reviewers and used to order the queue.
  NOT AUTOMATIC - The validation and decision rules never change by themselves.
                 Human decisions can be wrong, so rule changes are made by a
                 person, in code, and tested on the labelled set first.
  PERIODIC     - Fine-tuning a model on the stored corrections would need an
                 export + retraining + evaluation step. Not done in this MVP.
"""

import json
from collections import Counter

from core import database as db
from core.models import CheckOutcome, ReviewAction, Status

ACTION_TO_STATUS = {
    ReviewAction.APPROVE: (Status.APPROVED, db.DECIDED),
    ReviewAction.REJECT: (Status.REJECTED, db.DECIDED),
    ReviewAction.REQUEST_INFO: (Status.PENDING, db.INFO_REQUESTED),
    ReviewAction.ESCALATE: (Status.PENDING, db.ESCALATED),
}


def reason_required(action: ReviewAction, system_status: Status) -> bool:
    final_status, _ = ACTION_TO_STATUS[action]
    return action != ReviewAction.APPROVE or final_status != system_status


def record_review(vendor_id: int, reviewer: str, action: ReviewAction, reason: str,
                  corrections: list[dict] | None = None,
                  incorrect_checks: list[str] | None = None) -> int:
    """Save a human decision plus everything the system said at that moment."""
    vendor = db.get_vendor(vendor_id)
    if vendor is None or vendor["recommendation"] is None:
        raise ValueError("Run the checks before reviewing this vendor.")
    rec = vendor["recommendation"]
    final_status, review_state = ACTION_TO_STATUS[action]
    reason = (reason or "").strip()
    if reason_required(action, rec.status) and len(reason) < 5:
        raise ValueError("A reason is required for this decision (at least a few words).")
    if not reviewer.strip():
        raise ValueError("Enter the reviewer's name.")

    snapshot = {
        "submission": vendor["submission"].model_dump(mode="json"),
        "recommendation": rec.model_dump(mode="json"),
        "findings": [f.model_dump(mode="json") for f in vendor["findings"]],
        "extractions": [d["extraction"].model_dump(mode="json")
                        for d in vendor["documents"] if d["extraction"]],
    }
    review_id = db.add_review(
        vendor_id, reviewer.strip(), action.value, reason, rec.status.value,
        final_status.value, final_status == rec.status, incorrect_checks or [], snapshot)

    for c in corrections or []:
        db.add_correction(review_id, vendor_id, c.get("document_id"), c["doc_type"],
                          c["field_name"], c.get("extracted_value"), c["corrected_value"],
                          c.get("note", ""))

    db.set_status(vendor_id, final_status, review_state)
    db.log_event(vendor_id, reviewer.strip(), f"review_{action.value}", {
        "reason": reason, "system_recommendation": rec.status.value,
        "final_status": final_status.value, "overrode_system": final_status != rec.status,
        "corrections": len(corrections or []), "incorrect_checks": incorrect_checks or [],
    })
    return review_id


def correction_examples(doc_type: str, limit: int = 5) -> list[dict]:
    """Most recent corrections for a document type, for the AI prompt."""
    return db.list_corrections(doc_type=doc_type, limit=limit)


def check_reliability() -> dict[str, dict]:
    """For each check: how often it raised an issue and how often reviewers
    marked that issue as wrong (a 'false alarm')."""
    raised, wrong = Counter(), Counter()
    for r in db.list_reviews():
        for f in _snapshot_findings(r):
            if f["outcome"] != CheckOutcome.PASS.value:
                raised[f["check_id"]] += 1
        for cid in r["incorrect_checks"]:
            wrong[cid] += 1
    return {cid: {"raised": raised[cid], "marked_wrong": wrong[cid],
                  "false_alarm_rate": wrong[cid] / raised[cid] if raised[cid] else 0.0}
            for cid in set(raised) | set(wrong)}


def _snapshot_findings(review: dict) -> list[dict]:
    return json.loads(review["snapshot_json"]).get("findings", [])


def metrics() -> dict:
    reviews = db.list_reviews()
    corrections = db.list_corrections()
    # Only final decisions count for agreement (request-info/escalate are steps, not outcomes)
    final = [r for r in reviews if r["action"] in (ReviewAction.APPROVE.value,
                                                   ReviewAction.REJECT.value)]
    disagreements = [r for r in final if not r["agreed_with_system"]]
    return {
        "reviews": len(reviews),
        "final_decisions": len(final),
        "disagreements": len(disagreements),
        "disagreement_rate": len(disagreements) / len(final) if final else None,
        "corrections": len(corrections),
        "corrections_by_field": Counter(f"{c['doc_type']} / {c['field_name']}"
                                        for c in corrections).most_common(),
        "check_reliability": check_reliability(),
    }
