import json
from typing import Any

from .book_extraction import BookExtraction, CompanyExtraction, SubjectExtraction
from .data_quality import IndexSubject, build_index_subjects, detect_boilerplate

_COMPANY_FIELDS = ("name", "intro", "mission", "vision", "values")
_SUBJECT_FIELDS = ("title", "rawText", "pageStart", "pageEnd")


def extraction_from_payload(payload: dict) -> BookExtraction:
    company_payload = payload.get("company") or {}
    company = CompanyExtraction(
        **{key: company_payload[key] for key in _COMPANY_FIELDS if key in company_payload}
    )
    subjects: list[SubjectExtraction] = []
    for subject_payload in payload.get("subjects", []):
        fields = {
            key: subject_payload[key] for key in _SUBJECT_FIELDS if key in subject_payload
        }
        if not fields.get("title") or not fields.get("rawText"):
            continue
        subjects.append(SubjectExtraction(**fields))
    return BookExtraction(company=company, subjects=subjects)


def build_book_entries(extraction: str | dict[str, Any]) -> list[IndexSubject]:
    payload = extraction if isinstance(extraction, dict) else json.loads(extraction)
    book = extraction_from_payload(payload)
    boilerplate = detect_boilerplate([subject.rawText for subject in book.subjects])
    return build_index_subjects(book, boilerplate=boilerplate)