import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from app.book_extraction import (
    GENERIC_SUBJECT_TITLES,
    SUBJECT_JUNK_LINE_RE,
    SubjectExtraction,
    _CODE_LINE_RE,
    _SUBJECT_TITLE_LABEL_RE,
    _subject_title_from_text,
)

_MOJIBAKE_PAIRS: tuple[tuple[str, str], ...] = (
    ("ÔÇÖ", "'"),
    ("ÔÇÿ", "'"),
    ("ÔÇ£", '"'),
    ("ÔÇØ", '"'),
    ("ÔÇô", "—"),
    ("ÔÇò", "―"),
    ("ÔÇó", "•"),
    ("ÔÇª", "…"),
    ("â€™", "'"),
    ("â€˜", "'"),
    ("â€œ", '"'),
    ("â€", '"'),
    ("â€“", "–"),
    ("â€”", "—"),
    ("â€¦", "…"),
    ("â€¢", "•"),
    ("Ã©", "é"),
    ("Ã¨", "è"),
    ("Ãª", "ê"),
    ("Ã«", "ë"),
    ("Ã®", "î"),
    ("Ã¯", "ï"),
    ("Ã¢", "â"),
    ("Ã§", "ç"),
    ("Ã±", "ñ"),
    ("Ã¶", "ö"),
    ("Ã¼", "ü"),
    ("Ã»", "û"),
    ("Ã´", "ô"),
    ("Ã¡", "á"),
    ("Ã¯", "ï"),
    ("Ã ", "à"),
    ("Ã‰", "É"),
    ("Ãˆ", "È"),
    ("ÃŠ", "Ê"),
    ("ÃŽ", "Î"),
    ("Ã‡", "Ç"),
    ("Ã¤", "ä"),
    ("├®", "é"),
    ("├ª", "ê"),
    ("├¿", "è"),
    ("├¬", "ë"),
    ("├á", "à"),
    ("├┤", "ô"),
    ("├╣", "ù"),
    ("├╗", "û"),
    ("├⌐", "é"),
    ("├º", "ç"),
    ("├ñ", "ä"),
    ("┬░", "°"),
    ("┬Ö", "™"),
    ("┬á", " "),
    ("Â", ""),
    ("\ufeff", ""),
    ("\u200b", ""),
    ("\u2011", "-"),
    ("\u00ad", ""),
)

_MOJIBAKE_MAP = dict(_MOJIBAKE_PAIRS)
_MOJIBAKE_RE = re.compile("|".join(re.escape(key) for key, _ in _MOJIBAKE_PAIRS))

_PAGE_MARKER_RE = re.compile(r"^[\[{\(](?:p(?:age)?|pg)\s*\d+[\]}\)]$", re.IGNORECASE)
_LONE_DIGIT_RE = re.compile(r"^\d{1,4}$")
_REFERENCE_PREFIX_RE = re.compile(
    r"^(?:references?|r[ée]f[ée]rences?|r[ée]f)\s*:?\s*",
    re.IGNORECASE,
)
_REFERENCE_CODE_RE = re.compile(
    r"[A-Za-zÀ-ÿ]{1,5}[\s_-]?\d{2,}(?:[/_]\d{2,4})?",
    re.IGNORECASE,
)
_CHROME_LINE_RE = re.compile(
    r"^(?:bu|r[ée]f[ée]rence\s+sujet)\s*[:•-]?\s*.{1,40}$",
    re.IGNORECASE,
)
_EMAIL_URL_SNIPPET_RE = re.compile(
    r"^(?:email|e-mail|site web|website|web|tel|t[ée]l|phone)\s*[:•-]?\s*\S+$",
    re.IGNORECASE,
)

_SEMANTIC_LABEL_RE = re.compile(
    r"^(?:description|dur[ée]e|sp[ée]cialit[ée]s?|technologies?|techno|"
    r"env(?:ironnement)?|pr[ée]requis?|prerequis?|comp[ée]tences?|competences?|"
    r"missions?|mission|objectifs?|objectif|contexte|r[ée]sum[ée]|resum[ée]|"
    r"livrables?|exigences?|activit[ée]s?|r[ôleô]le|pr[ée]stations?|résultats?|resultats?|"
    r"title|titre|sujet|projet|stage|pfe|internship|salary|r[ée]mun[ée]ration|"
    r"n[ée]cessaire|profil|skills?|r[ée]f[ée]rences?\s*:?|"
    r"(?:front|back|full.?stack)?-?end|stack|frameworks?|langages?|languages?|"
    r"outils?|moyens?|mat[ée]riels?|[ée]quipement)"
    r"\s*[:•-]?\s*.*$",
    re.IGNORECASE,
)

