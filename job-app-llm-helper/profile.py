# profile.py
"""Runtime applicant profile — supplied by the user in the browser, not read from disk.

The personal edition of this app loaded a fixed resume/LinkedIn/cover-letter corpus
from local .docx files and a curated YAML story bank. The public edition is
stateless: every request carries a ``profile`` dict the user typed (and the browser
remembers in localStorage). This module turns that dict into the prompt-ready blocks
the generator expects, with no filesystem or network access.

Profile shape (all keys optional except ``background``):

    {
      "applicant_name": "Ada Lovelace",
      "background": "<pasted resume / experience / LinkedIn text>",
      "contact": {"name", "city_state", "phone", "email", "linkedin"},
      "writing_samples": "<pasted prose the AI should match in voice>",
      "stories": "<freeform notes on specific accomplishments>"
    }
"""

from __future__ import annotations

import re
import statistics
from collections import Counter

# Phrases never to use — generic AI-cover-letter tells. Hand-curated, applicant-agnostic.
ANTI_PATTERNS = [
    "I am thrilled",
    "I am writing to express my interest",
    "I am writing to apply",
    "I would like to express my interest",
    "It is with great enthusiasm",
    "I am excited to apply",
    "Please find attached",
    "In conclusion",
    "In closing",
    "delve into",
    "tapestry",
    "navigate the complexities",
    "wealth of experience",
    "dynamic and results-driven",
    "passionate about making a difference",
    "stand out from other candidates",
    "I am confident that",
    # 2026 buzzword spikes — see the anti-AI-tell guidance in the platform guide
    "leverage",
    "utilize",
    "robust",
    "seamless",
    "pivotal",
    "underscore",
    "testament to",
    "streamline",
    "cutting-edge",
]

_MIN_BACKGROUND_CHARS = 40


def applicant_name(profile: dict) -> str:
    """The applicant's name, or a neutral fallback used in prompt scaffolding."""
    name = (profile.get("applicant_name") or "").strip()
    if name:
        return name
    contact = profile.get("contact") or {}
    return (contact.get("name") or "").strip() or "the applicant"


def has_minimum_profile(profile: dict) -> bool:
    """True when the user supplied enough background text to generate from."""
    return len((profile.get("background") or "").strip()) >= _MIN_BACKGROUND_CHARS


def build_profile_summary(profile: dict) -> str:
    """Render the applicant's background as a prompt block.

    Replaces the personal edition's resume/cover-letter/LinkedIn corpus with the
    single free-text ``background`` field the user pastes in.
    """
    name = applicant_name(profile)
    background = (profile.get("background") or "").strip()
    if not background:
        return f"=== {name.upper()}'S BACKGROUND ===\n(No background provided.)"
    return f"=== {name.upper()}'S BACKGROUND (resume / experience / profile) ===\n{background}"


def build_stories_block(profile: dict) -> str:
    """Render optional applicant-supplied accomplishment notes as a prompt block.

    Returns an empty string when the user provided none — the generator handles the
    absence gracefully (it simply has fewer concrete anecdotes to draw on).
    """
    stories = (profile.get("stories") or "").strip()
    if not stories:
        return ""
    name = applicant_name(profile)
    header = (
        f"=== {name.upper()}'S STORY NOTES ===\n"
        "Concrete accomplishments the applicant supplied. Draw on the ones whose "
        "subject matter matches this job. Do NOT invent specifics, numbers, or quotes "
        "beyond what is written here, and do not merge separate stories into one anecdote."
    )
    return f"{header}\n\n{stories}"


# ----- voice fingerprint (computed from pasted text, not files) ---------------

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_SALUTATION_RE = re.compile(r"^\s*(Dear\s|To Whom)", re.IGNORECASE)
_CLOSING_RE = re.compile(
    r"^\s*(Sincerely|Best regards|Best,|Warm regards|Warmly|Kind regards|Thanks|"
    r"Thank you|Yours truly|Cordially)",
    re.IGNORECASE,
)
_TRANSITION_LEADS = {
    "as a result",
    "during my time",
    "through that experience",
    "i learned",
    "i led",
    "i believe",
    "previously,",
    "additionally,",
    "furthermore,",
    "however,",
    "for example",
    "for instance",
    "moreover",
    "in particular",
    "specifically,",
    "my time as",
    "my experience",
    "i would love",
}


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if len(p.strip()) > 30]


def _sentences(text: str) -> list[str]:
    return [
        s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip().split()) >= 3
    ]


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z'’]+", text)


def _strip_letter_scaffolding(text: str) -> str:
    """For cover-letter-style prose, keep the body between salutation and closing."""
    lines = text.splitlines()
    salutation_idx = next(
        (i for i, ln in enumerate(lines) if _SALUTATION_RE.match(ln)), -1
    )
    closing_idx = next(
        (i for i in range(len(lines) - 1, -1, -1) if _CLOSING_RE.match(lines[i])), -1
    )
    if salutation_idx >= 0 and closing_idx > salutation_idx:
        return "\n".join(lines[salutation_idx + 1 : closing_idx]).strip()
    return text.strip()


def _opener_phrase(paragraph: str, n: int = 4) -> str:
    sents = _sentences(paragraph)
    if not sents:
        return ""
    return " ".join(sents[0].split()[:n]).rstrip(",.;:")


