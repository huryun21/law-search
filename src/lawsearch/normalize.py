from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from lawsearch.models import MatchQuality, SearchResult, SearchScope, SourceGroup


class ResponseShapeError(ValueError):
    pass


_SOURCE_SHAPES = {
    SourceGroup.LAW: ("LawSearch", ("law", "법령")),
    SourceGroup.DECREE: ("LawSearch", ("law", "법령")),
    SourceGroup.MINISTERIAL_RULE: ("LawSearch", ("law", "법령")),
    SourceGroup.OTHER: ("LawSearch", ("law", "법령")),
    SourceGroup.ADMIN_RULE: ("AdmRulSearch", ("admrul", "행정규칙")),
    SourceGroup.MUNICIPAL: ("OrdinSearch", ("law", "ordin", "자치법규")),
    SourceGroup.PROVINCIAL: ("OrdinSearch", ("law", "ordin", "자치법규")),
}


def normalize_results(
    payload: Mapping[str, Any],
    source: SourceGroup,
    quality: MatchQuality,
    fetched_at: datetime,
    *,
    scope: SearchScope = SearchScope.BODY,
) -> tuple[SearchResult, ...]:
    try:
        wrapper_name, record_names = _SOURCE_SHAPES[source]
        wrapper = payload[wrapper_name]
        if not isinstance(wrapper, Mapping):
            raise TypeError
        raw_records = next((wrapper[name] for name in record_names if name in wrapper), None)
        if raw_records is None:
            if str(wrapper.get("totalCnt", wrapper.get("검색결과개수", ""))) == "0":
                return ()
            raise KeyError
        records = raw_records if isinstance(raw_records, list) else [raw_records]
        if not all(isinstance(record, Mapping) for record in records):
            raise TypeError
        return tuple(
            _normalize_record(record, source, quality, fetched_at, scope)
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ResponseShapeError):
            raise
        raise _shape_error(source) from exc


def _normalize_record(
    record: Mapping[str, Any],
    source: SourceGroup,
    quality: MatchQuality,
    fetched_at: datetime,
    scope: SearchScope,
) -> SearchResult:
    if source in {SourceGroup.LAW, SourceGroup.DECREE, SourceGroup.MINISTERIAL_RULE, SourceGroup.OTHER}:
        uid = _required(record, "법령ID", "법령일련번호")
        title = _required(record, "법령명한글", "법령명")
        category = _optional(record, "법령구분명") or "법령"
        authority = _optional(record, "소관부처명")
        region_name = None
        promulgation = _parse_date(_optional(record, "공포일자"))
        current = _current(_optional(record, "현행연혁코드", "현행연혁구분"))
        link = _required(record, "법령상세링크", "상세링크")
        normalized_source = _classify_law(category)
    elif source is SourceGroup.ADMIN_RULE:
        uid = _required(record, "행정규칙ID", "행정규칙일련번호")
        title = _required(record, "행정규칙명")
        category = _optional(record, "행정규칙종류") or "행정규칙"
        authority = _optional(record, "소관부처명")
        region_name = None
        promulgation = _parse_date(_optional(record, "발령일자"))
        current = _current(_optional(record, "현행연혁구분", "현행여부"))
        link = _required(record, "행정규칙상세링크", "상세링크")
        normalized_source = source
    else:
        uid = _required(record, "자치법규ID", "자치법규일련번호")
        title = _required(record, "자치법규명")
        category = _optional(record, "자치법규종류") or "자치법규"
        authority = _optional(record, "지자체기관명")
        region_name = authority
        promulgation = _parse_date(_optional(record, "공포일자"))
        current = _current(_optional(record, "현행연혁구분", "현행여부"))
        link = _required(record, "자치법규상세링크", "상세링크")
        normalized_source = source

    return SearchResult(
        uid=uid,
        source=normalized_source,
        quality=quality,
        title=title,
        category=category,
        authority=authority,
        region_name=region_name,
        promulgation_date=promulgation,
        effective_date=_parse_date(_optional(record, "시행일자")),
        is_current=current,
        official_url=_official_url(link, normalized_source),
        fetched_at=fetched_at,
        scope=scope,
    )


def _required(record: Mapping[str, Any], *names: str) -> str:
    value = _optional(record, *names)
    if value is None:
        raise ValueError
    return value


def _optional(record: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = record.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return datetime.strptime(value.replace("-", ""), "%Y%m%d").date()


def _current(value: str | None) -> bool:
    return value is None or value in {"현행", "Y", "1"}


def _classify_law(category: str) -> SourceGroup:
    if "대통령령" in category or "시행령" in category:
        return SourceGroup.DECREE
    if any(label in category for label in ("총리령", "부령", "시행규칙")):
        return SourceGroup.MINISTERIAL_RULE
    if "법률" in category:
        return SourceGroup.LAW
    return SourceGroup.OTHER


def _official_url(value: str, source: SourceGroup) -> str:
    url = urljoin("https://www.law.go.kr/", value)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.law.go.kr":
        raise ValueError
    if parsed.path.casefold() == "/drf/lawservice.do":
        parameters = dict(parse_qsl(parsed.query))
        if source in {
            SourceGroup.LAW,
            SourceGroup.DECREE,
            SourceGroup.MINISTERIAL_RULE,
            SourceGroup.OTHER,
        }:
            path, public_name, identifier = (
                "/LSW/lsInfoP.do",
                "lsiSeq",
                parameters.get("MST"),
            )
        elif source in {SourceGroup.MUNICIPAL, SourceGroup.PROVINCIAL}:
            path, public_name, identifier = (
                "/LSW/ordinInfoP.do",
                "ordinSeq",
                parameters.get("MST"),
            )
        else:
            path, public_name, identifier = (
                "/LSW/admRulInfoP.do",
                "admRulSeq",
                parameters.get("ID"),
            )
        if identifier is None or not identifier.isdigit():
            raise ValueError
        return urlunparse(
            ("https", "www.law.go.kr", path, "", urlencode({public_name: identifier}), "")
        )
    return url


def _shape_error(source: SourceGroup) -> ResponseShapeError:
    return ResponseShapeError(f"{source.value} 응답 형식을 처리할 수 없습니다.")
