import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


def terminal_trace(label: str, value: Any) -> None:
    print(f"[Extract:{label}] {value}", flush=True)


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


def parse_provider_response(response_text: Any) -> BookExtraction:
    if isinstance(response_text, list):
        response_text = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in response_text
        )
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("Provider returned an empty message content")
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
    raise ValueError("Provider response did not contain a JSON object")


def normalize_provider_payload(payload: Any) -> BookExtraction:
    if isinstance(payload, list):
        return BookExtraction(
            company=CompanyExtraction(),
            subjects=[_normalize_subject(item) for item in payload],
        )
    if not isinstance(payload, dict):
        raise ValueError("Provider returned a non-object extraction")

    if "company" in payload and isinstance(payload["company"], dict) and "subjects" in payload:
        return BookExtraction.model_validate(payload)

    internships = payload.get("internships") or payload.get("internship")
    if isinstance(internships, list):
        return BookExtraction(
            company=_company_from_context(
                payload.get("companyContext") or payload.get("internshipContext")
            ),
            subjects=[_normalize_subject(item) for item in internships],
        )

    if "subjects" in payload and isinstance(payload["subjects"], list):
        company_payload = payload.get("company")
        return BookExtraction(
            company=(
                CompanyExtraction.model_validate(company_payload)
                if isinstance(company_payload, dict)
                else CompanyExtraction()
            ),
            subjects=[_normalize_subject(item) for item in payload["subjects"]],
        )

    if not payload.get("subjects") and not payload.get("internships") and not payload.get("internship"):
        company_context = payload.get("companyContext") or payload.get("company_context")
        if company_context is None and isinstance(payload.get("company"), dict):
            company_context = payload["company"]
        if company_context is not None:
            return BookExtraction(company=_company_from_context(company_context), subjects=[])
        if _looks_like_company_context(payload):
            return BookExtraction(company=_company_from_context(payload), subjects=[])

    if _looks_like_subject(payload):
        return BookExtraction(
            company=CompanyExtraction(),
            subjects=[_normalize_subject(payload)],
        )

    raise ValueError("Provider returned neither a book extraction nor a subject object")


def _looks_like_subject(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("title", "name", "id", "code")) and any(
        key in payload for key in ("rawText", "raw_text", "description", "text", "content")
    )


def _looks_like_company_context(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("email", "website", "values")) and not any(
        key in payload for key in ("title", "subject", "reference", "duration", "specialties")
    )


def _normalize_subject(payload: Any) -> SubjectExtraction:
    if isinstance(payload, str):
        payload = {"title": payload}
    if not isinstance(payload, dict):
        raise ValueError("Provider returned a non-object subject")
    raw_text = next(
        (
            payload.get(key)
            for key in ("rawText", "raw_text", "description", "text", "content")
            if payload.get(key)
        ),
        "",
    )
    raw_text = str(raw_text)
    page_start, page_end = _page_range(
        payload.get("page", payload.get("pages", payload.get("pageRange")))
    )
    if page_start is None:
        page_start, page_end = _page_range_from_text(raw_text)
    reference = payload.get("reference")
    if reference:
        raw_text = f"Reference: {reference}\n{raw_text}"
    title = next(
        (str(payload.get(key)) for key in ("title", "name", "subject") if payload.get(key)),
        None,
    )
    if not title:
        title = _subject_title_from_text(raw_text)
    if not title:
        title = next(
            (str(payload.get(key)) for key in ("id", "code") if payload.get(key)),
            None,
        )
    return SubjectExtraction(
        title=title or "Untitled subject",
        rawText=raw_text,
        pageStart=page_start,
        pageEnd=page_end,
    )


def _subject_title_from_text(raw_text: str) -> str | None:
    match = SUBJECT_HEADER_RE.search(raw_text)
    if match and _is_subject_header(match):
        header_title = match.group("title") or match.group("standalone_title") or ""
        code = match.group("code") or match.group("standalone_code") or ""
        header = header_title.strip(" :-") or code.strip()
        if header:
            return header
    return _title_line_from_block(raw_text)


