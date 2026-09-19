import unittest

from app.indexing import build_book_entries, extraction_from_payload
from app.book_extraction import BookExtraction, CompanyExtraction, SubjectExtraction

SUBJECT_A = {
    "title": "Untitled subject",
    "rawText": "[PAGE 3]\nSearch engine\n" + "content a\n" * 6,
    "pageStart": 3,
    "pageEnd": 4,
}
SUBJECT_B = {
    "title": "Untitled subject",
    "rawText": "[PAGE 3]\nSearch engine\n" + "content b\n" * 25,
    "pageStart": 3,
    "pageEnd": 4,
}
SUBJECT_C = {
    "title": "Génération de Tests Automatisés",
    "rawText": "[PAGE 9]\nGénération de Tests Automatisés\n" + "contenu c\n" * 8,
    "pageStart": 9,
    "pageEnd": 9,
}
PAYLOAD = {
    "company": {"name": "Numeryx", "mission": None, "vision": None, "values": [], "intro": None},
    "subjects": [SUBJECT_A, SUBJECT_B, SUBJECT_C],
}


class ExtractionFromPayloadTests(unittest.TestCase):
    def test_parses_known_fields_only(self) -> None:
        book = extraction_from_payload(PAYLOAD)

        self.assertEqual(book.company.name, "Numeryx")
        self.assertEqual(len(book.subjects), 3)

    def test_skips_subjects_missing_title_or_text(self) -> None:
        payload = {
            "company": {"name": "X"},
            "subjects": [
                SUBJECT_A,
                {"title": "", "rawText": "text"},
                {"rawText": "no title"},
                {"title": "ok", "rawText": "valid", "pageStart": 1},
            ],
        }
        book = extraction_from_payload(payload)

        self.assertEqual([subject.title for subject in book.subjects], ["Untitled subject", "ok"])


class BuildBookEntriesTests(unittest.TestCase):
    def test_recovers_titles_and_dedups_by_reference(self) -> None:
        entries = build_book_entries(PAYLOAD)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].title, "Search engine")
        self.assertIn("content b", entries[0].text)
        self.assertEqual(entries[1].title, "Génération de Tests Automatisés")
        self.assertNotIn("Untitled subject", [entry.title for entry in entries])

    def test_accepts_json_string_input(self) -> None:
        import json

        entries = build_book_entries(json.dumps(PAYLOAD))

        self.assertEqual(len(entries), 2)

    def test_replaces_digit_only_titles_with_recovered_title(self) -> None:
        payload = {
            "company": {"name": "Corp"},
            "subjects": [
                {
                    "title": "39",
                    "rawText": "[PAGE 3]\nPFE BOOK\n2026\nParticipation à la segmentation des Fournisseurs / impact environnemental.\ncontenu détaillé de la mission\n" * 3,
                    "pageStart": 3,
                    "pageEnd": 4,
                },
            ],
        }
        entries = build_book_entries(payload)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "Participation à la segmentation des Fournisseurs / impact environnemental.")
        self.assertNotIn("39", entries[0].title)
        self.assertNotEqual(entries[0].title, "PFE BOOK")