from collections.abc import Mapping
from html.parser import HTMLParser
import re
from typing import Any


_MAX_CONTEXT_CHARS = 400


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def extract_contexts(payload: Any, keyword: str, limit: int = 5) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    compact_keyword = _compact(keyword)
    if not compact_keyword:
        return ()

    contexts: list[str] = []
    seen: set[str] = set()
    for value in _strings(payload):
        text = _plain_text(value)
        if text and compact_keyword in _compact(text) and text not in seen:
            excerpt = _excerpt(text, compact_keyword)
            if excerpt in seen:
                continue
            seen.add(excerpt)
            contexts.append(excerpt)
            if len(contexts) == limit:
                break
    return tuple(contexts)


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _excerpt(text: str, compact_keyword: str) -> str:
    if len(text) <= _MAX_CONTEXT_CHARS:
        return text

    positions = [index for index, character in enumerate(text) if not character.isspace()]
    compact_text = "".join(text[index] for index in positions)
    compact_start = compact_text.find(compact_keyword)
    match_start = positions[compact_start]
    match_end = positions[compact_start + len(compact_keyword) - 1] + 1

    sentence_start = max(text.rfind(mark, 0, match_start) for mark in ".!?\n") + 1
    sentence_ends = [text.find(mark, match_end) for mark in ".!?\n"]
    sentence_ends = [index + 1 for index in sentence_ends if index >= 0]
    sentence_end = min(sentence_ends, default=len(text))
    sentence = text[sentence_start:sentence_end].strip()
    if sentence and len(sentence) <= _MAX_CONTEXT_CHARS:
        return sentence

    body_limit = _MAX_CONTEXT_CHARS - 2
    match_length = match_end - match_start
    left = max(0, match_start - (body_limit - match_length) // 2)
    right = min(len(text), left + body_limit)
    left = max(0, right - body_limit)
    return f"…{text[left:right].strip()}…"