SUBJECT_JUNK_LINE_RE = re.compile(
    r"(?i)^(?:"
    r"\[PAGE\s+\d+\]"
    r"|\d{1,4}"
    r"|references?\s*:?\s*\S*"
    r"|r[ée]f[ée]rences?\s+sujets?\s*:?\s*\S*"
    r"|r[ée]f\s*:?\s*\S*"
    r"|bu\s*[:\-]\s*.*"
    r")$"
)

_SUBJECT_TITLE_LABEL_RE = re.compile(
    r"(?i)^(?:title|titre|subject|sujet|projet|project)\s*[:•\-]\s*(?P<title>.+)$"
)

_CODE_LINE_RE = re.compile(r"^[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\-_/.]{1,20}\d[A-Za-zÀ-ÿ0-9\-_/.]*$")


def _title_line_from_block(raw_text: str) -> str | None:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    for line in lines:
        if SUBJECT_JUNK_LINE_RE.fullmatch(line):
            continue
        label = _SUBJECT_TITLE_LABEL_RE.fullmatch(line)
        if label:
            candidate = label.group("title").strip().strip(" :-")
            if candidate:
                return candidate
            continue
    for line in lines:
        if SUBJECT_JUNK_LINE_RE.fullmatch(line) or _CODE_LINE_RE.fullmatch(line):
            continue
        if line.endswith(":"):
            continue
        if len(line) >= 8:
            return line
    return None


def _company_from_context(context: Any) -> CompanyExtraction:
    if isinstance(context, str):
        return _local_company(context, None)
    if not isinstance(context, dict):
        return CompanyExtraction()
    company = CompanyExtraction(
        name=context.get("name") or context.get("company") or context.get("title"),
        intro=context.get("intro") or context.get("introduction"),
        mission=context.get("mission"),
        vision=context.get("vision"),
        values=[
            str(value)
            for value in (context.get("values") or [])
            if str(value).strip()
        ],
    )
    raw_text = next(
        (
            context.get(key)
            for key in ("rawText", "raw_text", "content", "text", "description")
            if context.get(key)
        ),
        None,
    )
    if raw_text:
        local = _local_company(str(raw_text), None)
        company = CompanyExtraction(
            name=company.name or local.name,
            intro=company.intro or local.intro,
            mission=company.mission or local.mission,
            vision=company.vision or local.vision,
            values=company.values or local.values,
        )
    return company


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


SUBJECT_HEADER_RE = re.compile(
    r"(?im)^[ \t]*(?:(?:sujet|subject|projet|project|internship|stage|pfe)"
    r"[ \t]*(?:[:#-][ \t]*)?(?P<code>(?:as|pfe)?[- ]?\d{1,}(?:/\d{2,4})?)"
    r"[ \t]*(?:[:\-][ \t]*)?(?P<title>[^\n]*)|"
    r"(?P<standalone_code>(?:as|pfe)[-_ ]?\d{2,}(?:/\d{2,4})?)"
    r"[ \t]*(?:[:\-][ \t]*)(?P<standalone_title>[^\n]+))[ \t]*$"
)
GENERIC_SUBJECT_TITLES = {
    "pfe book",
    "sommaire",
    "qui sommes-nous",
    "qui sommes -nous",
    "qui sommes - nous",
    "comment postuler",
    "les opportunités de stage",
}
LABEL_RE = re.compile(
    r"(?im)^\s*(?P<label>title|titre|mission|objectif|objectifs|"
    r"technologies?|technology|stack technique|compétences?|skills?|"
    r"description|contexte)\s*[:\-]\s*(?P<value>.*)$"
)
COMPANY_LABEL_RE = re.compile(
    r"(?im)^\s*(?P<label>company|entreprise|introduction|présentation|"
    r"mission|vision|values|valeurs)\s*[:\-]\s*(?P<value>.*)$"
)


@dataclass(frozen=True)
class LocalSubjectCandidate:
    raw_text: str
    title: str
    page_start: int | None
    page_end: int | None
    fields: dict[str, str]
    confidence: float


def _page_range_from_text(text: str) -> tuple[int | None, int | None]:
    pages = [int(value) for value in re.findall(r"\[PAGE\s+(\d+)\]", text, re.IGNORECASE)]
    return (min(pages), max(pages)) if pages else (None, None)


