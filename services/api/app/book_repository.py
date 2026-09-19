from dataclasses import dataclass
import re
from threading import Lock
from typing import Any
import unicodedata

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings


@dataclass(frozen=True)
class BookRecord:
    file_hash: str
    object_ref: str
    filename: str
    page_count: int
    extracted_text: str
    used_ocr: bool
    extraction_json: str | None = None


@dataclass(frozen=True)
class CvRecord:
    cv_hash: str
    filename: str
    raw_text: str
    profile_json: str


class BookRepository:
    def __init__(self) -> None:
        self._records: dict[str, BookRecord] = {}
        self._index: dict[str, list[dict]] = {}
        self._cvs: dict[str, CvRecord] = {}
        self._lock = Lock()

    def get_by_hash(self, file_hash: str) -> BookRecord | None:
        with self._lock:
            return self._records.get(file_hash)

    def save_cv(self, record: CvRecord) -> None:
        with self._lock:
            self._cvs[record.cv_hash] = record

    def get_cv(self, cv_hash: str) -> CvRecord | None:
        with self._lock:
            return self._cvs.get(cv_hash)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._index.clear()
            self._cvs.clear()

    def save(self, record: BookRecord) -> None:
        with self._lock:
            self._records[record.file_hash] = record

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._index.clear()

    def save_extraction(self, file_hash: str, extraction_json: str) -> None:
        with self._lock:
            record = self._records[file_hash]
            self._records[file_hash] = BookRecord(
                file_hash=record.file_hash,
                object_ref=record.object_ref,
                filename=record.filename,
                page_count=record.page_count,
                extracted_text=record.extracted_text,
                used_ocr=record.used_ocr,
                extraction_json=extraction_json,
            )

    def list_hashes_with_extraction(self) -> list[str]:
        with self._lock:
            return [hash for hash, record in self._records.items() if record.extraction_json]

    def list_books(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "file_hash": file_hash,
                    "filename": record.filename,
                    "page_count": record.page_count,
                    "has_extraction": record.extraction_json is not None,
                    "subjects": len(self._index.get(file_hash, [])),
                }
                for file_hash, record in self._records.items()
            ]

    def replace_index_subjects(self, file_hash: str, records: list[Any]) -> None:
        with self._lock:
            self._index[file_hash] = [_index_row(record, file_hash) for record in records]

    def get_index_subjects(self, file_hash: str) -> list[dict]:
        with self._lock:
            return list(self._index.get(file_hash, []))

    @staticmethod
    def _fold(text: str) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFD", text or "").lower()
            if unicodedata.category(char) != "Mn"
        )

    def _keyword_rows(self, query: str) -> list[dict]:
        terms = [
            term
            for term in re.split(r"\s+", re.sub(r"[^\w\s'-]", " ", self._fold(query)).strip())
            if term
        ]
        if not terms:
            return []
        compact_query = re.sub(r"\s+", "", self._fold(query))
        results: list[dict] = []
        with self._lock:
            index = list(self._index.values())
        for rows in index:
            for row in rows:
                text = self._fold(row["text"])
                title = self._fold(row["title"])
                compact_reference = re.sub(r"\s+", "", self._fold(row["reference"]))
                text_hits = sum(1 for term in terms if re.search(r"\b" + re.escape(term) + r"\b", text))
                title_hits = sum(1 for term in terms if re.search(r"\b" + re.escape(term) + r"\b", title))
                score = title_hits * 2.0 + text_hits * 1.0
                if compact_query and compact_query in compact_reference:
                    score += 0.5
                if score > 0:
                    result = dict(row)
                    result["score"] = score
                    results.append(result)
        results.sort(key=lambda result: -result["score"])
        return results

    def search_keywords(self, query: str, limit: int = 20) -> list[dict]:
        results = self._keyword_rows(query)[:limit]
        for row in results:
            row["source"] = "keyword"
        return results

    def search_dense(self, query_embedding: list[float], limit: int = 20) -> list[dict]:
        if not query_embedding:
            return []
        results: list[dict] = []
        with self._lock:
            index = list(self._index.values())
        for rows in index:
            for row in rows:
                if not row.get("embedding"):
                    continue
                similarity = _cosine_similarity(query_embedding, row["embedding"])
                if similarity > 0.2:
                    result = dict(row)
                    result["score"] = similarity
                    result["source"] = "dense"
                    results.append(result)
        results.sort(key=lambda result: -result["score"])
        return results[:limit]

    def search_hybrid(
        self,
        query: str,
        limit: int = 20,
        query_embedding: list[float] | None = None,
        k: int = 60,
    ) -> list[dict]:
        keyword_rows = self._keyword_rows(query)[
            : max(limit * 4, _CANDIDATE_POOL)
        ]
        dense_rows = self.search_dense(query_embedding, max(limit * 4, _CANDIDATE_POOL))
        if not query_embedding:
            return keyword_rows[:limit]
        return _rff_merge(keyword_rows, dense_rows, limit=limit, k=k)


