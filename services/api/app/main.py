import os
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .book_extraction import BookExtraction, OpenRouterExtractionProvider
from .book_repository import BookRecord, BookRepository, PostgresBookRepository
from .config import settings
from .pdf_extraction import extract_pdf
from .storage import ObjectStorage

app = FastAPI(title="AutoApply API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
book_repository = (
    PostgresBookRepository() if os.getenv("DATABASE_URL") else BookRepository()
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "AutoApply API",
        "health": "/health",
        "upload_book": "POST /books",
    }


class HealthResponse(BaseModel):
    status: str
    service: str


class UploadResponse(BaseModel):
    file_hash: str
    object_ref: str
    filename: str
    page_count: int
    extracted_text: str
    used_ocr: bool
    deduplicated: bool


class ExtractionResponse(BaseModel):
    file_hash: str
    extraction: BookExtraction


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="api")


@app.post("/books", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_book(response: Response, file: UploadFile = File(...)) -> UploadResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are supported")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty")

    file_hash = sha256(content).hexdigest()
    existing_book = book_repository.get_by_hash(file_hash)
    if existing_book:
        response.status_code = status.HTTP_200_OK
        return UploadResponse(
            file_hash=existing_book.file_hash,
            object_ref=existing_book.object_ref,
            filename=existing_book.filename,
            page_count=existing_book.page_count,
            extracted_text=existing_book.extracted_text,
            used_ocr=existing_book.used_ocr,
            deduplicated=True,
        )

    try:
        extraction = extract_pdf(content)
        object_name = f"books/{uuid4()}.pdf"
        object_ref = ObjectStorage().put_pdf(object_name, BytesIO(content))
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"Could not process PDF: {error}") from error

    book_repository.save(
        BookRecord(
            file_hash=file_hash,
            object_ref=object_ref,
            filename=file.filename or "book.pdf",
            page_count=extraction.page_count,
            extracted_text=extraction.text,
            used_ocr=extraction.used_ocr,
        )
    )
    return UploadResponse(
        file_hash=file_hash,
        object_ref=object_ref,
        filename=file.filename or "book.pdf",
        page_count=extraction.page_count,
        extracted_text=extraction.text,
        used_ocr=extraction.used_ocr,
        deduplicated=False,
    )


@app.post("/books/{file_hash}/extract", response_model=ExtractionResponse)
def extract_book(file_hash: str) -> ExtractionResponse:
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenRouter extraction is not configured; set OPENROUTER_API_KEY",
        )

    book = book_repository.get_by_hash(file_hash)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    try:
        extraction = OpenRouterExtractionProvider(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
        ).extract(book.extracted_text, book.page_count)
        book_repository.save_extraction(file_hash, extraction.model_dump_json())
    except Exception as error:
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract structured book data: {error}",
        ) from error

    return ExtractionResponse(file_hash=file_hash, extraction=extraction)
