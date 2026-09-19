import re
import unicodedata
from dataclasses import dataclass, field

_SECTION_HEADINGS = {
    "skills": (
        "compétences",
        "competences",
        "compétences techniques",
        "skills",
        "technical skills",
        "technologies",
        "stack technique",
        "langages",
        "outils",
    ),
    "education": (
        "formation",
        "éducation",
        "education",
        "diplômes",
        "diplomes",
        "études",
        "studies",
        "académique",
        "parcours académique",
    ),
    "experience": (
        "expérience",
        "experience",
        "expériences professionnelles",
        "professional experience",
        "parcours professionnel",
        "stages",
        "internships",
    ),
    "projects": (
        "projets",
        "projects",
        "projets académiques",
        "projets personnels",
        "travaux",
    ),
    "certifications": (
        "certifications",
        "certifications professionnelles",
        "certifications techniques",
        "attestations",
        "cours certifiants",
    ),
}

# Common CV sections we do not classify into a profile bucket: when encountered,
# they close the current section so their bullets don't leak into the previous one.
_SECTION_BOUNDARIES = frozenset(
    re.sub(r"\s+", " ", name).casefold()
    for name in (
        "Certifications",
        "Langues",
        "Languages",
        "Langues étrangères",
        "Centres d'intérêt",
        "Centres d'interets",
        "Hobbies",
        "Intérêts",
        "Références",
        "References",
        "Loïsirs",
        "Loisirs",
        "Soft skills",
        "Qualités",
        "Bénévolat",
        "Activités",
        "Activités extra-professionnelles",
        "Mobilité",
        "Permis",
        "Profil",
        "Summary",
        "Résumé",
        "Objectifs",
        "Contact",
    )
)

_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:\d[.)]?[ \t]*)?(?:"
    r"(?P<skill>comp[eé]tences?(?:[ \t]+techniques?)?|competences?|"
    r"languages?|outils?|technologies?|stack[ \t]+technique)"
    r"|(?P<edu>formation|education|education[ \t]+continue|dipl[oô]me[s]?|e[é]tudes?|parcours[ \t]+acade[é]mique)"
    r"|(?P<exp>exp[eé]riences?(?:[ \t]+professionnelles?)?|(?:professional[ \t]+)?experience|"
    r"parcours[ \t]+professionnel|stages?|internships?)"
    r"|(?P<proj>projets?|[a-z][ \t]+projets?[ \t]+(?:acade[é]miques?|personnels?)|projects)"
    r"|(?P<cert>certifications?(?:[ \t]+(?:professionnelles?|techniques?))?|attestations?)"
    r")[ \t]*[:\[\t-]?[ \t]*$"
)

_ITEM_RE = re.compile(r"(?im)^[ \t]*(?:[-*•‣⁃▪▸◦·\u2022\u25cf\u2023\u2043]|\d+[.)]|\[x\])[ \t]+(?P<item>.+)$")

# Any line with >= 4 tokens outside a bullet is treated as substantive content of
# the current section (role lines, company stacks, dates, wrapped fragments...).
_SUBSTANTIVE_RE = re.compile(r"^(?=\S)(?:\S+\s+){3,}\S+$")

# Unknown headings that look like stand-alone section titles: ALL-CAPS only.
_ALL_CAPS_RE = re.compile(r"^[A-ZÀ-Þ][A-ZÀ-Þ'’-]*(?:[ \t]+[A-ZÀ-Þ][A-ZÀ-Þ'’-]*)*$")

# Spacing diacritics that PDF extraction sometimes emits instead of the composed
# letter (e.g. "Exp´erience" for "Expérience"). We reattach them and NFC-compose.
_SPACING_DIACRITIC = {
    "\u00b4": "\u0301",  # acute accent
    "\u0060": "\u0300",  # grave accent
    "\u00a8": "\u0308",  # diaeresis
    "\u00b8": "\u0327",  # cedilla
    "\u02c6": "\u0302",  # modifier circumflex
    "\u005e": "\u0302",  # ASCII caret
    "\u007e": "\u0303",  # ASCII tilde
    "\u02dc": "\u0303",  # modifier tilde
}


def _repair_accented_text(text: str) -> str:
    if not text:
        return ""
    pending: str | None = None
    pieces: list[str] = []
    for char in text:
        combining = _SPACING_DIACRITIC.get(char)
        if combining:
            pending = combining
            continue
        if char.isalpha() and pending is not None:
            pieces.append(char + pending)
            pending = None
            continue
        pieces.append(char)
    if pending is not None:
        pieces.append(pending)
    return unicodedata.normalize("NFC", "".join(pieces))


@dataclass(frozen=True)
class CvProfile:
    skills: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    experience: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)

    @property
    def query(self) -> str:
        """Free-text query derived from the profile, used for keyword/dense matching."""
        ranked = " ".join(self.skills[:12])
        ranked += " " + " ".join(self.projects[:6])
        ranked += " " + " ".join(self.experience[:6])
        ranked += " " + " ".join(self.certifications[:4])
        return " ".join(ranked.split())


def parse_cv(text: str) -> CvProfile:
    """Lightweight, keyless CV parser: splits the text by known section headings
    (FR/EN) and collects bullet items per section. Deliberately rules-based so it
    never requires a provider key; an LLM refinement is an optional later step."""
    text = _repair_accented_text(text)
    lines = [raw.strip() for raw in text.splitlines() if raw.strip()]
    sections: list[tuple[str, list[str]]] = []
    current: str | None = None
    for index, line in enumerate(lines):
        heading = _HEADING_RE.fullmatch(line)
        if heading:
            if heading.group("skill"):
                current = "skills"
            elif heading.group("edu"):
                current = "education"
            elif heading.group("exp"):
                current = "experience"
            elif heading.group("proj"):
                current = "projects"
            elif heading.group("cert"):
                current = "certifications"
            sections.append((current, []))
            continue
        next_is_bullet = index + 1 < len(lines) and bool(_ITEM_RE.match(lines[index + 1]))
        if re.sub(r"\s+", " ", line).casefold() in _SECTION_BOUNDARIES or (
            _ALL_CAPS_RE.fullmatch(line) and next_is_bullet
        ):
            current = None
            continue
        item = _ITEM_RE.match(line)
        if item and current is not None:
            sections[-1][1].append(item.group("item").strip())
        elif current is not None and _SUBSTANTIVE_RE.fullmatch(line):
            sections[-1][1].append(line)
    return CvProfile(
        skills=_dedup(extract(sections, "skills")),
        education=_dedup(extract(sections, "education")),
        experience=_dedup(extract(sections, "experience")),
        projects=_dedup(extract(sections, "projects")),
        certifications=_dedup(extract(sections, "certifications")),
    )


def extract(sections: list[tuple[str, list[str]]], wanted: str) -> list[str]:
    for name, items in sections:
        if name == wanted:
            return items
    return []


def _dedup(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = re.sub(r"\s+", "", item).lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result