_REMOVE_CHAR_RE = re.compile(
    r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F"
    r"\u200B-\u200F\u2028-\u202E\u2060-\u206F\uFEFF"
    r"\uFFF0-\uFFFF\ud800-\udfff\ue000-\uf8ff]"
)

_TABBED_BULLET_RE = re.compile(r"^[ \t]*\u25cf[ \t]+")


def repair_mojibake(text: str) -> str:
    """Fix common mojibake artifacts produced by misplaced encodings."""
    return _MOJIBAKE_RE.sub(lambda match: _MOJIBAKE_MAP.get(match.group(0), match.group(0)), text)


def strip_dirty_characters(text: str) -> str:
    """Remove control chars and leftover non-typographic symbols."""
    lines = []
    for line in text.splitlines():
        line = line.replace("\t", " ").replace("\u00A0", " ")
        line = _REMOVE_CHAR_RE.sub("", line.rstrip())
        lines.append(line)
    return "\n".join(lines)


def _is_email_line(line: str) -> bool:
    stripped = line.strip()
    compact = re.sub(r"\s+", "", stripped)
    if not (8 <= len(compact) <= 40):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.@+\-]+", compact) is None:
        return False
    if "@" not in compact or "." not in compact:
        return False
    tokens = stripped.split()
    if tokens and all(len(token) == 1 for token in tokens):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9_.+\-]+@[A-Za-z0-9_.\-]+\.[A-Za-z]{2,4}", compact))


def _line_is_chrome(line: str) -> bool:
    return bool(
        _PAGE_MARKER_RE.fullmatch(line)
        or _LONE_DIGIT_RE.fullmatch(line)
        or _CHROME_LINE_RE.fullmatch(line)
        or _EMAIL_URL_SNIPPET_RE.fullmatch(line)
        or _is_email_line(line)
    )


def _line_reference(line: str) -> str | None:
    prefix = _REFERENCE_PREFIX_RE.match(line)
    if not prefix:
        return None
    code = line[prefix.end() :].strip()
    if _REFERENCE_CODE_RE.fullmatch(code):
        return code
    return None


