import hashlib
import json
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.book_repository import BookRecord, BookRepository
from app.data_quality import IndexSubject
from app.embeddings import NullEmbedder
from app.indexing import build_book_entries
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


class UploadSizeLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        main.book_repository = BookRepository()
        FakeStorage.uploads = 0
        self.client = TestClient(app)

    @patch("app.main.ObjectStorage", FakeStorage)
    @patch("app.main.extract_pdf")
    def test_book_upload_rejects_oversized_content_length(self, extract_pdf) -> None:
        extract_pdf.return_value = ExtractionResult("catalog", 1, False)

        response = self.client.post(
            "/books",
            files={"file": ("book.pdf", b"pdf-content", "application/pdf")},
            headers={"Content-Length": str(main.settings.max_upload_bytes + 1)},
        )

        self.assertEqual(response.status_code, 413)
        self.assertNotIn(b"pdf-content", extract_pdf.call_args_list)

    def test_cv_upload_rejects_oversized_content_length(self) -> None:
        response = self.client.post(
            "/cv",
            files={"file": ("cv.txt", b"x" * 10, "text/plain")},
            headers={"Content-Length": str(main.settings.max_upload_bytes + 1)},
        )

        self.assertEqual(response.status_code, 413)


_EXTRACTION_PAYLOAD = {
    "company": {"name": "Numeryx", "mission": None, "vision": None, "values": [], "intro": None},
    "subjects": [
        {
            "title": "Untitled subject",
            "rawText": "[PAGE 3]\nSearch engine\n" + "content a\n" * 5,
            "pageStart": 3,
            "pageEnd": 4,
        },
        {
            "title": "Untitled subject",
            "rawText": "[PAGE 3]\nSearch engine\n" + "content b\n" * 20,
            "pageStart": 3,
            "pageEnd": 4,
        },
        {
            "title": "Génération de Tests Automatisés",
            "rawText": "[PAGE 9]\nGénération de Tests Automatisés\n" + "contenu c\n" * 8,
            "pageStart": 9,
            "pageEnd": 9,
        },
    ],
}


class IndexBookTests(unittest.TestCase):
    BOOK_HASH = "a" * 64

    def setUp(self) -> None:
        main.book_repository = BookRepository()
        self.client = TestClient(app)

    def _save_book(self, with_extraction: bool) -> None:
        main.book_repository.save(
            BookRecord(
                file_hash=self.BOOK_HASH,
                object_ref="s3://test/book.pdf",
                filename="book.pdf",
                page_count=10,
                extracted_text="text",
                used_ocr=False,
                extraction_json=json.dumps(_EXTRACTION_PAYLOAD) if with_extraction else None,
            )
        )

    def test_index_route_seeds_and_lists(self) -> None:
        self._save_book(with_extraction=True)

        indexed = self.client.post(f"/books/{self.BOOK_HASH}/index")
        rows = self.client.get(f"/books/{self.BOOK_HASH}/index")

        self.assertEqual(indexed.status_code, 200)
        self.assertEqual(indexed.json()["indexed"], 2)
        self.assertEqual(rows.status_code, 200)
        titles = [row["title"] for row in rows.json()]
        self.assertIn("Search engine", titles)
        self.assertIn("Génération de Tests Automatisés", titles)

    def test_index_route_is_idempotent(self) -> None:
        self._save_book(with_extraction=True)

        self.client.post(f"/books/{self.BOOK_HASH}/index")
        self.client.post(f"/books/{self.BOOK_HASH}/index")
        rows = self.client.get(f"/books/{self.BOOK_HASH}/index").json()

        self.assertEqual(len(rows), 2)

    def test_index_requires_prior_extraction(self) -> None:
        self._save_book(with_extraction=False)

        indexed = self.client.post(f"/books/{self.BOOK_HASH}/index")

        self.assertEqual(indexed.status_code, 409)

    def test_index_unknown_book_is_404(self) -> None:
        response = self.client.post(f"/books/{'b' * 64}/index")

        self.assertEqual(response.status_code, 404)

    def test_index_all_seeds_every_book_with_extraction(self) -> None:
        self._save_book(with_extraction=True)
        second_hash = "c" * 64
        main.book_repository.save(
            BookRecord(
                file_hash=second_hash,
                object_ref="s3://test/book2.pdf",
                filename="book2.pdf",
                page_count=5,
                extracted_text="text",
                used_ocr=False,
                extraction_json=json.dumps(_EXTRACTION_PAYLOAD),
            )
        )
        main.book_repository.save(
            BookRecord(
                file_hash="d" * 64,
                object_ref="s3://test/book3.pdf",
                filename="book3.pdf",
                page_count=5,
                extracted_text="text",
                used_ocr=False,
                extraction_json=None,
            )
        )

        results = self.client.post("/books/index-all").json()
        indexed_by_hash = {result["book_hash"]: result["indexed"] for result in results}

        self.assertEqual(len(results), 2)
        self.assertEqual(indexed_by_hash[self.BOOK_HASH], 2)
        self.assertEqual(indexed_by_hash[second_hash], 2)


class KeywordSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        main.book_repository = BookRepository()
        self.client = TestClient(app)
        book_hash = "e" * 64
        main.book_repository.save(
            BookRecord(
                file_hash=book_hash,
                object_ref="s3://test/book.pdf",
                filename="book.pdf",
                page_count=10,
                extracted_text="text",
                used_ocr=False,
                extraction_json=json.dumps(_EXTRACTION_PAYLOAD),
            )
        )
        main.book_repository.replace_index_subjects(
            book_hash,
            build_book_entries(json.dumps(_EXTRACTION_PAYLOAD)),
        )

    def test_search_ranks_by_term_matches(self) -> None:
        response = self.client.get("/search", params={"q": "content"})

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Search engine")

    def test_search_matches_french_content(self) -> None:
        response = self.client.get("/search", params={"q": "contenu"})

        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Génération de Tests Automatisés")

    def test_title_hits_outrank_text_only_hits(self) -> None:
        main.book_repository.replace_index_subjects(
            "e" * 64,
            [
                IndexSubject(reference="A", title="Search engine", text="cryptographie avancée", raw_text="", page_start=1, page_end=1),
                IndexSubject(reference="B", title="Other", text="search engine biographique", raw_text="", page_start=1, page_end=1),
            ],
        )

        response = self.client.get("/search", params={"q": "search engine"})

        results = response.json()["results"]
        self.assertEqual(results[0]["reference"], "A")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_search_returns_empty_when_no_match(self) -> None:
        response = self.client.get("/search", params={"q": "inexistant"})

        self.assertEqual(response.json()["results"], [])

    def test_search_is_accent_insensitive(self) -> None:
        main.book_repository.replace_index_subjects(
            "e" * 64,
            [
                IndexSubject(reference="TLS001/26", title="Impôt sur les sociétés", text="Analyse des règles fiscales en détail", raw_text="", page_start=1, page_end=1),
            ],
        )

        response = self.client.get("/search", params={"q": "impot sur les societes"})

        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["reference"], "TLS001/26")

    def test_search_requires_query(self) -> None:
        response = self.client.get("/search")

        self.assertEqual(response.status_code, 422)


class FixedQueryEmbedder:
    name = "stub"
    dim = 4

    def __init__(self, query_vector: list[float]) -> None:
        self._query_vector = query_vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._query_vector for _ in texts]