def _labeled_fields(text: str) -> dict[str, str]:
    matches = list(LABEL_RE.finditer(text))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        value_lines = [match.group("value").strip()]
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        continuation = text[match.end() : next_start].strip()
        if continuation:
            value_lines.append(continuation)
        fields[match.group("label").lower()] = "\n".join(
            line for line in value_lines if line
        )
    return fields


def _subject_title(match: re.Match[str], fields: dict[str, str]) -> str:
    header_title = match.group("title") or match.group("standalone_title") or ""
    code = match.group("code") or match.group("standalone_code") or ""
    return (
        fields.get("title")
        or fields.get("titre")
        or header_title.strip(" :-")
        or code.strip()
        or "Untitled subject"
    )


def _is_subject_header(match: re.Match[str]) -> bool:
    title = _subject_title(match, {})
    normalized = re.sub(r"\s+", " ", title.lower()).strip(" :-")
    if normalized in GENERIC_SUBJECT_TITLES:
        return False
    return bool(match.group("code") or match.group("standalone_code"))


def _subject_confidence(title: str, raw_text: str, fields: dict[str, str]) -> float:
    signals = [
        title != "Untitled subject",
        len(raw_text.strip()) >= 120,
        bool(fields),
    ]
    return sum(signals) / len(signals)


def parse_local_subjects(text: str) -> list[LocalSubjectCandidate]:
    """Parse common PFE subject blocks without using an LLM."""
    matches = [
        match for match in SUBJECT_HEADER_RE.finditer(text) if _is_subject_header(match)
    ]
    candidates: list[LocalSubjectCandidate] = []
    for index, match in enumerate(matches):
        page_marker_start = text.rfind("[PAGE", 0, match.start())
        block_start = page_marker_start if page_marker_start >= 0 else match.start()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw_text = text[block_start:block_end].strip()
        fields = _labeled_fields(raw_text)
        title = _subject_title(match, fields)
        page_start, page_end = _page_range_from_text(raw_text)
        candidates.append(
            LocalSubjectCandidate(
                raw_text=raw_text,
                title=title,
                page_start=page_start,
                page_end=page_end,
                fields=fields,
                confidence=_subject_confidence(title, raw_text, fields),
            )
        )
    return candidates


def _local_company(text: str, first_subject_start: int | None) -> CompanyExtraction:
    intro = text[:first_subject_start] if first_subject_start is not None else text
    fields = _labeled_fields(intro)
    company_fields = {
        match.group("label").lower(): match.group("value").strip()
        for match in COMPANY_LABEL_RE.finditer(intro)
    }
    name = company_fields.get("company") or company_fields.get("entreprise")
    return CompanyExtraction(
        name=name or None,
        intro=company_fields.get("introduction")
        or company_fields.get("présentation")
        or None,
        mission=company_fields.get("mission") or fields.get("mission") or None,
        vision=company_fields.get("vision") or None,
        values=[
            value.strip()
            for value in re.split(r"[,;|\n]", company_fields.get("values", company_fields.get("valeurs", "")))
            if value.strip()
        ],
    )


def select_candidate_pages(
    text: str,
    max_characters: int = 12000,
    context_pages: int = 1,
) -> str:
    """Keep likely PFE subject pages and small context windows for the LLM."""
    pages = [page.strip() for page in re.split(r"(?=\[PAGE\s+\d+\])", text) if page.strip()]
    if not pages:
        return text[:max_characters]

    scored_pages: list[tuple[int, int]] = []
    for index, page in enumerate(pages):
        normalized = page.lower()
        score = 0
        score += 5 * len(re.findall(r"\b(?:sujet|projet|stage|pfe|internship)\b", normalized))
        score += 4 * len(re.findall(r"\b(?:as|pfe)[-_ ]?\d{2,}\b", normalized))
        score += 2 * len(
            re.findall(
                r"\b(?:mission|objectif|technologies?|compétences?|skills?|description|contexte)\b",
                normalized,
            )
        )
        if re.search(r"^\s*(?:\d+[.)]|[-*])\s+\S+", page, re.MULTILINE):
            score += 1
        if score:
            scored_pages.append((score, index))

    selected: set[int] = {0}
    for _, index in sorted(scored_pages, reverse=True):
        selected.update(
            nearby
            for nearby in range(
                max(0, index - context_pages),
                min(len(pages), index + context_pages + 1),
            )
        )
        candidate = "\n\n".join(pages[item] for item in sorted(selected))
        if len(candidate) >= max_characters:
            break

    selected_text = "\n\n".join(pages[index] for index in sorted(selected))
    if len(selected_text) > max_characters:
        selected_text = selected_text[:max_characters]
        selected_text += "\n[Candidate pages truncated to fit the provider token limit.]"
    return selected_text


