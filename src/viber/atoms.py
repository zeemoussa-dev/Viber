"""Viber stores short rows, never documents. These are the size limits and the splitter that turns a long
text (an ADR section, a memory note) into rows that each hold one statement."""
import re

FACT_MAX = 500
RULE_MAX = 400
EPISODE_MAX = 1000
SPEC_MAX = 400
POINT_MAX = 500
RELATION_MAX = 60

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+")


def split_atoms(text: str, limit: int) -> list[str]:
    """One statement per row: a line (bullet markers dropped) is a row; a longer line is packed by sentence, and
    a sentence longer than the limit is wrapped at a word boundary. Order is kept; empty lines vanish."""
    atoms: list[str] = []
    for line in _statements(text):
        if len(line) <= limit:
            atoms.append(line)
            continue
        current = ""
        for sentence in _SENTENCE_END.split(line):
            for piece in _wrap(sentence, limit):
                if current and len(current) + 1 + len(piece) > limit:
                    atoms.append(current)
                    current = piece
                else:
                    current = f"{current} {piece}".strip()
        if current:
            atoms.append(current)
    return atoms


def split_lines(text: str, limit: int) -> list[str]:
    """One row per line (bullet markers dropped), for lists such as requirements where every line is its own statement."""
    rows: list[str] = []
    for raw in (text or "").splitlines():
        line = _BULLET.sub("", raw).strip()
        if line:
            rows.extend(split_atoms(line, limit))
    return rows


def _statements(text: str) -> list[str]:
    """A bullet starts a statement and a blank line ends one; the lines of a wrapped paragraph are one statement."""
    blocks: list[str] = []
    current = ""
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            if current:
                blocks.append(current)
            current = ""
        elif _BULLET.match(raw):
            if current:
                blocks.append(current)
            current = _BULLET.sub("", raw).strip()
        else:
            current = f"{current} {stripped}".strip()
    if current:
        blocks.append(current)
    return blocks


def _wrap(sentence: str, limit: int) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    pieces, current = [], ""
    for word in sentence.split():
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces
