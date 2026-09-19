import os
import logging
import json
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .book_extraction import BookExtraction, G4FExtractionProvider
from .book_repository import BookRecord, BookRepository, CvRecord, PostgresBookRepository
from .config import settings
from .cv import CvProfile, parse_cv
from .embeddings import TextEmbedder, get_embedder
from .indexing import build_book_entries
from .pdf_extraction import extract_pdf
from .storage import ObjectStorage

app = FastAPI(title="AutoApply API", version="0.1.0")
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
book_repository = (
    PostgresBookRepository() if os.getenv("DATABASE_URL") else BookRepository()
)
embedder: TextEmbedder = get_embedder()


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


class IndexResponse(BaseModel):
    book_hash: str
    indexed: int


class IndexSubjectRow(BaseModel):
    book_hash: str
    reference: str | None = None
    title: str
    page_start: int | None = None
    page_end: int | None = None
    text: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="api")


class BookInfoRow(BaseModel):
    file_hash: str
    filename: str
    page_count: int
    has_extraction: bool
    subjects: int


@app.get("/books", response_model=list[BookInfoRow])
def list_books() -> list[BookInfoRow]:
    return [BookInfoRow(**row) for row in book_repository.list_books()]


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
    provider = G4FExtractionProvider(
        providers=settings.g4f_provider_pool,
        max_tokens=settings.g4f_max_tokens,
        chunk_characters=settings.g4f_chunk_characters,
    )

    book = book_repository.get_by_hash(file_hash)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    try:
        extraction = provider.extract(book.extracted_text, book.page_count)
        logger.info(
            "Book extraction completed with provider pool=%s", settings.g4f_provider_pool
        )
        book_repository.save_extraction(file_hash, extraction.model_dump_json())
    except Exception as error:
        logger.exception("Book extraction failed for %s", file_hash)
        raise HTTPException(
            status_code=500,
            detail=f"{type(error).__name__}: {error}",
        ) from error

    return ExtractionResponse(file_hash=file_hash, extraction=extraction)


def _embed_entries(entries: list) -> list:
    embedder_name = getattr(embedder, "name", "null")
    if embedder_name == "null":
        return entries
    try:
        vectors = embedder.embed(
            [f"{entry.title}\n{(entry.text or '')[:2000]}" for entry in entries]
        )
    except Exception:
        logger.exception("Embedding failed; storing index without vectors")
        return entries
    return [
        replace(entry, embedding=vector) if vector else entry
        for entry, vector in zip(entries, vectors)
    ]


def _seed_index(file_hash: str) -> IndexResponse:
    book = book_repository.get_by_hash(file_hash)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.extraction_json:
        raise HTTPException(
            status_code=409,
            detail="Book has no extraction yet; run POST /books/{hash}/extract first",
        )
    entries = _embed_entries(build_book_entries(book.extraction_json))
    book_repository.replace_index_subjects(file_hash, entries)
    return IndexResponse(book_hash=file_hash, indexed=len(entries))


@app.post("/books/{file_hash}/index", response_model=IndexResponse)
def index_book(file_hash: str) -> IndexResponse:
    return _seed_index(file_hash)


@app.post("/books/index-all", response_model=list[IndexResponse])
def index_all_books() -> list[IndexResponse]:
    return [
        _seed_index(file_hash)
        for file_hash in book_repository.list_hashes_with_extraction()
    ]


@app.get("/books/{file_hash}/index", response_model=list[IndexSubjectRow])
def get_book_index(file_hash: str) -> list[IndexSubjectRow]:
    return [
        IndexSubjectRow(**row) for row in book_repository.get_index_subjects(file_hash)
    ]


class SearchResult(BaseModel):
    book_hash: str
    reference: str | None = None
    title: str
    page_start: int | None = None
    page_end: int | None = None
    text: str
    score: float
    source: str = "keyword"


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


