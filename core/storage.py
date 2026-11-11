"""
Saves uploaded PDFs to disk: uploads/<vendor_id>/<doc_type>__<filename>.pdf

The database stores only the path. On Streamlit Community Cloud this folder
is NOT permanent (it is wiped when the app restarts); see README "Deployment".
"""

import os
import re
from pathlib import Path

from core.models import DocumentType, UploadedDocument

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def get_upload_root() -> Path:
    return Path(os.environ.get("VENDOR_UPLOAD_DIR", PROJECT_ROOT / "uploads"))


def safe_filename(name: str) -> str:
    """Keep letters, digits, dot, dash, underscore. Stops '../' tricks."""
    name = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100] or "document.pdf"


def save_upload(vendor_id: int, doc_type: DocumentType, filename: str,
                data: bytes) -> UploadedDocument:
    """Validate and save one uploaded file. Raises ValueError with a clear message."""
    if len(data) == 0:
        raise ValueError(f"'{filename}' is empty.")
    if len(data) > MAX_BYTES:
        raise ValueError(f"'{filename}' is larger than 10 MB.")
    if not data.startswith(b"%PDF"):
        raise ValueError(f"'{filename}' is not a PDF file.")

    folder = get_upload_root() / str(vendor_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_type.value}__{safe_filename(filename)}"
    path.write_bytes(data)
    return UploadedDocument(doc_type=doc_type, original_filename=filename,
                            stored_path=str(path), size_bytes=len(data))
