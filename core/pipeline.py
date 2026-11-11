"""
Runs every stage for one vendor, in order, and reports progress as it goes.

The Streamlit page passes a `progress` function so it can show each stage
live (the "live run view"). Tests pass nothing and it runs silently.
"""

from typing import Callable

from core import database as db
from core.comparison import compare_all
from core.decision import recommend
from core.extraction import ai_available, extract_fields, extract_fields_from_images
from core.models import DocumentExtraction, DocumentType, Recommendation
from core.pdf_text import extract_text, render_pages
from core.validation import run_form_checks

Progress = Callable[[str], None]


def _silent(_: str) -> None:
    pass


def read_document(doc: dict, use_examples: bool = True) -> DocumentExtraction:
    doc_type = DocumentType(doc["doc_type"])
    pdf = extract_text(doc["stored_path"])
    base = dict(document_id=doc["id"], doc_type=doc_type, filename=doc["original_filename"],
                page_count=len(pdf.pages), text_chars=pdf.char_count)
    if not pdf.readable:
        if pdf.needs_ocr and ai_available():
            # Scanned document: let the AI read the page images instead
            try:
                fields, method = extract_fields_from_images(
                    render_pages(doc["stored_path"]), doc_type, use_examples=use_examples)
                return DocumentExtraction(readable=True, needs_ocr=True, read_from_images=True,
                                          method=method, fields=fields, **base)
            except Exception as exc:
                return DocumentExtraction(
                    readable=False, needs_ocr=True, method="none", **base,
                    problem=f"{pdf.problem} AI image reading also failed "
                            f"({type(exc).__name__}: {str(exc)[:150]}).")
        return DocumentExtraction(readable=False, needs_ocr=pdf.needs_ocr, method="none",
                                  problem=pdf.problem, **base)
    fields, method = extract_fields(pdf.pages, doc_type, use_examples=use_examples)
    return DocumentExtraction(readable=True, method=method, fields=fields, **base)


def run_checks(vendor_id: int, progress: Progress = _silent,
               reextract: bool = True, use_examples: bool = True) -> Recommendation:
    vendor = db.get_vendor(vendor_id)
    if vendor is None:
        raise ValueError(f"Vendor {vendor_id} not found.")
    submission, docs = vendor["submission"], vendor["documents"]

    progress("Checking form fields against the configured rules")
    findings = run_form_checks(submission, [d["doc_type"] for d in docs])
    progress(f"Form checks done: {sum(f.outcome != 'pass' for f in findings)} open issue(s)")

    extractions = []
    for doc in docs:
        if not reextract and doc["extraction"] is not None:
            extractions.append(doc["extraction"])
            progress(f"Re-using earlier extraction for {doc['original_filename']}")
            continue
        progress(f"Reading {doc['original_filename']}")
        ex = read_document(doc, use_examples=use_examples)
        db.save_extraction(doc["id"], ex)
        extractions.append(ex)
        if ex.read_from_images:
            progress(f"{doc['original_filename']} is a scan: read from page images ({ex.method}); "
                     "a reviewer must confirm")
        elif ex.readable:
            progress(f"Extracted fields from {doc['original_filename']} ({ex.method})")
        else:
            progress(f"Could not read {doc['original_filename']}: {ex.problem}")

    progress("Comparing form values with document values")
    findings += compare_all(submission, extractions)

    progress("Building recommendation")
    rec = recommend(findings)
    db.save_results(vendor_id, findings, rec)
    progress(f"Recommendation: {rec.status.value}. {rec.headline}")
    return rec
