"""De-slop: strip the tell-tale signatures of AI-generated writing.

Applied to every draft the AI Studio / campaign generator produces, BEFORE it
reaches the user, so content reads like a person wrote it — not a chatbot.

Deliberately conservative: it removes/rewrites known AI tics (em-dash overuse,
hedge preambles, "delve/tapestry" vocabulary, emoji spam, LLM meta-talk) but
never rewrites the substance. Idempotent — running it twice changes nothing.

``deslop_html`` runs the same cleanup on the text nodes of an HTML body while
leaving tags/attributes intact (for Ghost long-form).
"""
from __future__ import annotations

import re

# Whole-phrase preamble/hedge cutter — matches a leading clause up to its comma.
_PREAMBLE = re.compile(
    r"(?im)^\s*(?:"
    r"as an ai(?: language model)?|"
    r"as a large language model|"
    r"in today['’]s (?:fast[- ]paced|digital|modern) world|"
    r"in the (?:ever[- ]evolving|fast[- ]changing) landscape[^,.]*|"
    r"it['’]s (?:important|worth|crucial) (?:to note|noting|to remember|mentioning) that|"
    r"it is (?:important|worth|crucial) (?:to note|noting|to remember|mentioning) that|"
    r"needless to say|"
    r"without a doubt|"
    r"at the end of the day"
    r")[,:]?\s*",
)

# In-line phrases to delete outright (with surrounding space tidy afterward).
_PHRASES = [
    r"\bit['’]s (?:important|worth|crucial) to note that\b",
    r"\bit is (?:important|worth|crucial) to note that\b",
    r"\bwhen it comes to\b",
    r"\bin conclusion\b",
    r"\bin summary\b",
    r"\bthat being said\b",
    r"\bfirst and foremost\b",
]

# Slop vocabulary → plainer swaps (word-boundary, case-insensitive, case-kept
# for the capitalised sentence-start form).
_WORD_SWAPS = {
    r"\bdelve into\b": "look at",
    r"\bdelving into\b": "looking at",
    r"\bdelve\b": "look",
    r"\btapestry\b": "mix",
    r"\b(?:a )?myriad of\b": "many",
    r"\bmyriad\b": "many",
    r"\b(?:a )?plethora of\b": "plenty of",
    r"\ba testament to\b": "a sign of",
    r"\btestament to\b": "sign of",
    r"\bunderscore(s)?\b": r"show\1",
    r"\bleverage\b": "use",
    r"\bleveraging\b": "using",
    r"\butilize\b": "use",
    r"\butilizing\b": "using",
    r"\bfoster(s)?\b": r"build\1",
    r"\brobust\b": "solid",
    r"\bseamless(ly)?\b": "smooth",
    r"\bnavigate the\b": "handle the",
    r"\bin the realm of\b": "in",
    r"\bembark on\b": "start",
    r"\bharness(ing)?\b": "use",
    r"\bgame[- ]changer\b": "big deal",
    r"\bcutting[- ]edge\b": "advanced",
    r"\bunlock(ing)?\b": "open up",
    r"\bpivotal\b": "key",
    r"\bmeticulous(ly)?\b": "careful",
}

# Transition openers that scream "AI paragraph" — soften to nothing at line start.
_OPENERS = re.compile(
    r"(?im)^\s*(?:furthermore|moreover|additionally|notably|importantly)[,]?\s+",
)

# Meta-preamble the model prepends to a caption ("Here is your LinkedIn post,
# written in the AfCEN voice.") — strip the whole leading line + any fence after.
_META_PREAMBLE = re.compile(
    r"(?is)^\s*(?:sure[,!.]?\s*)?(?:here(?:['’]s| is)|below is|this is)\b[^\n]*?"
    r"\b(?:post|caption|draft|version|copy|thread|tweet|write[- ]?up)\b[^\n]*\r?\n+",
)

# Markdown that must NOT reach a social caption (renders as literal * # ` on-platform).
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")          # [text](url) -> text (url)
_MD_HR = re.compile(r"(?m)^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$")     # --- *** ___ rules
_MD_HEADER = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+")               # ## Heading -> Heading
_MD_QUOTE = re.compile(r"(?m)^[ \t]{0,3}>[ \t]?")                     # > quote
_MD_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)         # **x** __x__ -> x
_MD_ITALIC = re.compile(r"(?<![\w*_])([*_])(?=\S)([^*_\n]+?)(?<=\S)\1(?![\w*_])")  # *x* _x_ -> x
_MD_CODE = re.compile(r"`([^`\n]+)`")                                # `x` -> x


def _strip_markdown(text: str) -> str:
    """Flatten markdown to plain text so it doesn't render as raw *, #, ` on social."""
    text = _MD_LINK.sub(r"\1 (\2)", text)
    text = _MD_HR.sub("", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_QUOTE.sub("", text)
    text = _MD_BOLD.sub(r"\2", text)     # ** before * so bold isn't eaten by italic
    text = _MD_ITALIC.sub(r"\2", text)
    text = _MD_CODE.sub(r"\1", text)
    return text


def _apply_word_swaps(text: str) -> str:
    for pat, repl in _WORD_SWAPS.items():
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    return text


def _strip_phrases(text: str) -> str:
    for pat in _PHRASES:
        text = re.sub(pat + r"[,]?\s*", "", text, flags=re.IGNORECASE)
    return text


def _deslop_inline(text: str) -> str:
    """Fragment-safe cleanup: no sentence-start anchoring, no recapitalisation.

    Applied to standalone plain text AND to individual HTML text nodes, where
    assuming a fragment starts a sentence would wrongly capitalise mid-sentence
    words (e.g. inside <strong>) or link text.
    """
    out = text
    # Em/en dashes → comma+space (the #1 AI tell); collapse spaced dashes too.
    out = re.sub(r"\s*[—–]\s*", ", ", out)
    out = _strip_phrases(out)
    out = _apply_word_swaps(out)
    # Emoji spam: collapse runs of 2+ emoji/symbols to a single one.
    out = re.sub(r"([\U0001F300-\U0001FAFF☀-➿]{1})[\U0001F300-\U0001FAFF☀-➿\s]+", r"\1 ", out)
    # Excess punctuation: !!! → !, ??? → ?
    out = re.sub(r"([!?])\1{1,}", r"\1", out)
    # Tidy whitespace the deletions left behind.
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([,.!?;:])", r"\1", out)
    return out


def deslop(text: str) -> str:
    """Clean AI tics from a plain-text string. Safe on empty / already-clean."""
    if not text:
        return text
    # Structural (start-anchored) passes run ONLY on full plain text.
    out = _META_PREAMBLE.sub("", text)   # "Here is your LinkedIn post, …" → gone
    out = _PREAMBLE.sub("", out)
    out = _OPENERS.sub("", out)
    out = _strip_markdown(out)           # **bold**/##/---/`code` → plain
    out = _deslop_inline(out)
    # Recapitalise a sentence whose leading clause we removed.
    out = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# Split an HTML body into tags vs text nodes so cleanup only touches prose.
_TAG_SPLIT = re.compile(r"(<[^>]+>)")


def deslop_html(html: str) -> str:
    """De-slop the text nodes of an HTML fragment, leaving tags untouched."""
    if not html:
        return html
    parts = _TAG_SPLIT.split(html)
    for i, part in enumerate(parts):
        if i % 2 == 0 and part.strip():  # text node — fragment-safe pass only
            parts[i] = _deslop_inline(part)
    return "".join(parts)
