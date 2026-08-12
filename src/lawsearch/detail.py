from collections.abc import Mapping
from html.parser import HTMLParser
import re
from typing import Any


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
            seen.add(text)
            contexts.append(text)
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
