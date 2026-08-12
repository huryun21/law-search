import json
from importlib.resources import files

from .models import Region, RegionResolution


def _normalize(value: str) -> str:
    return "".join(value.split()).casefold()


class RegionRegistry:
    def __init__(
        self,
        regions: tuple[Region, ...],
        unverified_api_codes: frozenset[tuple[str, str | None]] = frozenset(),
    ):
        self.regions = regions
        self.unverified_api_codes = unverified_api_codes
        index: dict[str, list[Region]] = {}
        for region in regions:
            names = set(region.aliases)
            if region.municipality_name is None:
                names.add(region.province_name)
            if region.municipality_name:
                names.add(region.municipality_name)
                if region.municipality_name[-1:] in {"시", "군", "구"}:
                    names.add(region.municipality_name[:-1])
            for name in names:
                index.setdefault(_normalize(name), []).append(region)
        self._index = {key: tuple(dict.fromkeys(value)) for key, value in index.items()}

    @classmethod
    def from_package_data(cls) -> "RegionRegistry":
        data_path = files("lawsearch").joinpath("data/regions.json")
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        regions = tuple(
            Region(**{**item, "aliases": tuple(item["aliases"])}) for item in payload["regions"]
        )
        unverified = frozenset(
            (item["org"], item.get("sborg"))
            for item in payload["metadata"]["api_compatibility"]["unverified_codes"]
        )
        return cls(regions, unverified)

    def resolve(self, token: str) -> RegionResolution:
        candidates = self._index.get(_normalize(token), ())
        if len(candidates) == 1 and (candidates[0].org, candidates[0].sborg) not in self.unverified_api_codes:
            return RegionResolution(candidates[0])
        return RegionResolution(None, candidates)