class HybridSearchTests(unittest.TestCase):
    BOOK_HASH = "f" * 64
    QV = [1.0, 0.0, 0.0, 0.0]
    SUBJECTS = [
        IndexSubject(reference="A1/26", title="Audit Fiscal", text="contenu fiscal", raw_text="", page_start=1, page_end=1, embedding=[1.0, 0.0, 0.0, 0.0]),
        IndexSubject(reference="B1/26", title="Audit Fiscal", text="contenu fiscal", raw_text="", page_start=2, page_end=2, embedding=[0.0, 0.0, 1.0, 0.0]),
        IndexSubject(reference="C1/26", title="Sans lien textuel", text="zzz gibberish unrelated", raw_text="", page_start=3, page_end=3, embedding=[0.9, 0.05, 0.05, 0.0]),
    ]

    def setUp(self) -> None:
        main.book_repository = BookRepository()
        main.embedder = FixedQueryEmbedder(self.QV)
        self.client = TestClient(app)
        main.book_repository.replace_index_subjects(self.BOOK_HASH, self.SUBJECTS)

    def test_dense_breaks_keyword_tie(self) -> None:
        keyword = self.client.get("/search", params={"q": "audit fiscal"}).json()["results"]
        hybrid = self.client.get("/search", params={"q": "audit fiscal", "dense": "true"}).json()["results"]

        self.assertEqual(keyword[0]["reference"], "A1/26")
        self.assertEqual(keyword[1]["reference"], "B1/26")
        self.assertEqual(hybrid[0]["reference"], "A1/26")
        self.assertGreater(hybrid[0]["score"], hybrid[1]["score"])

    def test_dense_only_recall_surfaces_without_keywords(self) -> None:
        keyword = self.client.get("/search", params={"q": "qqzzqq"})
        hybrid = self.client.get("/search", params={"q": "qqzzqq", "dense": "true"}).json()["results"]

        self.assertEqual(keyword.json()["results"], [])
        refs = [r["reference"] for r in hybrid]
        self.assertIn("C1/26", refs)
        sources = {r["source"] for r in hybrid}
        self.assertIn("dense", sources)

    def test_null_embedder_dense_falls_back_to_keyword(self) -> None:
        main.embedder = NullEmbedder()
        response = self.client.get("/search", params={"q": "audit fiscal", "dense": "true"})

        self.assertEqual(response.status_code, 200)
        refs = [r["reference"] for r in response.json()["results"]]
        self.assertEqual(refs, ["A1/26", "B1/26"])
        sources = {r["source"] for r in response.json()["results"]}
        self.assertEqual(sources, {"keyword"})

    def test_rrf_merges_keyword_and_dense_rankings(self) -> None:
        keyword = self.client.get("/search", params={"q": "audit fiscal"})
        keyword_refs = [r["reference"] for r in keyword.json()["results"]]
        self.assertEqual(keyword_refs, ["A1/26", "B1/26"])
        self.assertTrue(all(r["source"] == "keyword" for r in keyword.json()["results"]))

        hybrid = self.client.get("/search", params={"q": "audit fiscal", "dense": "true"}).json()["results"]
        refs = [r["reference"] for r in hybrid]

        self.assertEqual(refs[0], "A1/26")
        self.assertGreater(hybrid[0]["score"], hybrid[1]["score"])
        self.assertLess(hybrid[0]["score"], 2.0)
        self.assertEqual(hybrid[0]["source"], "both")
        self.assertEqual(hybrid[1]["source"], "keyword")

    def test_hybrid_surfaces_dense_matches_when_keyword_empty(self) -> None:
        hybrid = self.client.get("/search", params={"q": "qqzzqq", "dense": "true"}).json()["results"]
        refs = [r["reference"] for r in hybrid]

        self.assertEqual(refs[0], "A1/26")
        self.assertIn("C1/26", refs)
        self.assertNotIn("B1/26", refs)


CV_TEXT = """INGÉNIEUR DATA
COMPÉTENCES
- audit informatique
- analyse de données
- Python
FORMATION
2020-2023 Master Data Science
PROJETS
- Projet: tableau de bord BI pour analyse de données
"""


class CvRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        main.book_repository = BookRepository()
        main.embedder = NullEmbedder()
        self.client = TestClient(app)
        main.book_repository.replace_index_subjects(
            "f" * 64,
            [
                IndexSubject(reference="F1/26", title="Audit Fiscal", text="audit informatique analyse de données", raw_text="", page_start=1, page_end=1),
                IndexSubject(reference="F2/26", title="Autre Sujet", text="tennis photographie", raw_text="", page_start=1, page_end=1),
            ],
        )
        upload = self.client.post(
            "/cv",
            files={"file": ("cv.txt", CV_TEXT.encode("utf-8"), "text/plain")},
        )
        self.assertEqual(upload.status_code, 201)
        self.cv_hash = upload.json()["cv_hash"]

    def test_upload_parses_profile(self) -> None:
        cv = self.client.get(f"/cv/{self.cv_hash}").json()

        self.assertIn("audit informatique", cv["profile"]["skills"])
        self.assertIn("tableau de bord BI", cv["profile"]["projects"][0])
        self.assertEqual(cv["profile"]["education"], ["2020-2023 Master Data Science"])

    def test_match_keyword_returns_relevant_subjects(self) -> None:
        match = self.client.post(
            f"/cv/{self.cv_hash}/match", params={"dense": "false"}
        ).json()

        self.assertEqual(match["profile_query"].split()[0], "audit")
        titles = [r["title"] for r in match["results"]]
        self.assertEqual(titles[0], "Audit Fiscal")

    def test_match_unknown_cv_is_404(self) -> None:
        response = self.client.post(f"/cv/{'g' * 64}/match")

        self.assertEqual(response.status_code, 404)

    def test_update_profile_changes_next_match(self) -> None:
        update = {
            "skills": ["tennis", "photographie"],
            "education": [],
            "experience": [],
            "projects": [],
        }
        response = self.client.post(f"/cv/{self.cv_hash}/profile", json=update)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"]["skills"], ["tennis", "photographie"])
        cv = self.client.get(f"/cv/{self.cv_hash}").json()
        self.assertEqual(cv["profile"]["skills"], ["tennis", "photographie"])
        match = self.client.post(
            f"/cv/{self.cv_hash}/match", params={"dense": "false"}
        ).json()
        titles = [r["title"] for r in match["results"]]
        self.assertEqual(titles[0], "Autre Sujet")

    def test_update_unknown_cv_is_404(self) -> None:
        response = self.client.post(
            f"/cv/{'g' * 64}/profile",
            json={"skills": ["x"]},
        )

        self.assertEqual(response.status_code, 404)

    def test_books_list_reports_subjects_and_extraction(self) -> None:
        main.book_repository.save(
            BookRecord(
                file_hash="f" * 64,
                object_ref="s3://test/book.pdf",
                filename="book.pdf",
                page_count=2,
                extracted_text="audit",
                used_ocr=False,
            )
        )

        books = self.client.get("/books").json()

        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["file_hash"], "f" * 64)
        self.assertEqual(books[0]["subjects"], 2)
        self.assertFalse(books[0]["has_extraction"])

    def test_index_surfaces_books_in_library_list(self) -> None:
        main.book_repository.save(
            BookRecord(
                file_hash="f" * 64,
                object_ref="s3://test/book.pdf",
                filename="book.pdf",
                page_count=2,
                extracted_text="audit",
                used_ocr=False,
                extraction_json=json.dumps(_EXTRACTION_PAYLOAD),
            )
        )
        self.client.post(f"/books/{'f' * 64}/index")

        books = self.client.get("/books").json()
        self.assertEqual(books[0]["subjects"], 2)
        self.assertTrue(books[0]["has_extraction"])


