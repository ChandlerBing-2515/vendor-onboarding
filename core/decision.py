"""
Explainable decision engine: findings in, recommendation out.

The rules, in order:
  1. Any FAILED rejection rule (a defined policy condition)  -> Rejected
  2. Any check that failed or is inconclusive               -> Pending
  3. Everything passed                                      -> Approved
     (a recommendation only: a human must still authorise)

There is no score and no averaging. One open issue keeps a case Pending, no
matter how many other checks passed. Missing or uncertain information never
leads to rejection on its own. These rules never change automatically: the
learning loop (feedback.py) cannot weaken them.
"""

from core.models import (
    DOC_LABELS, Category, CheckOutcome, DocumentType, Finding, Recommendation, Severity, Status,
)
from core.validation import FIELD_LABELS

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.INFO: 3}

# What this system does NOT verify. Shown on every vendor page.
NOT_VERIFIED = [
    "Document authenticity (we read documents; we cannot prove they are genuine).",
    "Bank account ownership (needs a bank account verification service).",
    "Company existence in an official register (no registry API connected).",
    "Tax ID validity with the tax authority (only the format is checked).",
    "Real sanctions screening (only a synthetic test list is used).",
]


def open_issues(findings: list[Finding]) -> list[Finding]:
    issues = [f for f in findings if f.outcome != CheckOutcome.PASS]
    return sorted(issues, key=lambda f: SEVERITY_ORDER[f.severity])


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _join(items: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b and c'"""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "." if text else ""


def soft_lower(text: str) -> str:
    """'Tax ID type' -> 'tax ID type' (keeps acronyms in capitals)."""
    return " ".join(w if w.isupper() else w.lower() for w in text.split())


def _missing_fields(issues: list[Finding]) -> list[str]:
    return [soft_lower(FIELD_LABELS.get(f.check_id.split(".", 1)[1], f.label))
            for f in issues if f.check_id.startswith("required.")]


def _missing_docs(issues: list[Finding]) -> list[str]:
    return [DOC_LABELS[DocumentType(f.check_id.rsplit(".", 1)[1])].lower()
            for f in issues if f.check_id.startswith("document.present.")]


def split_actions(issues: list[Finding]) -> tuple[list[str], list[str]]:
    """Turn many per-check actions into two short lists: what the vendor must
    send or fix, and what a reviewer must check. Missing fields and missing
    documents are each combined into a single line."""
    vendor, reviewer = [], []
    fields, docs = _missing_fields(issues), _missing_docs(issues)
    if fields:
        vendor.append(f"Complete {len(fields)} missing detail(s): {_join(fields)}.")
    if docs:
        vendor.append(f"Upload the missing document(s): {_join(docs)}.")

    for f in issues:
        if f.check_id.startswith(("required.", "document.present.")) or not f.next_action:
            continue
        action = f.next_action
        # "...; a reviewer must confirm X" -> vendor part + reviewer part
        if "; a reviewer must " in action:
            action, review_part = action.split("; a reviewer must ", 1)
            reviewer.append(_sentence(review_part))
        if action.startswith("Ask the vendor to "):
            vendor.append(_sentence(action.removeprefix("Ask the vendor to ")))
        elif action.startswith("Ask the vendor for "):
            vendor.append(_sentence("Provide " + action.removeprefix("Ask the vendor for ")))
        elif action.startswith("Reviewer to "):
            reviewer.append(_sentence(action.removeprefix("Reviewer to ")))
        else:
            reviewer.append(_sentence(action))
    return _dedupe(vendor), _dedupe(reviewer)


def summarise_reasons(issues: list[Finding]) -> list[str]:
    """One line per real problem; missing fields/documents grouped."""
    reasons = []
    fields, docs = _missing_fields(issues), _missing_docs(issues)
    for f in issues:
        if f.check_id.startswith("required."):
            if fields:
                reasons.append(f"[major] {len(fields)} required detail(s) missing: {_join(fields)}.")
                fields = []
        elif f.check_id.startswith("document.present."):
            if docs:
                reasons.append(f"[major] Required document(s) missing: {_join(docs)}.")
                docs = []
        else:
            reasons.append(f"[{f.severity.value}] {f.label}: {f.message}")
    return reasons


def recommend(findings: list[Finding]) -> Recommendation:
    issues = open_issues(findings)
    rejections = [f for f in issues if f.category == Category.REJECTION_RULE
                  and f.outcome == CheckOutcome.FAIL]

    if rejections:
        tasks = ["Confirm the blocked-party match, then reject with a reason."]
        return Recommendation(
            status=Status.REJECTED,
            headline="Rejection condition met: a reviewer must confirm",
            reasons=[f"{f.label}: {f.message}" for f in rejections],
            next_actions=tasks, reviewer_tasks=tasks,
            blocking_check_ids=[f.check_id for f in rejections])

    if issues:
        critical = [f for f in issues if f.severity == Severity.CRITICAL]
        missing = [f for f in issues if f.category == Category.MISSING_INFO
                   or f.check_id.startswith("document.present")]
        if critical:
            headline = f"{len(critical)} critical issue(s) need a reviewer"
        elif missing:
            headline = "Waiting for missing information or documents"
        else:
            headline = "Some checks are inconclusive and need a reviewer"
        vendor, reviewer = split_actions(issues)
        return Recommendation(
            status=Status.PENDING, headline=headline,
            reasons=summarise_reasons(issues),
            next_actions=vendor + reviewer, vendor_requests=vendor, reviewer_tasks=reviewer,
            blocking_check_ids=[f.check_id for f in issues])

    tasks = ["Authorise approval after reading the 'Not verified' list."]
    return Recommendation(
        status=Status.APPROVED,
        headline="All configured checks passed: awaiting human authorisation",
        reasons=[f"All {len(findings)} configured checks passed."],
        next_actions=tasks, reviewer_tasks=tasks,
        blocking_check_ids=[])
