from dataclasses import dataclass
from threading import Lock

import psycopg

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


class BookRepository:
    def __init__(self) -> None:
        self._records: dict[str, BookRecord] = {}
        self._lock = Lock()

    def get_by_hash(self, file_hash: str) -> BookRecord | None:
        with self._lock:
            return self._records.get(file_hash)

    def save(self, record: BookRecord) -> None:
        with self._lock:
            self._records[record.file_hash] = record

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

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


class PostgresBookRepository:
    def __init__(self, database_url: str = settings.database_url) -> None:
        self.database_url = database_url
        self._create_table()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url)

    def _create_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
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
            )
            connection.execute(
                "ALTER TABLE books ADD COLUMN IF NOT EXISTS extraction_json JSONB"
            )

    @staticmethod
    def _record_from_row(row: tuple) -> BookRecord:
        return BookRecord(
            file_hash=row[0],
            object_ref=row[1],
            filename=row[2],
            page_count=row[3],
            extracted_text=row[4],
            used_ocr=row[5],
            extraction_json=row[6],
        )

    def get_by_hash(self, file_hash: str) -> BookRecord | None:
        with self._connect() as connection:
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
        with self._connect() as connection:
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

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("TRUNCATE TABLE books RESTART IDENTITY")

    def save_extraction(self, file_hash: str, extraction_json: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE books SET extraction_json = %s::jsonb WHERE file_hash = %s",
                (extraction_json, file_hash),
            )