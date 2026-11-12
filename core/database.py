"""
Database layer: the ONLY file that talks to SQLite.
If we later move to a cloud database, only this file needs to change.

Tables
  vendors     one row per vendor (form data, latest findings, recommendation)
  documents   one row per uploaded PDF (+ what was extracted from it)
  events      append-only audit log: every action, timestamped, never edited
  reviews     every human decision with a snapshot of what the system said
  corrections every field value a reviewer corrected (the learning data)
"""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from core.models import (
    DocumentExtraction, Finding, Recommendation, Status, UploadedDocument,
    VendorSubmission, utc_now,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# review_state values (where the case sits in the human workflow)
AWAITING_REVIEW = "awaiting_review"
INFO_REQUESTED = "info_requested"
ESCALATED = "escalated"
DECIDED = "decided"


def get_db_path() -> Path:
    """VENDOR_DB_PATH if set (used by tests), otherwise data/vendors.db."""
    path = Path(os.environ.get("VENDOR_DB_PATH", PROJECT_ROOT / "data" / "vendors.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row          # read columns by name: row["status"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call every time."""
    with closing(_connect()) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vendors (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                vendor_name         TEXT NOT NULL,
                status              TEXT NOT NULL,
                review_state        TEXT NOT NULL DEFAULT 'awaiting_review',
                submission_json     TEXT NOT NULL,
                findings_json       TEXT NOT NULL DEFAULT '[]',
                recommendation_json TEXT
            );
            CREATE TABLE IF NOT EXISTS documents (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id         INTEGER NOT NULL REFERENCES vendors(id),
                doc_type          TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path       TEXT NOT NULL,
                size_bytes        INTEGER NOT NULL,
                uploaded_at       TEXT NOT NULL,
                extraction_json   TEXT,
                superseded        INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id    INTEGER NOT NULL REFERENCES vendors(id),
                timestamp    TEXT NOT NULL,
                actor        TEXT NOT NULL,
                event_type   TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id             INTEGER NOT NULL REFERENCES vendors(id),
                timestamp             TEXT NOT NULL,
                reviewer              TEXT NOT NULL,
                action                TEXT NOT NULL,
                reason                TEXT NOT NULL,
                system_status         TEXT NOT NULL,
                final_status          TEXT NOT NULL,
                agreed_with_system    INTEGER NOT NULL,
                incorrect_checks_json TEXT NOT NULL DEFAULT '[]',
                snapshot_json         TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS corrections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id       INTEGER NOT NULL REFERENCES reviews(id),
                vendor_id       INTEGER NOT NULL REFERENCES vendors(id),
                document_id     INTEGER,
                doc_type        TEXT NOT NULL,
                field_name      TEXT NOT NULL,
                extracted_value TEXT,
                corrected_value TEXT NOT NULL,
                note            TEXT NOT NULL DEFAULT '',
                timestamp       TEXT NOT NULL
            );
            """
        )


# ---------- Audit log ----------

def log_event(vendor_id: int, actor: str, event_type: str, details: dict | None = None) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO events (vendor_id, timestamp, actor, event_type, details_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (vendor_id, utc_now(), actor, event_type, json.dumps(details or {})),
        )


# ---------- Vendors ----------

def create_vendor(submission: VendorSubmission) -> int:
    now = utc_now()
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO vendors (created_at, updated_at, vendor_name, status, submission_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, now, submission.vendor_name or "(no name)", Status.PENDING.value,
             submission.model_dump_json()),
        )
        vendor_id = cur.lastrowid
    log_event(vendor_id, "system", "submitted", {"vendor_name": submission.vendor_name})
    return vendor_id


def save_results(vendor_id: int, findings: list[Finding], rec: Recommendation) -> None:
    """Store the latest check results and the system recommendation.
    The official status stays Pending until a human decides."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE vendors SET findings_json = ?, recommendation_json = ?, updated_at = ? "
            "WHERE id = ?",
            (json.dumps([f.model_dump(mode="json") for f in findings]),
             rec.model_dump_json(), utc_now(), vendor_id),
        )
    log_event(vendor_id, "system", "checks_completed", {
        "recommendation": rec.status.value,
        "open_issues": sum(f.outcome != "pass" for f in findings),
    })


def set_status(vendor_id: int, status: Status, review_state: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE vendors SET status = ?, review_state = ?, updated_at = ? WHERE id = ?",
            (status.value, review_state, utc_now(), vendor_id),
        )


def update_submission(vendor_id: int, submission: VendorSubmission, actor: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE vendors SET submission_json = ?, vendor_name = ?, updated_at = ? WHERE id = ?",
            (submission.model_dump_json(), submission.vendor_name or "(no name)",
             utc_now(), vendor_id),
        )
    log_event(vendor_id, actor, "submission_updated")


def list_vendors() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM vendors ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "vendor_name": r["vendor_name"], "status": r["status"],
            "review_state": r["review_state"], "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "submission": VendorSubmission.model_validate_json(r["submission_json"]),
            "findings": [Finding(**f) for f in json.loads(r["findings_json"])],
            "recommendation": (Recommendation.model_validate_json(r["recommendation_json"])
                               if r["recommendation_json"] else None),
        })
    return out