def _index_row(record: Any, file_hash: str) -> dict:
    return {
        "book_hash": file_hash,
        "reference": record.reference,
        "title": record.title,
        "text": record.text,
        "raw_text": record.raw_text,
        "page_start": record.page_start,
        "page_end": record.page_end,
        "embedding": record.embedding,
    }


_CANDIDATE_POOL = 100


def _tag_source(rows: list, source: str) -> list[dict]:
    return [dict(row, source=source) for row in rows]


def _rff_merge(
    keyword_rows: list[dict],
    dense_rows: list[dict],
    limit: int,
    k: int = 60,
) -> list[dict]:
    def identity(row: dict) -> tuple:
        return (row["book_hash"], row["reference"], row["title"])

    rrf: dict[tuple, float] = {}
    meta: dict[tuple, dict] = {}
    sources: dict[tuple, set[str]] = {}
    for rows, label in ((keyword_rows, "keyword"), (dense_rows, "dense")):
        for rank, row in enumerate(rows):
            ident = identity(row)
            rrf[ident] = rrf.get(ident, 0.0) + 1.0 / (k + rank + 1)
            meta.setdefault(ident, row)
            sources.setdefault(ident, set()).add(label)
    ordered = sorted(meta, key=lambda ident: -rrf[ident])
    merged = []
    for ident in ordered:
        merged_row = dict(meta[ident])
        merged_row["score"] = rrf[ident]
        merged_row["source"] = sorted(sources[ident])[0] if len(sources[ident]) == 1 else "both"
        merged.append(merged_row)
    return merged[:limit]


def _vector_literal(embedding: list[float] | None) -> str | None:
    if not embedding:
        return None
    return "[" + ",".join(str(value) for value in embedding) + "]"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


_KEYWORD_SELECT = """
    SELECT TRIM(book_hash) AS book_hash, reference, title, text, raw_text,
           page_start, page_end,
           COALESCE(ts_rank_cd(tokens, plainto_tsquery('app_search', %s)), 0) * 3.0
           + COALESCE(similarity(COALESCE(title, ''), %s), 0) * 2.0
           + COALESCE(similarity(text, %s), 0)
           + CASE WHEN REPLACE(COALESCE(reference, ''), ' ', '') ILIKE '%%' || %s || '%%' THEN 0.5 ELSE 0 END AS score
    FROM book_subjects
    WHERE plainto_tsquery('app_search', %s) @@ tokens
       OR COALESCE(similarity(text, %s), 0) > 0.1
       OR REPLACE(COALESCE(reference, ''), ' ', '') ILIKE '%%' || %s || '%%'
"""