_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="g4f")


@dataclass(frozen=True)
class G4FExtractionProvider:
    providers: tuple[tuple[str, str], ...] = (
        ("Gemini", "gemini-3.6-flash"),
        ("Cloudflare", "glm-5.2"),
        ("Gemini", "gemini-3.1-flash-lite"),
        ("LLM7", "default"),
    )
    max_tokens: int = 8000
    chunk_characters: int = 8000
    retries_per_provider: int = 2
    attempt_timeout: float = 120.0

    def _completion(self, prompt: str, provider_name: str, model_name: str) -> str:
        terminal_trace(
            "request",
            f"provider=g4f backend={provider_name} model={model_name}",
        )
        submission = _EXECUTOR.submit(
            self._request_completion, provider_name, model_name, prompt
        )
        try:
            return submission.result(timeout=self.attempt_timeout)
        except FutureTimeoutError as error:
            raise TimeoutError(
                f"g4f provider {provider_name}/{model_name} timed out "
                f"after {self.attempt_timeout:g}s"
            ) from error

    def _request_completion(self, provider_name: str, model_name: str, prompt: str) -> str:
        from g4f import Provider
        from g4f.client import Client

        selected_provider = getattr(Provider, provider_name)
        if not model_name:
            model_name = getattr(selected_provider, "default_model", None)
        response = Client().chat.completions.create(
            model=model_name,
            provider=selected_provider,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only one valid JSON object. "
                        "Do not include reasoning, tool calls, markdown fences, or commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=self.max_tokens,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("g4f returned non-text or empty final content")
        terminal_trace("raw_response", content)
        return content

    def _extract_chunk(self, chunk: str, page_count: int) -> BookExtraction:
        prompt = self._prompt(chunk, page_count, self.chunk_characters)
        failures: list[str] = []
        for provider_name, model_name in self.providers:
            for attempt in range(1, self.retries_per_provider + 1):
                try:
                    extraction = parse_provider_response(
                        self._completion(prompt, provider_name, model_name)
                    )
                    terminal_trace(
                        "normalized",
                        f"provider={provider_name}/{model_name} subjects={len(extraction.subjects)}",
                    )
                    return extraction
                except Exception as error:
                    failure = f"{provider_name}/{model_name} attempt {attempt}: {error}"
                    failures.append(failure)
                    terminal_trace("provider_error", failure)
        raise RuntimeError("All g4f providers failed: " + " | ".join(failures))

    @staticmethod
    def _prompt(text: str, page_count: int, max_source_characters: int = 6000) -> str:
        source_text = text[:max_source_characters]
        if len(text) > max_source_characters:
            source_text += "\n[Source text truncated to fit the provider token limit.]"
        instructions = [
            "Extract a PFE catalog into the requested JSON schema.",
            "Do not invent information. Use empty strings or empty arrays when absent.",
            "The source below is a slice of the book, not the full catalog.",
            "Return company context and each internship subject as a complete raw text block.",
            "Use [PAGE N] markers for 1-based page ranges; use null when unavailable.",
            "Preserve skills, location, and contact details inside rawText.",
            f"The source has approximately {page_count} pages.",
            "SOURCE TEXT:",
            source_text,
        ]
        return "\n".join(instructions)

    def extract(self, text: str, page_count: int) -> BookExtraction:
        extractions = [
            self._extract_chunk(chunk, page_count)
            for chunk in chunk_text(text, max_characters=self.chunk_characters)
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
        subjects = [subject for extraction in extractions for subject in extraction.subjects]
        return BookExtraction(company=company, subjects=subjects)