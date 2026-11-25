"""Version constraint solving. PEP 440 specifiers and npm/semver ranges both reduce to PEP 440 sets."""
import re

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

WILDCARD_CHARACTERS = {"x", "X", "*"}
PARTIAL_VERSION = re.compile(r"^[vV=]?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:-([0-9A-Za-z.-]+))?$")
OPERATOR_THEN_SPACE = re.compile(r"(\^|~>?|>=|<=|>|<|=)\s+")


class ConstraintError(ValueError):
    pass


def parse_version(text: str) -> Version:
    try:
        return Version(text.strip().lstrip("vV"))
    except InvalidVersion as error:
        raise ConstraintError(f"not a version: {text!r}") from error


def split_partial(text: str) -> tuple[int | None, int | None, int | None]:
    match = PARTIAL_VERSION.match(text)
    if not match:
        raise ConstraintError(f"not a version or range: {text!r}")
    numbers = [None if part is None or part in WILDCARD_CHARACTERS else int(part) for part in match.groups()[:3]]
    return numbers[0], numbers[1], numbers[2]


def dotted(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def range_for_partial(major, minor, patch) -> list[str]:
    if major is None:
        return []
    if minor is None:
        return [f">={dotted(major, 0, 0)}", f"<{dotted(major + 1, 0, 0)}"]
    if patch is None:
        return [f">={dotted(major, minor, 0)}", f"<{dotted(major, minor + 1, 0)}"]
    return [f"=={dotted(major, minor, patch)}"]


def caret_range(major, minor, patch) -> list[str]:
    if major is None:
        return []
    lower = f">={dotted(major, minor or 0, patch or 0)}"
    if major > 0:
        return [lower, f"<{dotted(major + 1, 0, 0)}"]
    if minor is None:
        return [lower, "<1.0.0"]
    if minor > 0:
        return [lower, f"<{dotted(0, minor + 1, 0)}"]
    if patch is None:
        return [lower, "<0.1.0"]
    return [lower, f"<{dotted(0, 0, patch + 1)}"]


def tilde_range(major, minor, patch) -> list[str]:
    if major is None:
        return []
    lower = f">={dotted(major, minor or 0, patch or 0)}"
    upper = dotted(major + 1, 0, 0) if minor is None else dotted(major, minor + 1, 0)
    return [lower, f"<{upper}"]


def comparator_range(operator: str, major, minor, patch) -> list[str]:
    if major is None:
        return []
    low = dotted(major, minor or 0, patch or 0)
    if operator == ">=":
        return [f">={low}"]
    if operator == "<":
        return [f"<{low}"]
    if operator == ">":
        if patch is not None:
            return [f">{low}"]
        bumped = dotted(major + 1, 0, 0) if minor is None else dotted(major, minor + 1, 0)
        return [f">={bumped}"]
    if operator == "<=":
        if patch is not None:
            return [f"<={low}"]
        bumped = dotted(major + 1, 0, 0) if minor is None else dotted(major, minor + 1, 0)
        return [f"<{bumped}"]
    return range_for_partial(major, minor, patch)


def token_to_specifiers(token: str) -> list[str]:
    if token in ("", "*", "x", "X", "latest"):
        return []
    for operator in ("^", "~>", "~", ">=", "<=", ">", "<", "="):
        if token.startswith(operator):
            parts = split_partial(token[len(operator):])
            if operator == "^":
                return caret_range(*parts)
            if operator in ("~", "~>"):
                return tilde_range(*parts)
            return comparator_range(operator, *parts)
    return range_for_partial(*split_partial(token))


def npm_alternatives(constraint: str) -> list[SpecifierSet]:
    alternatives = []
    for alternative in constraint.split("||"):
        text = OPERATOR_THEN_SPACE.sub(r"\1", alternative.strip())
        if " - " in text:
            low, high = [side.strip() for side in text.split(" - ", 1)]
            tokens = [f">={low}", f"<={high}"]
        else:
            tokens = text.split()
        specifiers: list[str] = []
        for token in tokens:
            specifiers += token_to_specifiers(token)
        try:
            alternatives.append(SpecifierSet(",".join(specifiers)))
        except InvalidSpecifier as error:
            raise ConstraintError(f"cannot read constraint {constraint!r}") from error
    return alternatives


def satisfies(version_text: str, constraint: str, syntax: str = "semver") -> bool:
    constraint = (constraint or "").strip()
    if not constraint:
        return True
    version = parse_version(version_text)
    if syntax == "pep440":
        try:
            return SpecifierSet(constraint).contains(version, prereleases=True)
        except InvalidSpecifier as error:
            raise ConstraintError(f"cannot read constraint {constraint!r}") from error
    return any(alternative.contains(version, prereleases=True) for alternative in npm_alternatives(constraint))


def highest(version_texts: list[str]) -> str | None:
    valid = []
    for text in version_texts:
        try:
            valid.append((parse_version(text), text))
        except ConstraintError:
            continue
    return max(valid, key=lambda pair: pair[0])[1] if valid else None