def get_vendor(vendor_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if row is None:
            return None
        docs = conn.execute("SELECT * FROM documents WHERE vendor_id = ? AND superseded = 0 "
                            "ORDER BY id", (vendor_id,)).fetchall()
        events = conn.execute("SELECT * FROM events WHERE vendor_id = ? ORDER BY id",
                              (vendor_id,)).fetchall()
        reviews = conn.execute("SELECT * FROM reviews WHERE vendor_id = ? ORDER BY id",
                               (vendor_id,)).fetchall()
    return {
        "id": row["id"],
        "vendor_name": row["vendor_name"],
        "status": row["status"],
        "review_state": row["review_state"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "submission": VendorSubmission.model_validate_json(row["submission_json"]),
        "findings": [Finding(**f) for f in json.loads(row["findings_json"])],
        "recommendation": (Recommendation.model_validate_json(row["recommendation_json"])
                           if row["recommendation_json"] else None),
        "documents": [_doc_row(d) for d in docs],
        "events": [{**dict(e), "details": json.loads(e["details_json"])} for e in events],
        "reviews": [{**dict(r), "incorrect_checks": json.loads(r["incorrect_checks_json"])}
                    for r in reviews],
    }


def list_recent_events(limit: int = 10) -> list[dict]:
    """Latest audit-log entries across all vendors (for the dashboard)."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT e.*, v.vendor_name FROM events e JOIN vendors v ON v.id = e.vendor_id "
            "ORDER BY e.id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "details": json.loads(r["details_json"])} for r in rows]


# ---------- Documents ----------

def _doc_row(d: sqlite3.Row) -> dict:
    data = dict(d)
    data["extraction"] = (DocumentExtraction.model_validate_json(d["extraction_json"])
                          if d["extraction_json"] else None)
    return data


def add_document(vendor_id: int, doc: UploadedDocument) -> int:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO documents (vendor_id, doc_type, original_filename, stored_path, "
            "size_bytes, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (vendor_id, doc.doc_type.value, doc.original_filename, doc.stored_path,
             doc.size_bytes, doc.uploaded_at),
        )
        doc_id = cur.lastrowid
    log_event(vendor_id, "system", "document_uploaded",
              {"doc_type": doc.doc_type.value, "filename": doc.original_filename})
    return doc_id


def list_documents(vendor_id: int) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM documents WHERE vendor_id = ? AND superseded = 0 "
                            "ORDER BY id", (vendor_id,)).fetchall()
    return [_doc_row(d) for d in rows]


def supersede_documents(vendor_id: int, doc_type: str) -> None:
    """Hide older files of this type (kept on disk and in the audit log)."""
    with closing(_connect()) as conn, conn:
        n = conn.execute("UPDATE documents SET superseded = 1 WHERE vendor_id = ? AND doc_type = ? "
                         "AND superseded = 0", (vendor_id, doc_type)).rowcount
    if n:
        log_event(vendor_id, "reviewer", "document_replaced", {"doc_type": doc_type, "replaced": n})


def save_extraction(document_id: int, extraction: DocumentExtraction) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE documents SET extraction_json = ? WHERE id = ?",
                     (extraction.model_dump_json(), document_id))


# ---------- Reviews and corrections (learning data) ----------

def add_review(vendor_id: int, reviewer: str, action: str, reason: str,
               system_status: str, final_status: str, agreed: bool,
               incorrect_checks: list[str], snapshot: dict) -> int:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO reviews (vendor_id, timestamp, reviewer, action, reason, system_status, "
            "final_status, agreed_with_system, incorrect_checks_json, snapshot_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vendor_id, utc_now(), reviewer, action, reason, system_status, final_status,
             int(agreed), json.dumps(incorrect_checks), json.dumps(snapshot)),
        )
        return cur.lastrowid


def add_correction(review_id: int, vendor_id: int, document_id: int | None, doc_type: str,
                   field_name: str, extracted_value: str | None, corrected_value: str,
                   note: str = "") -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO corrections (review_id, vendor_id, document_id, doc_type, field_name, "
            "extracted_value, corrected_value, note, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (review_id, vendor_id, document_id, doc_type, field_name, extracted_value,
             corrected_value, note, utc_now()),
        )


def list_reviews() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM reviews ORDER BY id").fetchall()
    return [{**dict(r), "incorrect_checks": json.loads(r["incorrect_checks_json"])} for r in rows]


def list_corrections(doc_type: str | None = None, limit: int | None = None) -> list[dict]:
    sql, params = "SELECT * FROM corrections", []
    if doc_type:
        sql += " WHERE doc_type = ?"
        params.append(doc_type)
    sql += " ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with closing(_connect()) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
