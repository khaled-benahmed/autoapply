import time
import unittest
from unittest.mock import patch

from app.book_extraction import (
    BookExtraction,
    CompanyExtraction,
    G4FExtractionProvider,
    SubjectExtraction,
    chunk_text,
    parse_provider_response,
    provider_response_schema,
    select_candidate_pages,
    parse_local_subjects,
    terminal_trace,
)


class FakeResponse:
    text = """```json
{"company":{"name":null,"intro":null,"mission":null,"vision":null,"values":[]},"subjects":[{"title":"Search","rawText":"Python","pageStart":null,"pageEnd":null}]}
```"""


class BookExtractionTests(unittest.TestCase):
    def test_gemini_schema_removes_sdk_unsupported_keyword(self) -> None:
        schema_text = str(provider_response_schema())

        self.assertNotIn("additionalProperties", schema_text)

    def test_parser_accepts_fenced_json_and_unknown_pages(self) -> None:
        extraction = parse_provider_response(FakeResponse.text)

        self.assertIsNone(extraction.subjects[0].pageStart)

    def test_parser_rejects_empty_provider_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty message content"):
            parse_provider_response(None)

    def test_parser_accepts_provider_content_parts(self) -> None:
        extraction = parse_provider_response(
            [{"type": "text", "text": FakeResponse.text}]
        )

        self.assertEqual(extraction.subjects[0].title, "Search")

    def test_parser_extracts_json_after_reasoning_text(self) -> None:
        extraction = parse_provider_response(
            "Here is my thinking process...\n"
            + FakeResponse.text
        )

        self.assertEqual(extraction.company.values, [])

    def test_parser_wraps_single_subject_response(self) -> None:
        extraction = parse_provider_response(
            '{"reference":"AS005/26","title":"IFRS 9",'
            '"page":[32],"rawText":"Subject details"}'
        )

        self.assertEqual(extraction.subjects[0].title, "IFRS 9")
        self.assertEqual(extraction.subjects[0].pageStart, 32)
        self.assertIn("AS005/26", extraction.subjects[0].rawText)

    def test_parser_accepts_subject_aliases_and_subject_lists(self) -> None:
        extraction = parse_provider_response(
            '{"subjects":[{"title":"NLP","description":"Python project",'
            '"pages":[4,5]}]}'
        )

        self.assertEqual(extraction.subjects[0].rawText, "Python project")
        self.assertEqual(extraction.subjects[0].pageEnd, 5)

    def test_parser_accepts_internships_and_company_context(self) -> None:
        extraction = parse_provider_response(
            '{"companyContext":{"rawText":"[PAGE 1]\\nCompany: Acme\\n'
            'Mission: build tools\\nValues: quality, delivery"},'
            '"internships":[{"rawText":"[PAGE 2]\\nSujet AS001/26 - Search\\n'
            'Mission: Build the platform"}]}'
        )

        self.assertEqual(extraction.company.name, "Acme")
        self.assertEqual(extraction.company.mission, "build tools")
        self.assertEqual(extraction.company.values, ["quality", "delivery"])
        self.assertEqual(extraction.subjects[0].title, "Search")

    def test_parser_derives_title_from_id_when_header_missing(self) -> None:
        extraction = parse_provider_response(
            '{"subjects":[{"id":"AS009/26","rawText":"details"}]}'
        )

        self.assertEqual(extraction.subjects[0].title, "AS009/26")
        self.assertEqual(extraction.subjects[0].rawText, "details")

    def test_parser_accepts_string_subjects(self) -> None:
        extraction = parse_provider_response(
            '{"company":"Acme","subjects":["Search platform"]}'
        )

        self.assertEqual(extraction.subjects[0].title, "Search platform")

    def test_parser_accepts_top_level_subject_array(self) -> None:
        extraction = parse_provider_response(
            '[{"title":"Data platform","text":"SQL and Python"}]'
        )

        self.assertEqual(extraction.subjects[0].title, "Data platform")

    def test_parser_accepts_company_context_without_subjects(self) -> None:
        extraction = parse_provider_response(
            '{"company_context":"[PAGE 1]\\nCompany: Acme Corp\\n'
            'Mission: build tools"}'
        )

        self.assertEqual(extraction.company.name, "Acme Corp")
        self.assertEqual(extraction.company.mission, "build tools")
        self.assertEqual(extraction.subjects, [])

    def test_parser_accepts_bare_company_object(self) -> None:
        extraction = parse_provider_response(
            '{"name":"MEDIANET","email":"info@medianet.com.tn",'
            '"rawText":"[PAGE 58]\\nNous contacter"}'
        )

        self.assertEqual(extraction.company.name, "MEDIANET")
        self.assertEqual(extraction.subjects, [])

    def test_company_context_prefers_explicit_fields(self) -> None:
        extraction = parse_provider_response(
            '{"companyContext":{"name":"MEDIANET",'
            '"rawText":"[PAGE 1]\\nCompany: Legacy Name\\nMission: m"},'
            '"internships":[]}'
        )

        self.assertEqual(extraction.company.name, "MEDIANET")
        self.assertEqual(extraction.company.mission, "m")

    def test_normalize_derives_page_range_from_raw_text(self) -> None:
        extraction = parse_provider_response(
            '{"subjects":[{"rawText":"[PAGE 7]\\nSujet AS001/26 - Search"}]}'
        )

        self.assertEqual(extraction.subjects[0].pageStart, 7)
        self.assertEqual(extraction.subjects[0].pageEnd, 7)

    def test_normalize_derives_title_from_pwc_style_block(self) -> None:
        extraction = parse_provider_response(
            '{"subjects":[{"rawText":"Reference: TLS001/26\\n[PAGE 17]\\n'
            "PwC\\nPwC\\nLes opérations sur le capital social\\n"
            'Objectif du stage :"}]}'
        )

        self.assertEqual(extraction.subjects[0].title, "Les opérations sur le capital social")

    def test_terminal_trace_prints_and_flushes(self) -> None:
        with patch("builtins.print") as print_mock:
            terminal_trace("test", "value")

        print_mock.assert_called_once_with("[Extract:test] value", flush=True)

    def test_chunk_text_keeps_all_content(self) -> None:
        text = "page one\n\npage two\n\npage three"

        chunks = chunk_text(text, max_characters=12)

        self.assertEqual("\n\n".join(chunks), text)

    def test_prompt_bounds_large_source_text(self) -> None:
        prompt = G4FExtractionProvider._prompt("x" * 20, 1, 10)

        self.assertIn("x" * 10, prompt)
        self.assertIn("Source text truncated", prompt)

    def test_select_candidate_pages_prefers_subject_markers(self) -> None:
        text = (
            "[PAGE 1]\nCompany cover\n\n"
            "[PAGE 2]\nAdjacent company context\n\n"
            "[PAGE 3]\nSujet AS005/26\nBuild a search platform with Python\n\n"
            "[PAGE 4]\nSubject continuation\n\n"
            "[PAGE 5]\nDistant legal appendix"
        )

        candidates = select_candidate_pages(text, max_characters=500)

        self.assertIn("Sujet AS005/26", candidates)
        self.assertIn("Adjacent company context", candidates)
        self.assertNotIn("Distant legal appendix", candidates)

    def test_local_parser_extracts_subject_blocks_and_fields(self) -> None:
        text = (
            "[PAGE 1]\nCompany: Example\n\n"
            "[PAGE 2]\nSujet AS001/26 - Search platform\n"
            "Mission: Build the platform\n"
            "Objectif: Improve search\n"
            "Technologies: Python, PostgreSQL\n"
            "Skills: NLP\n"
            "\n[PAGE 3]\nSujet AS002/26 - Mobile app\n"
            "Mission: Build the app\n"
            "Objectif: Serve users\n"
            "Technologies: Flutter\n"
            "Skills: Dart\n"
        )

        candidates = parse_local_subjects(text)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].title, "Search platform")
        self.assertIn("Python, PostgreSQL", candidates[0].fields["technologies"])
        self.assertEqual(candidates[0].page_start, 2)
        self.assertEqual(candidates[1].page_end, 3)
        self.assertGreaterEqual(candidates[0].confidence, 0.66)

    def test_local_parser_ignores_front_matter_headings(self) -> None:
        text = (
            "[PAGE 1]\nPFE BOOK\n2026\n\n"
            "[PAGE 2]\nSOMMAIRE\n\n"
            "[PAGE 3]\nQUI SOMMES -NOUS ?\nCompany information\n\n"
            "[PAGE 8]\nSUJET 1\nMission: Build a dashboard\n"
        )

        candidates = parse_local_subjects(text)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "1")

    def test_hybrid_schema_keeps_subject_context(self) -> None:
        extraction = BookExtraction.model_validate(
            {
                "company": {
                    "name": "Example",
                    "intro": "Software company",
                    "mission": "Build useful tools",
                    "vision": "A better future",
                    "values": ["quality"],
                },
                "subjects": [
                    {
                        "title": "Document search",
                        "rawText": "Python, NLP, Tunis, contact@example.com",
                        "pageStart": 4,
                        "pageEnd": 5,
                    }
                ],
            }
        )

        self.assertEqual(
            extraction.subjects[0].rawText,
            "Python, NLP, Tunis, contact@example.com",
        )


