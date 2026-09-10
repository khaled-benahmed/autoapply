from dataclasses import dataclass
from io import BytesIO

import fitz
import pytesseract
from PIL import Image


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    page_count: int
    used_ocr: bool


def extract_pdf(content: bytes) -> ExtractionResult:
    document = fitz.open(stream=content, filetype="pdf")
    page_text = [page.get_text("text").strip() for page in document]
    text = "\n\n".join(
        f"[PAGE {index}]\n{value}"
        for index, value in enumerate(page_text, start=1)
        if value
    )
    if text:
        return ExtractionResult(text=text, page_count=len(document), used_ocr=False)

    ocr_pages = []
    for index, page in enumerate(document, start=1):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png")))
        page_text = pytesseract.image_to_string(image).strip()
        if page_text:
            ocr_pages.append(f"[PAGE {index}]\n{page_text}")
    return ExtractionResult(
        text="\n\n".join(value for value in ocr_pages if value),
        page_count=len(document),
        used_ocr=True,
    )