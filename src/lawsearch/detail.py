from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Any
import unicodedata


_MAX_CONTEXT_CHARS = 400
_ARTICLE_HEADING = re.compile(r"^\s*(제\d+조(?:의\d+)?)(?:\(([^)]+)\))?\s*")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass(frozen=True)
class _Candidate:
    relevance: int
    order: int
    location: str
    text: str


def extract_contexts(payload: Any, keyword: str, limit: int = 5) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    compact_keyword = _compact(keyword)
    if not compact_keyword:
        return ()

    units = tuple(_article_units(payload))
    exact = _collect_candidates(units, keyword, exact=True)
    candidates = exact or _collect_candidates(units, keyword, exact=False)

    contexts: list[str] = []
    seen: set[str] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.relevance,
            -item.location.count(" > "),
            len(_compact(item.text)),
            item.order,
            item.location,
        ),
    ):
        context = _format_context(candidate, compact_keyword)
        if context in seen:
            continue
        seen.add(context)
        contexts.append(context)
        if len(contexts) == limit:
            break
    return tuple(contexts)


def _article_units(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        article_section = value.get("조문")
        if isinstance(article_section, Mapping):
            units = article_section.get("조문단위", article_section.get("조"))
            for unit in _as_items(units):
                if isinstance(unit, Mapping):
                    yield unit
        for item in value.values():
            yield from _article_units(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _article_units(item)


def _collect_candidates(
    units: tuple[Mapping[str, Any], ...], keyword: str, *, exact: bool
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for order, unit in enumerate(units):
        location, title = _article_location(unit)
        direct_content = _plain_text(
            str(unit.get("조문내용") or unit.get("조내용") or "")
        )
        direct_content = _strip_article_heading(direct_content)
        title_matches = _matches(title, keyword, exact=exact)
        if title_matches:
            text = direct_content or title
            candidates.append(_Candidate(0, order, location, text))

        nested = tuple(_nested_candidates(unit, location, order, keyword, exact))
        candidates.extend(nested)
        if not nested and direct_content and not title_matches and _matches(
            direct_content, keyword, exact=exact
        ):
            candidates.append(_Candidate(1 if exact else 2, order, location, direct_content))
    return candidates


def _nested_candidates(
    unit: Mapping[str, Any],
    article_location: str,
    order: int,
    keyword: str,
    exact: bool,
) -> Iterable[_Candidate]:
    for paragraph in _as_mappings(unit.get("항")):
        paragraph_marker = str(paragraph.get("항번호") or "")
        paragraph_location = _join_location(
            article_location, _legal_marker(paragraph_marker, "항")
        )
        paragraph_text = _clean_leaf(paragraph.get("항내용"), paragraph_marker)
        if paragraph_text and _matches(paragraph_text, keyword, exact=exact):
            yield _Candidate(1 if exact else 2, order, paragraph_location, paragraph_text)
        yield from _numbered_children(
            paragraph,
            "호",
            "호번호",
            "호내용",
            paragraph_location,
            order,
            keyword,
            exact,
        )

    yield from _numbered_children(
        unit,
        "호",
        "호번호",
        "호내용",
        article_location,
        order,
        keyword,
        exact,
    )


def _numbered_children(
    parent: Mapping[str, Any],
    child_key: str,
    marker_key: str,
    content_key: str,
    parent_location: str,
    order: int,
    keyword: str,
    exact: bool,
) -> Iterable[_Candidate]:
    for child in _as_mappings(parent.get(child_key)):
        marker = str(child.get(marker_key) or "")
        location = _join_location(parent_location, _legal_marker(marker, child_key))
        text = _clean_leaf(child.get(content_key), marker)
        if text and _matches(text, keyword, exact=exact):
            yield _Candidate(1 if exact else 2, order, location, text)
        next_key = "목" if child_key == "호" else None
        if next_key is not None:
            yield from _numbered_children(
                child,
                next_key,
                "목번호",
                "목내용",
                location,
                order,
                keyword,
                exact,
            )


def _article_location(unit: Mapping[str, Any]) -> tuple[str, str]:
    title = _plain_text(str(unit.get("조문제목") or unit.get("조제목") or ""))
    content = _plain_text(str(unit.get("조문내용") or unit.get("조내용") or ""))
    heading = _ARTICLE_HEADING.match(content)
    if heading:
        article = heading.group(1)
        title = title or (heading.group(2) or "")
    else:
        article = _article_number(
            unit.get("조문번호"), unit.get("조문가지번호")
        )
    return (f"{article}({title})" if title else article, title)


def _article_number(number: Any, branch: Any) -> str:
    if isinstance(number, (list, tuple)):
        number = number[0] if number else ""
    digits = "".join(re.findall(r"\d+", str(number or "")))
    if len(digits) >= 4 and digits.endswith("00"):
        digits = str(int(digits) // 100)
    elif digits:
        digits = str(int(digits))
    else:
        digits = "?"
    branch_digits = "".join(re.findall(r"\d+", str(branch or "")))
    suffix = f"의{int(branch_digits)}" if branch_digits and int(branch_digits) else ""
    return f"제{digits}조{suffix}"


def _legal_marker(value: str, level: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if level == "항" and len(value) == 1:
        try:
            number = int(unicodedata.numeric(value))
        except (TypeError, ValueError):
            number = 0
        if number:
            return f"제{number}항"
    digits = re.search(r"\d+", value)
    if digits:
        return f"제{int(digits.group())}{level}"
    if level == "목":
        letter = re.sub(r"[^가-힣A-Za-z]", "", value)
        if letter:
            return f"{letter}목"
    return value


def _join_location(parent: str, child: str) -> str:
    return f"{parent} > {child}" if child else parent


def _as_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    return tuple(value) if isinstance(value, (list, tuple)) else (value,)


def _as_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    return (item for item in _as_items(value) if isinstance(item, Mapping))


def _clean_leaf(value: Any, marker: str) -> str:
    text = _plain_text(str(value or ""))
    marker = marker.strip()
    if marker and text.startswith(marker):
        text = text[len(marker) :].strip()
    return text


def _strip_article_heading(text: str) -> str:
    return _ARTICLE_HEADING.sub("", text, count=1).strip()


def _matches(text: str, keyword: str, *, exact: bool) -> bool:
    compact_text = _compact(text)
    compact_keyword = _compact(keyword)
    if exact:
        return compact_keyword in compact_text
    tokens = tuple(_compact(token) for token in keyword.split() if _compact(token))
    return len(tokens) >= 2 and all(token in compact_text for token in tokens)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _format_context(candidate: _Candidate, compact_keyword: str) -> str:
    prefix = f"{candidate.location} — "
    available = max(20, _MAX_CONTEXT_CHARS - len(prefix))
    return prefix + _excerpt(candidate.text, compact_keyword, available)


def _excerpt(text: str, compact_keyword: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    positions = [index for index, character in enumerate(text) if not character.isspace()]
    compact_text = "".join(text[index] for index in positions)
    compact_start = compact_text.find(compact_keyword)
    if compact_start < 0:
        return text[: limit - 1].rstrip() + "…"
    match_start = positions[compact_start]
    match_end = positions[compact_start + len(compact_keyword) - 1] + 1

    body_limit = limit - 2
    match_length = match_end - match_start
    left = max(0, match_start - (body_limit - match_length) // 2)
    right = min(len(text), left + body_limit)
    left = max(0, right - body_limit)
    return f"…{text[left:right].strip()}…"
