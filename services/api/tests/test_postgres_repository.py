import os
import unittest

from app.book_repository import BookRecord, PostgresBookRepository
from app.data_quality import IndexSubject

POSTGRES_URL = os.getenv("TEST_DATABASE_URL", "").replace(
    "@postgres:", "@localhost:"
)


@unittest.skipUnless(POSTGRES_URL, "TEST_DATABASE_URL not set; skipping Postgres integration tests")
class PostgresScopingTests(unittest.TestCase):
    BOOK_A = "f" * 64
    BOOK_B = "h" * 64
    DIM = 384

    def setUp(self) -> None:
        self.repo = PostgresBookRepository(database_url=POSTGRES_URL)
        for file_hash, filename in (
            (self.BOOK_A, "book-a.pdf"),
            (self.BOOK_B, "book-b.pdf"),
        ):
            self.repo.save(
                BookRecord(
                    file_hash=file_hash,
                    object_ref=f"s3://test/{filename}",
                    filename=filename,
                    page_count=5,
                    extracted_text="text",
                    used_ocr=False,
                )
            )
        self.repo.replace_index_subjects(
            self.BOOK_A,
            [
                IndexSubject(reference="A1/26", title="Audit Fiscal", text="audit informatique analyse de données", raw_text="", page_start=1, page_end=1),
                IndexSubject(reference="A2/26", title="Autre Sujet", text="tennis photographie", raw_text="", page_start=1, page_end=1),
            ],
        )
        self.repo.replace_index_subjects(
            self.BOOK_B,
            [
                IndexSubject(reference="B1/26", title="Data Platform", text="audit analyse de données Python", raw_text="", page_start=1, page_end=1),
                IndexSubject(reference="B2/26", title="Réseaux Sociaux", text="communication marketing", raw_text="", page_start=1, page_end=1),
            ],
        )

    def tearDown(self) -> None:
        with self.repo._pool.connection(timeout=10) as connection:
            connection.execute(
                "DELETE FROM books WHERE file_hash IN (%s, %s)",
                (self.BOOK_A, self.BOOK_B),
            )
        self.repo._pool.close()

    def test_keyword_search_scopes_to_book(self) -> None:
        rows = self.repo.search_keywords("audit", limit=10, book_hash=self.BOOK_A)

        self.assertTrue(rows)
        self.assertTrue(all(row["book_hash"] == self.BOOK_A for row in rows))
        refs = {row["reference"] for row in rows}
        self.assertIn("A1/26", refs)
        self.assertNotIn("B1/26", refs)

    def test_unscoped_keyword_search_covers_all_books(self) -> None:
        rows = self.repo.search_keywords("audit", limit=10)

        hashes = {row["book_hash"] for row in rows}
        self.assertIn(self.BOOK_A, hashes)
        self.assertIn(self.BOOK_B, hashes)

    def test_hybrid_search_scopes_to_book(self) -> None:
        rows = self.repo.search_hybrid(
            "audit", limit=10, query_embedding=[0.0] * self.DIM, book_hash=self.BOOK_A
        )

        self.assertTrue(rows)
        self.assertTrue(all(row["book_hash"] == self.BOOK_A for row in rows))

    def test_dense_search_scopes_to_book(self) -> None:
        vector = [1.0] + [0.0] * (self.DIM - 1)
        self.repo.replace_index_subjects(
            self.BOOK_A,
            [
                IndexSubject(reference="A1/26", title="Audit Fiscal", text="audit information", raw_text="", page_start=1, page_end=1, embedding=vector),
            ],
        )

        rows = self.repo.search_dense(vector, limit=10, book_hash=self.BOOK_A)
        self.assertTrue(rows)
        self.assertTrue(all(row["book_hash"] == self.BOOK_A for row in rows))


if __name__ == "__main__":
    unittest.main()