class PostgresBookRepository:
    _CV_SCHEMA_DDL = """
        CREATE TABLE IF NOT EXISTS cv_profiles (
            id BIGSERIAL PRIMARY KEY,
            cv_hash CHAR(64) NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            profile_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    _SCHEMA_DDL = """
        CREATE TABLE IF NOT EXISTS books (
            id BIGSERIAL PRIMARY KEY,
            file_hash CHAR(64) NOT NULL UNIQUE,
            object_ref TEXT NOT NULL,
            filename TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            extracted_text TEXT NOT NULL,
            used_ocr BOOLEAN NOT NULL,
            extraction_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    _SUBJECTS_SCHEMA_DDL = """
        CREATE TABLE IF NOT EXISTS book_subjects (
            id BIGSERIAL PRIMARY KEY,
            book_hash CHAR(64) NOT NULL REFERENCES books(file_hash) ON DELETE CASCADE,
            reference TEXT,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            tokens TSVECTOR,
            embedding VECTOR(384),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE NULLS NOT DISTINCT (book_hash, reference, title)
        )
    """
    _SUBJECTS_INDEX_DDL = """
        CREATE INDEX IF NOT EXISTS book_subjects_tokens_idx ON book_subjects USING gin (tokens)
    """
    _SUBJECTS_TRGM_INDEX_DDL = """
        CREATE INDEX IF NOT EXISTS book_subjects_text_trgm_idx
        ON book_subjects USING gin (text gin_trgm_ops)
    """
    _SUBJECTS_HNSW_INDEX_DDL = """
        CREATE INDEX IF NOT EXISTS book_subjects_embedding_hnsw_idx
        ON book_subjects USING hnsw (embedding vector_cosine_ops)
    """
    _SUBJECTS_ADD_EMBEDDING_DDL = """
        ALTER TABLE book_subjects ADD COLUMN IF NOT EXISTS embedding VECTOR(384)
    """
    _SEARCH_CONFIG_DDL = """
        DO $app_search$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_ts_config WHERE cfgname = 'app_search') THEN
                CREATE TEXT SEARCH CONFIGURATION app_search (COPY = pg_catalog.simple);
                ALTER TEXT SEARCH CONFIGURATION app_search
                    ALTER MAPPING FOR asciiword, asciihword, word, numword,
                    hword, hword_part
                    WITH unaccent, simple;
            END IF;
        END $app_search$;
    """
    _SCHEMA_STATEMENTS = (
        "CREATE EXTENSION IF NOT EXISTS unaccent",
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        _SCHEMA_DDL,
        _CV_SCHEMA_DDL,
        _SUBJECTS_SCHEMA_DDL,
        _SEARCH_CONFIG_DDL,
        _SUBJECTS_INDEX_DDL,
        _SUBJECTS_TRGM_INDEX_DDL,
        _SUBJECTS_ADD_EMBEDDING_DDL,
        _SUBJECTS_HNSW_INDEX_DDL,
    )

    def __init__(
        self,
        database_url: str = settings.database_url,
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        self._schema_lock = Lock()
        self._schema_ready = False

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            self._pool.open()
            with self._pool.connection(timeout=10) as connection:
                for statement in self._SCHEMA_STATEMENTS:
                    connection.execute(statement)
            self._schema_ready = True

    @staticmethod
    def _record_from_row(row: dict) -> BookRecord:
        return BookRecord(
            file_hash=row["file_hash"],
            object_ref=row["object_ref"],
            filename=row["filename"],
            page_count=row["page_count"],
            extracted_text=row["extracted_text"],
            used_ocr=row["used_ocr"],
            extraction_json=row["extraction_json"],
        )

    def get_by_hash(self, file_hash: str) -> BookRecord | None:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            row = connection.execute(
                """
                SELECT file_hash, object_ref, filename, page_count,
                       extracted_text, used_ocr, extraction_json
                FROM books
                WHERE file_hash = %s
                """,
                (file_hash,),
            ).fetchone()
        return self._record_from_row(row) if row else None

    def save(self, record: BookRecord) -> None:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            connection.execute(
                """
                INSERT INTO books (
                    file_hash, object_ref, filename, page_count,
                    extracted_text, used_ocr
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_hash) DO NOTHING
                """,
                (
                    record.file_hash,
                    record.object_ref,
                    record.filename,
                    record.page_count,
                    record.extracted_text,
                    record.used_ocr,
                ),
            )

    def save_cv(self, record: CvRecord) -> None:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            connection.execute(
                """
                INSERT INTO cv_profiles (cv_hash, filename, raw_text, profile_json)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (cv_hash) DO UPDATE
                SET filename = EXCLUDED.filename,
                    raw_text = EXCLUDED.raw_text,
                    profile_json = EXCLUDED.profile_json
                """,
                (
                    record.cv_hash,
                    record.filename,
                    record.raw_text,
                    record.profile_json,
                ),
            )

    def get_cv(self, cv_hash: str) -> CvRecord | None:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            row = connection.execute(
                """
                SELECT TRIM(cv_hash) AS cv_hash, filename, raw_text,
                       profile_json::text AS profile_json
                FROM cv_profiles
                WHERE cv_hash = %s
                """,
                (cv_hash,),
            ).fetchone()
        if not row:
            return None
        return CvRecord(
            cv_hash=row["cv_hash"],
            filename=row["filename"],
            raw_text=row["raw_text"],
            profile_json=row["profile_json"],
        )

    def clear(self) -> None:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            connection.execute("TRUNCATE TABLE books RESTART IDENTITY")

    def save_extraction(self, file_hash: str, extraction_json: str) -> None:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            connection.execute(
                "UPDATE books SET extraction_json = %s::jsonb WHERE file_hash = %s",
                (extraction_json, file_hash),
            )

    def list_hashes_with_extraction(self) -> list[str]:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT TRIM(file_hash) AS file_hash
                FROM books
                WHERE extraction_json IS NOT NULL
                """
            ).fetchall()
        return [row["file_hash"] for row in rows]

    def list_books(self) -> list[dict]:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            rows = connection.execute(
                """
                SELECT TRIM(b.file_hash) AS file_hash, b.filename, b.page_count,
                       (b.extraction_json IS NOT NULL) AS has_extraction,
                       COUNT(s.id) AS subjects
                FROM books b
                LEFT JOIN book_subjects s ON TRIM(s.book_hash) = TRIM(b.file_hash)
                GROUP BY b.id
                ORDER BY b.id
                """
            ).fetchall()
        return list(rows)

    def replace_index_subjects(self, file_hash: str, records: list[Any]) -> None:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            connection.execute("DELETE FROM book_subjects WHERE book_hash = %s", (file_hash,))
            if not records:
                return
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO book_subjects (
                        book_hash, reference, title, text, raw_text, page_start, page_end, tokens, embedding
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        to_tsvector('app_search', COALESCE(%s, '') || ' ' || COALESCE(%s, '') || ' ' || COALESCE(%s, '')),
                        %s::vector
                    )
                    """,
                    [
                        (
                            file_hash,
                            record.reference,
                            record.title,
                            record.text,
                            record.raw_text,
                            record.page_start,
                            record.page_end,
                            record.text,
                            record.title,
                            record.reference,
                            _vector_literal(record.embedding),
                        )
                        for record in records
                    ],
                )

    def get_index_subjects(self, file_hash: str) -> list[dict]:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            rows = connection.execute(
                """
                SELECT TRIM(book_hash) AS book_hash, reference, title, text, raw_text,
                       page_start, page_end
                FROM book_subjects
                WHERE book_hash = %s
                ORDER BY id
                """,
                (file_hash,),
            ).fetchall()
        return rows

    def search_keywords(self, query: str, limit: int = 20) -> list[dict]:
        self._ensure_schema()
        with self._pool.connection(timeout=10) as connection:
            rows = connection.execute(
                _KEYWORD_SELECT + "ORDER BY score DESC, id LIMIT %s",
                (query, query, query, query, query, query, query, limit),
            ).fetchall()
        return _tag_source(rows, "keyword")

    def search_dense(self, query_embedding: list[float], limit: int = 20) -> list[dict]:
        self._ensure_schema()
        vector = _vector_literal(query_embedding)
        with self._pool.connection(timeout=10) as connection:
            rows = connection.execute(
                """
                SELECT TRIM(book_hash) AS book_hash, reference, title, text, raw_text,
                       page_start, page_end,
                       (1 - (embedding <=> %s::vector)) AS score
                FROM book_subjects
                WHERE embedding IS NOT NULL
                  AND (1 - (embedding <=> %s::vector)) > 0.2
                ORDER BY score DESC, id
                LIMIT %s
                """,
                (vector, vector, limit),
            ).fetchall()
        return _tag_source(rows, "dense")

    def search_hybrid(
        self,
        query: str,
        limit: int = 20,
        query_embedding: list[float] | None = None,
        k: int = 60,
    ) -> list[dict]:
        self._ensure_schema()
        pool = max(limit * 4, _CANDIDATE_POOL)
        keyword_rows = self.search_keywords(query, pool)
        if not query_embedding:
            return keyword_rows[:limit]
        dense_rows = self.search_dense(query_embedding, pool)
        return _rff_merge(keyword_rows, dense_rows, limit=limit, k=k)