def _sanitize_subject_text(text: str, boilerplate: Iterable[str] = ()) -> tuple[str, bool]:
    repaired = strip_dirty_characters(repair_mojibake(text))
    boilerplate_lines = {line.strip() for line in boilerplate if line.strip()}
    repaired_lines = repaired.splitlines()
    lines = []
    for index, raw_line in enumerate(repaired_lines):
        line = raw_line.strip()
        if not line:
            continue
        if _line_is_chrome(line):
            continue
        if line in boilerplate_lines:
            previous = repaired_lines[index - 1].strip() if index > 0 else ""
            at_edge = index < 2 or index >= len(repaired_lines) - 3
            follows_label = bool(previous) and bool(_SEMANTIC_LABEL_RE.match(previous))
            if at_edge and not follows_label:
                continue
        lines.append(_TABBED_BULLET_RE.sub("* ", line) if line.startswith("\u25cf") else line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", cleaned)).strip()

    if not cleaned or len(cleaned) < 0.25 * len(repaired):
        return repaired.strip(), True
    return cleaned, False


def sanitize_subject_text(text: str, boilerplate: Iterable[str] = ()) -> str:
    """Clean a subject's text for indexing while keeping the raw text intact.

    Strips page markers, lone page numbers, chrome/footer lines, and
    per-book boilerplate. Cleans general dirty characters. Falls back to a
    conservative (mojibake-only) pass if the aggressive pass would remove
    too much content, so unknown layouts degrade safely.
    """
    return _sanitize_subject_text(text, boilerplate)[0]


def detect_boilerplate(subject_texts: Iterable[str], threshold: float = 0.5) -> frozenset[str]:
    """Learn layout chrome: lines identical across many subjects of one book.

    Repeats that carry meaning (semantic labels, reference codes) are kept.
    """
    texts = list(subject_texts)
    if not texts:
        return frozenset()
    counts: Counter[str] = Counter()
    for text in texts:
        seen: set[str] = set()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _SEMANTIC_LABEL_RE.match(stripped):
                continue
            if _line_reference(stripped):
                continue
            if _line_is_chrome(stripped):
                continue
            if re.search(r"\d", stripped):
                continue
            seen.add(stripped)
        counts.update(seen)
    minimum = max(2, int(threshold * len(texts)))
    return frozenset(line for line, count in counts.items() if count >= minimum)


@dataclass(frozen=True)
class IndexSubject:
    reference: str | None
    title: str
    text: str
    raw_text: str
    page_start: int | None
    page_end: int | None
    embedding: list[float] | None = None


def _subject_reference(subject: SubjectExtraction) -> str | None:
    for line in (subject.rawText or "").splitlines():
        reference = _line_reference(line.strip())
        if reference:
            return reference
    return None


def _dedup_key(reference: str | None, title: str) -> str:
    normalized = re.sub(r"\s+", "", title or "").lower()
    if reference:
        return f"ref:{re.sub(r'[\s_/-]+', '', reference.lower())}"
    return f"title:{normalized}"


_TITLE_DIGITS_RE = re.compile(r"^\d+$")


def _recover_title(raw_text: str) -> str | None:
    def valid(candidate: str) -> str | None:
        candidate = (candidate or "").strip(" :-")
        if not candidate or candidate == "Untitled subject":
            return None
        if len(candidate) < 8:
            return None
        if _TITLE_DIGITS_RE.fullmatch(candidate):
            return None
        if candidate.lower() in GENERIC_SUBJECT_TITLES:
            return None
        return candidate

    for line in (raw_text or "").splitlines():
        label = _SUBJECT_TITLE_LABEL_RE.fullmatch(line.strip())
        if label:
            return valid(label.group("title")) or None

    header = _subject_title_from_text(raw_text)
    if header:
        valid_header = valid(header)
        if valid_header:
            return valid_header

    for line in (raw_text or "").splitlines():
        stripped = line.strip()
        for skipped in (
            SUBJECT_JUNK_LINE_RE.fullmatch(stripped),
            _CODE_LINE_RE.fullmatch(stripped),
        ):
            if skipped:
                break
        else:
            candidate = valid(stripped)
            if candidate:
                return candidate
    return None


def _subject_title(subject: SubjectExtraction) -> str:
    title = (subject.title or "").strip()
    if not title or title == "Untitled subject" or _TITLE_DIGITS_RE.fullmatch(title):
        return _recover_title(subject.rawText) or "Untitled subject"
    return title


def build_index_subjects(extraction: Any, boilerplate: Iterable[str] = ()) -> list[IndexSubject]:
    """Turn extracted subjects into de-duplicated, cleaned index records."""
    subjects: list[SubjectExtraction] = list(extraction.subjects)
    boilerplate_lines = frozenset(boilerplate)
    by_key: dict[str, SubjectExtraction] = {}
    for subject in subjects:
        reference = _subject_reference(subject)
        title = _subject_title(subject)
        key = _dedup_key(reference, title)
        existing = by_key.get(key)
        if existing is None or len(subject.rawText or "") > len(existing.rawText or ""):
            by_key[key] = SubjectExtraction(
                title=title,
                rawText=subject.rawText,
                pageStart=subject.pageStart,
                pageEnd=subject.pageEnd,
            )
    result: list[IndexSubject] = []
    for key, subject in by_key.items():
        result.append(
            IndexSubject(
                reference=_subject_reference(subject),
                title=subject.title,
                text=sanitize_subject_text(subject.rawText, boilerplate_lines),
                raw_text=subject.rawText,
                page_start=subject.pageStart,
                page_end=subject.pageEnd,
            )
        )
    return result


_MOJIBAKE_SNIFF_RE = re.compile(r"[ÃÂ�]ÔÇ|├|â€™|â€|├®|\\u00")


def quality_report(extraction: Any) -> dict[str, Any]:
    """Score an extraction for indexing readiness."""
    subjects = list(extraction.subjects)
    references = [_subject_reference(subject) for subject in subjects]
    reference_keys = [key for key in references if key]
    duplicate_references = len(reference_keys) - len(set(key.lower() for key in reference_keys))
    untitled = sum(1 for subject in subjects if subject.title in ("", "Untitled subject"))
    too_short = sum(1 for subject in subjects if len((subject.rawText or "").strip()) < 80)
    no_page = sum(1 for subject in subjects if subject.pageStart is None and subject.pageEnd is None)
    fixed_titles = sum(
        1
        for subject in subjects
        if subject.title in ("", "Untitled subject") and _subject_title_from_text(subject.rawText)
    )
    mojibake = sum(1 for subject in subjects if _MOJIBAKE_SNIFF_RE.search(subject.rawText or ""))
    floor_trips = sum(
        1
        for subject in subjects
        if _sanitize_subject_text(subject.rawText or "")[1]
    )
    return {
        "subjects": len(subjects),
        "untitled": untitled,
        "untitled_recoverable": fixed_titles,
        "duplicate_references": duplicate_references,
        "too_short": too_short,
        "no_page": no_page,
        "mojibake": mojibake,
        "floor_trips": floor_trips,
    }