@app.get("/search", response_model=SearchResponse)
def keyword_search(
    query: str = Query(..., alias="q", min_length=1, description="Free-text keyword query"),
    limit: int = Query(20, ge=1, le=100),
    dense: bool = Query(False, description="Run hybrid search (keyword + dense RRF)"),
) -> SearchResponse:
    query_embedding: list[float] | None = None
    if dense and getattr(embedder, "name", "null") != "null":
        try:
            vectors = embedder.embed([query])
            query_embedding = vectors[0] if vectors else None
        except Exception:
            logger.exception("Query embedding failed; falling back to keyword search")
            query_embedding = None
    results = (
        book_repository.search_hybrid(query, limit, query_embedding=query_embedding)
        if dense
        else book_repository.search_keywords(query, limit)
    )
    return SearchResponse(
        query=query,
        results=[SearchResult(**row) for row in results],
    )


class CvProfileResponse(BaseModel):
    skills: list[str] = []
    education: list[str] = []
    experience: list[str] = []
    projects: list[str] = []
    certifications: list[str] = []


class CvResponse(BaseModel):
    cv_hash: str
    filename: str
    profile: CvProfileResponse


class CvMatchResponse(BaseModel):
    cv_hash: str
    profile_query: str
    results: list[SearchResult]


def _read_upload_text(filename: str, content: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        return extract_pdf(content).text
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


@app.post("/cv", response_model=CvResponse, status_code=status.HTTP_201_CREATED)
def upload_cv(file: UploadFile = File(...)) -> CvResponse:
    content = file.file.read()
    cv_hash = sha256(content).hexdigest()
    raw_text = _read_upload_text(file.filename or "cv.txt", content)
    profile = parse_cv(raw_text)
    profile_payload = {
        "skills": profile.skills,
        "education": profile.education,
        "experience": profile.experience,
        "projects": profile.projects,
        "certifications": profile.certifications,
    }
    book_repository.save_cv(
        CvRecord(
            cv_hash=cv_hash,
            filename=file.filename or "cv.txt",
            raw_text=raw_text,
            profile_json=json.dumps(profile_payload),
        )
    )
    return CvResponse(cv_hash=cv_hash, filename=file.filename or "cv.txt", profile=profile_payload)


@app.get("/cv/{cv_hash}", response_model=CvResponse)
def get_cv(cv_hash: str) -> CvResponse:
    record = book_repository.get_cv(cv_hash)
    if not record:
        raise HTTPException(status_code=404, detail="CV not found")
    return CvResponse(
        cv_hash=record.cv_hash,
        filename=record.filename,
        profile=json.loads(record.profile_json),
    )


@app.post("/cv/{cv_hash}/match", response_model=CvMatchResponse)
def match_cv(
    cv_hash: str,
    limit: int = Query(10, ge=1, le=100),
    dense: bool = Query(True, description="Use hybrid (keyword + dense RRF) matching"),
) -> CvMatchResponse:
    record = book_repository.get_cv(cv_hash)
    if not record:
        raise HTTPException(status_code=404, detail="CV not found")
    profile = CvProfile(**json.loads(record.profile_json))
    query = profile.query
    query_embedding: list[float] | None = None
    if dense and getattr(embedder, "name", "null") != "null" and query:
        try:
            vectors = embedder.embed([query])
            query_embedding = vectors[0] if vectors else None
        except Exception:
            logger.exception("CV query embedding failed; falling back to keyword matching")
            query_embedding = None
    results = (
        book_repository.search_hybrid(query, limit, query_embedding=query_embedding)
        if dense
        else book_repository.search_keywords(query, limit)
    )
    return CvMatchResponse(
        cv_hash=cv_hash,
        profile_query=query,
        results=[SearchResult(**row) for row in results],
    )


class CvProfileUpdate(BaseModel):
    skills: list[str] = []
    education: list[str] = []
    experience: list[str] = []
    projects: list[str] = []
    certifications: list[str] = []


@app.post("/cv/{cv_hash}/profile", response_model=CvResponse)
def update_cv_profile(cv_hash: str, update: CvProfileUpdate) -> CvResponse:
    record = book_repository.get_cv(cv_hash)
    if not record:
        raise HTTPException(status_code=404, detail="CV not found")
    profile_payload = update.model_dump()
    book_repository.save_cv(
        CvRecord(
            cv_hash=record.cv_hash,
            filename=record.filename,
            raw_text=record.raw_text,
            profile_json=json.dumps(profile_payload),
        )
    )
    return CvResponse(
        cv_hash=record.cv_hash,
        filename=record.filename,
        profile=profile_payload,
    )
