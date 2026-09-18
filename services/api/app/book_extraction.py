import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


def terminal_trace(label: str, value: Any) -> None:
    print(f"[NVIDIA:{label}] {value}", flush=True)


def extraction_system_prompt() -> str:
    return (
        "ROLE: You are a document extraction service for PFE internship catalogs.\n"
        "TASK: Convert the supplied catalog text into the exact JSON object described below.\n"
        "CONSTRAINTS:\n"
        "- Return only one valid JSON object.\n"
        "- Do not return markdown, code fences, explanations, reasoning, or commentary.\n"
        "- Use exactly these top-level keys: company and subjects.\n"
        "- Use exactly these company keys: name, intro, mission, vision, values.\n"
        "- Use exactly these subject keys: title, rawText, pageStart, pageEnd.\n"
        "- Do not rename, add, or remove keys.\n"
        "- Use null for unknown pageStart or pageEnd. Use [] for unknown values.\n"
        "- Preserve the complete subject text in rawText, including skills, location, and contacts.\n"
        "- Do not invent information.\n"
        "OUTPUT FORMAT:\n"
        '{"company":{"name":null,"intro":null,"mission":null,"vision":null,"values":[]},'
        '"subjects":[{"title":"...","rawText":"...","pageStart":null,"pageEnd":null}]}\n'
        "Return the JSON object now."
    )


class CompanyExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    intro: str | None = None
    mission: str | None = None
    vision: str | None = None
    values: list[str] = Field(default_factory=list)


class SubjectExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    rawText: str
    pageStart: int | None = Field(default=None, ge=1)
    pageEnd: int | None = Field(default=None, ge=1)


class BookExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: CompanyExtraction
    subjects: list[SubjectExtraction]


class ExtractionProvider(Protocol):
    def extract(self, text: str, page_count: int) -> BookExtraction:
        """Extract company context and subject boundaries from a book."""


def parse_provider_response(response_text: Any) -> BookExtraction:
    if isinstance(response_text, list):
        response_text = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in response_text
        )
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("NVIDIA returned an empty message content")
    response_text = response_text.strip()
    decoder = json.JSONDecoder()
    validation_error: ValidationError | None = None
    for position, character in enumerate(response_text):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(response_text[position:])
            return normalize_provider_payload(candidate)
        except (json.JSONDecodeError, ValidationError) as error:
            if isinstance(error, ValidationError):
                validation_error = error
    if validation_error:
        raise validation_error
    raise ValueError("NVIDIA response did not contain a JSON object")


def normalize_provider_payload(payload: Any) -> BookExtraction:
    if isinstance(payload, list):
        return BookExtraction(
            company=CompanyExtraction(),
            subjects=[_normalize_subject(item) for item in payload],
        )
    if not isinstance(payload, dict):
        raise ValueError("NVIDIA returned a non-object extraction")

    if "company" in payload and "subjects" in payload:
        return BookExtraction.model_validate(payload)

    if "internships" in payload and isinstance(payload["internships"], list):
        return BookExtraction(
            company=CompanyExtraction(intro=str(payload.get("companyContext", ""))),
            subjects=[_normalize_subject(item) for item in payload["internships"]],
        )

    if "subjects" in payload and isinstance(payload["subjects"], list):
        return BookExtraction(
            company=CompanyExtraction.model_validate(payload.get("company", {})),
            subjects=[_normalize_subject(item) for item in payload["subjects"]],
        )

    if _looks_like_subject(payload):
        return BookExtraction(
            company=CompanyExtraction(),
            subjects=[_normalize_subject(payload)],
        )

    raise ValueError("NVIDIA returned neither a book extraction nor a subject object")


def _looks_like_subject(payload: dict[str, Any]) -> bool:
    return "title" in payload and any(
        key in payload for key in ("rawText", "raw_text", "description", "text", "content")
    )


def _normalize_subject(payload: Any) -> SubjectExtraction:
    if not isinstance(payload, dict):
        raise ValueError("NVIDIA returned a non-object subject")
    raw_text = next(
        (
            payload.get(key)
            for key in ("rawText", "raw_text", "description", "text", "content")
            if payload.get(key)
        ),
        "",
    )
    page_start, page_end = _page_range(
        payload.get("page", payload.get("pages", payload.get("pageRange")))
    )
    reference = payload.get("reference")
    if reference:
        raw_text = f"Reference: {reference}\n{raw_text}"
    return SubjectExtraction(
        title=str(payload.get("title", "Untitled subject")),
        rawText=str(raw_text),
        pageStart=page_start,
        pageEnd=page_end,
    )