class G4FCascadeTests(unittest.TestCase):
    def test_cascade_uses_primary_provider_first(self) -> None:
        provider = G4FExtractionProvider(
            providers=(("TierOne", "m1"), ("TierTwo", "m2")),
            retries_per_provider=1,
        )
        calls: list[tuple[str, str]] = []

        def fake_completion(prompt: str, provider_name: str, model_name: str) -> str:
            calls.append((provider_name, model_name))
            return '{"subjects":[{"title":"S","rawText":"t","pageStart":1,"pageEnd":1}]}'

        with patch.object(G4FExtractionProvider, "_completion", side_effect=fake_completion):
            result = provider._extract_chunk("chunk", 1)

        self.assertEqual(calls, [("TierOne", "m1")])
        self.assertEqual(result.subjects[0].title, "S")

    def test_extract_merges_chunk_extractions(self) -> None:
        provider = G4FExtractionProvider(chunk_characters=10)

        with patch.object(
            G4FExtractionProvider,
            "_extract_chunk",
            side_effect=[
                BookExtraction(
                    company=CompanyExtraction(name="Example"),
                    subjects=[SubjectExtraction(title="One", rawText="a")],
                ),
                BookExtraction(
                    company=CompanyExtraction(),
                    subjects=[SubjectExtraction(title="Two", rawText="b")],
                ),
            ],
        ):
            result = provider.extract("page one\n\npage two", 2)

        self.assertEqual(result.company.name, "Example")
        self.assertEqual([subject.title for subject in result.subjects], ["One", "Two"])

    def test_cascade_falls_through_after_provider_failure(self) -> None:
        provider = G4FExtractionProvider(
            providers=(("TierOne", "m1"), ("TierTwo", "m2")),
            retries_per_provider=1,
        )

        def fake_completion(prompt: str, provider_name: str, model_name: str) -> str:
            if provider_name == "TierOne":
                raise ValueError("boom")
            return '{"subjects":[{"title":"OK","rawText":"t","pageStart":1,"pageEnd":1}]}'

        with patch.object(G4FExtractionProvider, "_completion", side_effect=fake_completion):
            result = provider._extract_chunk("chunk", 1)

        self.assertEqual(result.subjects[0].title, "OK")

    def test_cascade_reports_all_failures(self) -> None:
        provider = G4FExtractionProvider(
            providers=(("TierOne", "m1"), ("TierTwo", "m2")),
            retries_per_provider=1,
        )

        def fake_completion(prompt: str, provider_name: str, model_name: str) -> str:
            raise ValueError("down")

        with patch.object(G4FExtractionProvider, "_completion", side_effect=fake_completion):
            with self.assertRaisesRegex(RuntimeError, r"TierOne/m1 .*TierTwo/m2"):
                provider._extract_chunk("chunk", 1)

    def test_completion_times_out_hanging_provider(self) -> None:
        provider = G4FExtractionProvider(attempt_timeout=0.1)

        def hang(*args: object) -> str:
            time.sleep(5)
            return "never reached"

        with patch.object(G4FExtractionProvider, "_request_completion", side_effect=hang):
            with self.assertRaisesRegex(TimeoutError, "TierOne/m1 timed out"):
                provider._completion("prompt", "TierOne", "m1")