def _closer_phrase(paragraph: str, n: int = 4) -> str:
    sents = _sentences(paragraph)
    if not sents:
        return ""
    return " ".join(sents[-1].split()[-n:]).rstrip(",.;:")


def _ngrams(words: list[str], n: int) -> list[str]:
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def _transition_phrases(text: str, n: int = 4) -> Counter:
    counter: Counter = Counter()
    for g in _ngrams(text.split(), n):
        g_low = g.lower().strip(",.;:")
        for lead in _TRANSITION_LEADS:
            if g_low.startswith(lead):
                counter[g.strip(",.;:")] += 1
                break
    return counter


def _anti_patterns_block() -> str:
    lines = ["Do NOT use these phrases (generic AI / cover-letter cliché):"]
    lines += [f'  • "{p}"' for p in ANTI_PATTERNS]
    return "\n".join(lines)


def build_voice_fingerprint(profile: dict) -> str:
    """Compute a prompt-ready voice fingerprint from the user's pasted writing samples.

    When no samples are supplied, returns just the anti-pattern guard so the generator
    still avoids the worst AI tells while matching no specific voice.
    """
    raw = (profile.get("writing_samples") or "").strip()
    if not raw:
        return (
            "=== VOICE GUIDANCE ===\n"
            "No writing samples were provided, so there is no personal voice to match. "
            "Write in clear, direct, human prose; vary sentence length; avoid corporate "
            "filler and AI clichés.\n\n" + _anti_patterns_block()
        )

    # Treat the pasted text as one or more samples separated by blank-line runs of 3+.
    chunks = [c.strip() for c in re.split(r"\n\s*\n\s*\n+", raw) if c.strip()] or [raw]
    bodies = [
        b for b in (_strip_letter_scaffolding(c) for c in chunks) if len(b) >= 150
    ]
    if not bodies:
        bodies = [raw]

    sentence_word_counts: list[int] = []
    paragraph_sentence_counts: list[int] = []
    openers: Counter = Counter()
    closers: Counter = Counter()
    transitions: Counter = Counter()
    exemplars: list[str] = []

    for body in bodies:
        for para in _paragraphs(body):
            sents = _sentences(para)
            if not sents:
                continue
            paragraph_sentence_counts.append(len(sents))
            for sent in sents:
                sentence_word_counts.append(len(_words(sent)))
            opener = _opener_phrase(para)
            if opener and len(opener.split()) >= 2:
                openers[opener] += 1
            closer = _closer_phrase(para)
            if closer and len(closer.split()) >= 2:
                closers[closer] += 1
        transitions.update(_transition_phrases(body))

    # exemplar paragraphs: prefer substantive ~4-sentence ones
    for body in bodies:
        paras = sorted(
            _paragraphs(body),
            key=lambda p: abs(len(_sentences(p)) - 4) + (1 if len(p) < 300 else 0),
        )
        if paras:
            exemplars.append(paras[0])
        if len(exemplars) >= 3:
            break

    avg_sent = statistics.mean(sentence_word_counts) if sentence_word_counts else 0
    median_sent = statistics.median(sentence_word_counts) if sentence_word_counts else 0
    stdev_sent = (
        statistics.stdev(sentence_word_counts) if len(sentence_word_counts) > 1 else 0
    )
    avg_para = (
        statistics.mean(paragraph_sentence_counts) if paragraph_sentence_counts else 0
    )

    lines = ["=== YOUR VOICE FINGERPRINT (match this) ==="]
    lines.append(
        f"Stats across {len(bodies)} sample(s): avg sentence {avg_sent:.0f} words "
        f"(median {median_sent:.0f}, stdev {stdev_sent:.0f}); avg paragraph "
        f"{avg_para:.1f} sentences. Match this distribution — cohesive paragraphs, "
        "varied sentence length, not bullet fragments."
    )
    if openers:
        lines.append(
            "\nCharacteristic paragraph openers (reuse these or close variants):"
        )
        lines += [
            f'  • "{p}…"' + (f"  (×{c})" if c > 1 else "")
            for p, c in openers.most_common(6)
        ]
    if closers:
        lines.append("\nCharacteristic paragraph closers:")
        lines += [
            f'  • "…{p}"' + (f"  (×{c})" if c > 1 else "")
            for p, c in closers.most_common(5)
        ]
    if transitions:
        common = [(p, c) for p, c in transitions.most_common(8) if c >= 2]
        if common:
            lines.append("\nCharacteristic transitions / connective phrases:")
            lines += [f'  • "{p}…"  (×{c})' for p, c in common]
    if exemplars:
        lines.append("\nVoice exemplars (match this rhythm and register):")
        for i, ex in enumerate(exemplars, 1):
            lines.append(f"\n  EXEMPLAR {i}:")
            lines.append("  " + ex.replace("\n", " ").strip())

    lines.append("\n" + _anti_patterns_block())
    return "\n".join(lines)


def contact_from_profile(profile: dict) -> dict:
    """Extract the docx-header contact dict from a profile (used by docx_writer)."""
    contact = dict(profile.get("contact") or {})
    if not contact.get("name"):
        contact["name"] = applicant_name(profile)
    return contact
