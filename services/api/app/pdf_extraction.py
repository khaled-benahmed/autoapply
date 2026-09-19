from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
import os

import fitz
import pytesseract
from PIL import Image


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    page_count: int
    used_ocr: bool


def _ocr_page(page: fitz.Page) -> str:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png")))
    return pytesseract.image_to_string(image).strip()


def extract_pdf(content: bytes) -> ExtractionResult:
    with fitz.open(stream=content, filetype="pdf") as document:
        page_text = [page.get_text("text").strip() for page in document]
        text = "\n\n".join(
            f"[PAGE {index}]\n{value}"
            for index, value in enumerate(page_text, start=1)
            if value
        )
        if text:
            return ExtractionResult(text=text, page_count=len(document), used_ocr=False)

        pages = list(document)
        with ThreadPoolExecutor(max_workers=min(len(pages), os.cpu_count() or 1)) as executor:
            ocr_pages = [
                f"[PAGE {index}]\n{value}"
                for index, value in enumerate(executor.map(_ocr_page, pages), start=1)
                if value
            ]
        return ExtractionResult(
            text="\n\n".join(ocr_pages),
            page_count=len(document),
            used_ocr=True,
        )