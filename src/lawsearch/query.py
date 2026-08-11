from .models import MatchQuality, ParsedQuery, QueryVariant
from .regions import RegionRegistry


class QueryError(ValueError):
    pass


def parse_query(raw: str, registry: RegionRegistry) -> ParsedQuery:
    parts = raw.split()
    region_tokens = [part for part in parts if part.startswith("@")]
    if len(region_tokens) > 1:
        raise QueryError("지역은 하나만 지정할 수 있습니다")
    keyword = " ".join(part for part in parts if not part.startswith("@"))
    if not region_tokens:
        return ParsedQuery(keyword)
    resolution = registry.resolve(region_tokens[0][1:])
    return ParsedQuery(keyword, resolution.region, resolution.candidates)


def build_query_variants(keyword: str) -> tuple[QueryVariant, ...]:
    exact = " ".join(keyword.split())
    candidates = (
        QueryVariant(exact, MatchQuality.EXACT),
        QueryVariant(exact.replace(" ", ""), MatchQuality.COMPACT),
    )
    seen = set()
    variants = []
    for item in candidates:
        if item.query and item.query not in seen:
            seen.add(item.query)
            variants.append(item)
    return tuple(variants)
