import hashlib
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.book_repository import BookRepository
from app.pdf_extraction import ExtractionResult


class FakeStorage:
    uploads = 0

    def put_pdf(self, object_name: str, file_object: BytesIO) -> str:
        FakeStorage.uploads += 1
        return f"s3://test/{object_name}"


class UploadBookTests(unittest.TestCase):
    def setUp(self) -> None:
        main.book_repository = BookRepository()
        FakeStorage.uploads = 0
        self.client = TestClient(app)

    @patch("app.main.ObjectStorage", FakeStorage)
    @patch("app.main.extract_pdf")
    def test_first_upload_is_stored_with_sha256(self, extract_pdf) -> None:
        content = b"pdf-content"
        extract_pdf.return_value = ExtractionResult("catalog", 1, False)

        response = self.client.post(
            "/books",
            files={"file": ("book.pdf", content, "application/pdf")},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["file_hash"], hashlib.sha256(content).hexdigest())
        self.assertFalse(response.json()["deduplicated"])
        self.assertEqual(extract_pdf.call_count, 1)
        self.assertEqual(FakeStorage.uploads, 1)

    @patch("app.main.ObjectStorage", FakeStorage)
    @patch("app.main.extract_pdf")
    def test_duplicate_upload_reuses_existing_record(self, extract_pdf) -> None:
        extract_pdf.return_value = ExtractionResult("catalog", 1, False)
        files = {"file": ("book.pdf", b"pdf-content", "application/pdf")}

        first_response = self.client.post("/books", files=files)
        duplicate_response = self.client.post("/books", files=files)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertTrue(duplicate_response.json()["deduplicated"])
        self.assertEqual(duplicate_response.json()["object_ref"], first_response.json()["object_ref"])
        self.assertEqual(extract_pdf.call_count, 1)
        self.assertEqual(FakeStorage.uploads, 1)

    @patch("app.main.ObjectStorage", FakeStorage)
    @patch("app.main.extract_pdf")
    def test_different_upload_is_processed_separately(self, extract_pdf) -> None:
        extract_pdf.return_value = ExtractionResult("catalog", 1, False)

        first_response = self.client.post(
            "/books",
            files={"file": ("book.pdf", b"first", "application/pdf")},
        )
        second_response = self.client.post(
            "/books",
            files={"file": ("book.pdf", b"second", "application/pdf")},
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        self.assertNotEqual(first_response.json()["file_hash"], second_response.json()["file_hash"])
        self.assertEqual(extract_pdf.call_count, 2)
        self.assertEqual(FakeStorage.uploads, 2)