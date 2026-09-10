import unittest
from unittest.mock import patch

from app.book_extraction import (
    BookExtraction,
    OpenRouterExtractionProvider,
    chunk_text,
    parse_provider_response,
    provider_response_schema,
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

    def test_parser_accepts_top_level_subject_array(self) -> None:
        extraction = parse_provider_response(
            '[{"title":"Data platform","text":"SQL and Python"}]'
        )

        self.assertEqual(extraction.subjects[0].title, "Data platform")

    @patch("app.book_extraction.httpx.stream")
    def test_streaming_provider_collects_reasoning_and_content(self, stream) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def raise_for_status(self):
                return None

            def iter_lines(self):
                return [
                    'data: {"choices":[{"delta":{"reasoning":"thinking "}}]}',
                    'data: {"choices":[{"delta":{"content":"{\\"company\\":{"}}]}',
                    'data: [DONE]',
                ]

        stream.return_value = FakeResponse()
        provider = OpenRouterExtractionProvider("test-key")

        result = provider._stream_completion("prompt")

        self.assertEqual(result, '{"company":{')

    def test_terminal_trace_prints_and_flushes(self) -> None:
        with patch("builtins.print") as print_mock:
            terminal_trace("test", "value")

        print_mock.assert_called_once_with("[OpenRouter:test] value", flush=True)

    def test_chunk_text_keeps_all_content(self) -> None:
        text = "page one\n\npage two\n\npage three"

        chunks = chunk_text(text, max_characters=12)

        self.assertEqual("\n\n".join(chunks), text)

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