def _page_range(page: Any) -> tuple[int | None, int | None]:
    if isinstance(page, int) and page >= 1:
        return page, page
    if isinstance(page, list):
        pages = [value for value in page if isinstance(value, int) and value >= 1]
        if pages:
            return min(pages), max(pages)
    return None, None


def provider_response_schema() -> dict[str, Any]:
    schema = BookExtraction.model_json_schema()

    def remove_unsupported_keywords(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: remove_unsupported_keywords(item)
                for key, item in value.items()
                if key != "additionalProperties"
            }
        if isinstance(value, list):
            return [remove_unsupported_keywords(item) for item in value]
        return value

    return remove_unsupported_keywords(schema)


def chunk_text(text: str, max_characters: int = 24000) -> list[str]:
    pages = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for page in pages:
        if current and current_size + len(page) + 2 > max_characters:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(page)
        current_size += len(page) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


@dataclass(frozen=True)
class NVIDIAExtractionProvider:
    api_key: str
    model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    base_url: str = "https://integrate.api.nvidia.com/v1"
    timeout_seconds: float = 180
    max_tokens: int = 8000
    max_retries: int = 0

    def _completion(self, prompt: str) -> str:
        terminal_trace("request", f"model={self.model} streaming=false")
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": extraction_system_prompt(),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": self.max_tokens,
                "reasoning": {"enabled": False},
                "response_format": {"type": "json_object"},
                "stream": False,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choice = payload.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                f"NVIDIA returned no final content (finish_reason={choice.get('finish_reason', 'unknown')})"
            )
        terminal_trace("raw_response", content)
        return content

    def extract(self, text: str, page_count: int) -> BookExtraction:
        prompt = self._prompt(text, page_count)
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                extraction = parse_provider_response(self._completion(prompt))
                terminal_trace(
                    "normalized",
                    f"subjects={len(extraction.subjects)} company={extraction.company.name or 'unknown'}",
                )
                return extraction
            except (httpx.HTTPError, KeyError, IndexError, ValidationError,
                    json.JSONDecodeError, TypeError, ValueError) as error:
                last_error = error
                terminal_trace("parse_error", str(error))
                prompt += "\nReturn only the final JSON object. Do not include reasoning or markdown."
        raise ValueError(f"NVIDIA returned invalid structured extraction: {last_error}") from last_error

    @staticmethod
    def _prompt(text: str, page_count: int) -> str:
        instructions = [
            "Extract a PFE catalog into the requested JSON schema.",
            "Return exactly one JSON object with keys company and subjects.",
            "company must contain name, intro, mission, vision, and values.",
            "Each subjects item must contain title, rawText, pageStart, and pageEnd.",
            "The title must be the internship subject title, not a generic label or subject number.",
            "Do not invent information. Use empty strings or empty arrays when absent.",
            "Return company context and each internship subject as a complete raw text block.",
            "Use [PAGE N] markers for 1-based page ranges; use null when unavailable.",
            "Preserve skills, location, and contact details inside rawText.",
            f"The source has approximately {page_count} pages.",
            "SOURCE TEXT:",
            text,
        ]
        return "\n".join(instructions)


@dataclass(frozen=True)
class G4FExtractionProvider:
    model: str = "default"
    provider: str = "LLM7"
    max_tokens: int = 8000
    chunk_characters: int = 8000

    def _completion(self, prompt: str) -> str:
        from g4f.client import Client
        from g4f import Provider

        selected_provider = getattr(Provider, self.provider)
        terminal_trace(
            "request",
            f"provider=g4f backend={self.provider} model={self.model}",
        )
        response = Client().chat.completions.create(
            model=self.model,
            provider=selected_provider,
            messages=[
                {"role": "system", "content": extraction_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=self.max_tokens,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("g4f returned no final content")
        terminal_trace("raw_response", content)
        return content

    def extract(self, text: str, page_count: int) -> BookExtraction:
        chunks = chunk_text(text, max_characters=self.chunk_characters)
        extractions = [
            _extract_with_provider(self._completion, chunk, page_count, "g4f")
            for chunk in chunks
        ]
        company = next(
            (
                extraction.company
                for extraction in extractions
                if extraction.company.name
                or extraction.company.intro
                or extraction.company.mission
                or extraction.company.vision
                or extraction.company.values
            ),
            CompanyExtraction(),
        )
        subjects = [
            subject
            for extraction in extractions
            for subject in extraction.subjects
        ]
        return BookExtraction(company=company, subjects=subjects)


def _extract_with_provider(
    completion: Any,
    text: str,
    page_count: int,
    provider_name: str,
) -> BookExtraction:
    prompt = NVIDIAExtractionProvider._prompt(text, page_count)
    extraction = parse_provider_response(completion(prompt))
    terminal_trace(
        "normalized",
        f"provider={provider_name} subjects={len(extraction.subjects)}",
    )
    return extraction