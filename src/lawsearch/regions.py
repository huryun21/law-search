import json
from importlib.resources import files

from .models import Region, RegionResolution


def _normalize(value: str) -> str:
    return "".join(value.split()).casefold()


class RegionRegistry:
    def __init__(self, regions: tuple[Region, ...]):
        self.regions = regions
        index: dict[str, list[Region]] = {}
        for region in regions:
            names = {region.province_name, *region.aliases}
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
        return cls(
            tuple(Region(**{**item, "aliases": tuple(item["aliases"])}) for item in payload["regions"])
        )

    def resolve(self, token: str) -> RegionResolution:
        candidates = self._index.get(_normalize(token.lstrip("@")), ())
        if len(candidates) == 1:
            return RegionResolution(candidates[0])
        return RegionResolution(None, candidates)
