import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


def terminal_trace(label: str, value: Any) -> None:
    print(f"[OpenRouter:{label}] {value}", flush=True)


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
        raise ValueError("OpenRouter returned an empty message content")
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
    raise ValueError("OpenRouter response did not contain a JSON object")


def normalize_provider_payload(payload: Any) -> BookExtraction:
    if isinstance(payload, list):
        return BookExtraction(
            company=CompanyExtraction(),
            subjects=[_normalize_subject(item) for item in payload],
        )
    if not isinstance(payload, dict):
        raise ValueError("OpenRouter returned a non-object extraction")

    if "company" in payload and "subjects" in payload:
        return BookExtraction.model_validate(payload)

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

    raise ValueError("OpenRouter returned neither a book extraction nor a subject object")


def _looks_like_subject(payload: dict[str, Any]) -> bool:
    return "title" in payload and any(
        key in payload for key in ("rawText", "raw_text", "description", "text", "content")
    )


def _normalize_subject(payload: Any) -> SubjectExtraction:
    if not isinstance(payload, dict):
        raise ValueError("OpenRouter returned a non-object subject")
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
class OpenRouterExtractionProvider:
    api_key: str
    model: str = "minimax/minimax-m3:free"
    base_url: str = "https://openrouter.ai/api/v1"
    max_retries: int = 1

    def _stream_completion(self, prompt: str) -> str:
        response_text: list[str] = []
        reasoning_text: list[str] = []
        choice: dict[str, Any] = {}
        terminal_trace("request", f"model={self.model} streaming=true")
        with httpx.stream(
            "POST",
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
                        "content": (
                            "Think privately, then return only the final valid JSON object. "
                            "Never include your reasoning, analysis, markdown fences, or commentary."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 8000,
                "reasoning": {"enabled": False},
                "response_format": {"type": "json_object"},
                "stream": False,
            },
            timeout=60,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                choice = event.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                reasoning = delta.get("reasoning") or ""
                reasoning_details = delta.get("reasoning_details") or []
                content = delta.get("content") or ""
                if reasoning:
                    reasoning_text.append(reasoning)
                    terminal_trace("reasoning", reasoning)
                    logger.info("OpenRouter reasoning: %s", reasoning)
                for detail in reasoning_details:
                    detail_text = detail.get("text") if isinstance(detail, dict) else None
                    if detail_text:
                        reasoning_text.append(detail_text)
                        terminal_trace("reasoning_details", detail_text)
                        logger.info("OpenRouter reasoning: %s", detail_text)
                if content:
                    response_text.append(content)
                    terminal_trace("content_chunk", content)
                    logger.info("OpenRouter final response: %s", content)

        terminal_trace(
            "stream_complete",
            f"reasoning_chars={len(''.join(reasoning_text))} content_chars={len(''.join(response_text))} "
            f"finish_reason={choice.get('finish_reason', 'unknown')}",
        )
        if not response_text:
            finish_reason = choice.get("finish_reason", "unknown")
            if reasoning_text:
                logger.warning(
                    "OpenRouter completed reasoning but returned no final content "
                    "(finish_reason=%s)",
                    finish_reason,
                )
            raise ValueError(
                f"OpenRouter returned no final content (finish_reason={finish_reason})"
            )
        final_response = "".join(response_text)
        terminal_trace("raw_response", final_response)
        return final_response

    def extract(self, text: str, page_count: int) -> BookExtraction:
        prompt = self._prompt(text, page_count)
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                extraction = parse_provider_response(self._stream_completion(prompt))
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
        raise ValueError(f"OpenRouter returned invalid structured extraction: {last_error}") from last_error

    @staticmethod
    def _prompt(text: str, page_count: int) -> str:
        instructions = [
            "Extract a PFE catalog into the requested JSON schema.",
            "Do not invent information. Use empty strings or empty arrays when absent.",
            "Return company context and each internship subject as a complete raw text block.",
            "Use [PAGE N] markers for 1-based page ranges; use null when unavailable.",
            "Preserve skills, location, and contact details inside rawText.",
            f"The source has approximately {page_count} pages.",
            "SOURCE TEXT:",
            text,
        ]
        return "\n".join(instructions)