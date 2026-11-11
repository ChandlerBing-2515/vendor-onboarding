"""
Reads the text layer of a PDF with PyMuPDF.

Important: a scanned PDF is a picture of a page. It has no text layer, so
there is nothing to read as text. We detect that ("needs_ocr"). If an AI
provider is configured, the pipeline then sends page images to the AI instead
(see render_pages below and extraction.extract_fields_from_images).
"""

from dataclasses import dataclass, field

import pymupdf

MIN_CHARS_PER_PAGE = 25  # less than this on average = probably scanned


@dataclass
class PdfText:
    readable: bool
    pages: list[str] = field(default_factory=list)
    needs_ocr: bool = False
    problem: str = ""

    @property
    def full_text(self) -> str:
        return "\n".join(f"[page {i + 1}]\n{t}" for i, t in enumerate(self.pages))

    @property
    def char_count(self) -> int:
        return sum(len(p.strip()) for p in self.pages)


def extract_text(path: str) -> PdfText:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # corrupt or not a PDF
        return PdfText(readable=False, problem=f"File could not be opened as a PDF ({exc}).")

    with doc:
        if doc.needs_pass:
            return PdfText(readable=False, problem="PDF is password-protected.")
        if doc.page_count == 0:
            return PdfText(readable=False, problem="PDF has no pages.")
        pages = [page.get_text("text") for page in doc]

    result = PdfText(readable=True, pages=pages)
    if result.char_count < MIN_CHARS_PER_PAGE * len(pages):
        result.readable = False
        result.needs_ocr = True
        result.problem = ("Little or no text found. This looks like a scanned image, "
                          "so OCR would be needed to read it.")
    return result


MAX_IMAGE_PAGES = 5   # only the first pages are sent, to limit cost and size
IMAGE_DPI = 150       # enough for the AI to read normal-size print


def render_pages(path: str, max_pages: int = MAX_IMAGE_PAGES, dpi: int = IMAGE_DPI) -> list[bytes]:
    """Turn the first pages of a PDF into PNG images (for scanned documents)."""
    with pymupdf.open(path) as doc:
        return [doc[i].get_pixmap(dpi=dpi).tobytes("png")
                for i in range(min(max_pages, doc.page_count))]