class MatchBookScopingTests(unittest.TestCase):
    BOOK_A = "f" * 64
    BOOK_B = "h" * 64

    def setUp(self) -> None:
        main.book_repository = BookRepository()
        main.embedder = NullEmbedder()
        self.client = TestClient(app)
        for file_hash, filename in ((self.BOOK_A, "book-a.pdf"), (self.BOOK_B, "book-b.pdf")):
            main.book_repository.save(
                BookRecord(
                    file_hash=file_hash,
                    object_ref=f"s3://test/{filename}",
                    filename=filename,
                    page_count=10,
                    extracted_text="text",
                    used_ocr=False,
                )
            )
        main.book_repository.replace_index_subjects(
            self.BOOK_A,
            [
                IndexSubject(reference="F1/26", title="Audit Fiscal", text="audit informatique analyse de données", raw_text="", page_start=1, page_end=1),
                IndexSubject(reference="F2/26", title="Autre Sujet", text="tennis photographie", raw_text="", page_start=1, page_end=1),
            ],
        )
        main.book_repository.replace_index_subjects(
            self.BOOK_B,
            [
                IndexSubject(reference="H1/26", title="Data Platform", text="audit analyse de données Python", raw_text="", page_start=1, page_end=1),
                IndexSubject(reference="H2/26", title="Réseaux Sociaux", text="communication marketing", raw_text="", page_start=1, page_end=1),
            ],
        )
        upload = self.client.post(
            "/cv",
            files={
                "file": (
                    "cv.txt",
                    "COMPÉTENCES\n- audit informatique\n- analyse de données\n".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        self.assertEqual(upload.status_code, 201)
        self.cv_hash = upload.json()["cv_hash"]

    def _match(self, book_hash: str | None):
        params: dict[str, str] = {}
        if book_hash:
            params["book_hash"] = book_hash
        return self.client.post(f"/cv/{self.cv_hash}/match", params=params)

    def test_unscoped_match_covers_all_books(self) -> None:
        match = self._match(None).json()

        hashes = {row["book_hash"] for row in match["results"]}
        self.assertIn(self.BOOK_A, hashes)
        self.assertIn(self.BOOK_B, hashes)

    def test_match_with_book_scopes_results_to_that_book(self) -> None:
        match = self._match(self.BOOK_A).json()

        hashes = {row["book_hash"] for row in match["results"]}
        self.assertEqual(hashes, {self.BOOK_A})
        self.assertEqual(match["results"][0]["title"], "Audit Fiscal")

    def test_match_scopes_to_second_book(self) -> None:
        match = self._match(self.BOOK_B).json()

        hashes = {row["book_hash"] for row in match["results"]}
        self.assertEqual(hashes, {self.BOOK_B})
        self.assertEqual(match["results"][0]["title"], "Data Platform")

    def test_match_unknown_book_is_404(self) -> None:
        response = self.client.post(
            f"/cv/{self.cv_hash}/match", params={"book_hash": "z" * 64}
        )

        self.assertEqual(response.status_code, 404)