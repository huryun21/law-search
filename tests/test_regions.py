from lawsearch.models import Region
from lawsearch.regions import RegionRegistry


def test_registry_contains_all_current_provinces_and_municipalities():
    registry = RegionRegistry.from_package_data()
    assert len({region.org for region in registry.regions}) == 16
    assert sum(region.sborg is not None for region in registry.regions) >= 229


def test_integrated_province_is_the_current_official_region():
    resolution = RegionRegistry.from_package_data().resolve("전남광주")
    assert resolution.is_unique
    assert resolution.region.province_name == "전남광주통합특별시"
    assert resolution.region.org == "6130000"
    assert resolution.region.sborg is None


def test_legacy_province_names_resolve_to_the_integrated_region():
    registry = RegionRegistry.from_package_data()
    for token in ("광주광역시", "전라남도", "전남"):
        resolution = registry.resolve(token)
        assert resolution.is_unique
        assert resolution.region.province_name == "전남광주통합특별시"


def test_bare_gwangju_remains_ambiguous():
    resolution = RegionRegistry.from_package_data().resolve("광주")
    assert not resolution.is_unique
    assert {candidate.province_name for candidate in resolution.candidates} >= {
        "경기도",
        "전남광주통합특별시",
    }


def test_legacy_qualified_names_resolve_to_current_municipalities():
    registry = RegionRegistry.from_package_data()
    assert registry.resolve("광주/동구").region.sborg == "5805000"
    assert registry.resolve("전남/목포").region.sborg == "5780000"


def test_current_incheon_districts_resolve_by_new_names():
    registry = RegionRegistry.from_package_data()
    expected = {
        "제물포": "3501000",
        "영종": "3491000",
        "검단": "3565000",
        "서해": "3561000",
    }
    for token, sborg in expected.items():
        resolution = registry.resolve(token)
        assert resolution.is_unique
        assert resolution.region.sborg == sborg


def test_legacy_incheon_split_names_return_safe_candidates():
    registry = RegionRegistry.from_package_data()
    old_junggu = registry.resolve("인천/중구")
    old_seogu = registry.resolve("인천/서구")
    assert not old_junggu.is_unique
    assert {item.municipality_name for item in old_junggu.candidates} == {"영종구", "제물포구"}
    assert not old_seogu.is_unique
    assert {item.municipality_name for item in old_seogu.candidates} == {"검단구", "서해구"}


def test_legacy_incheon_donggu_maps_to_jemulpo():
    resolution = RegionRegistry.from_package_data().resolve("인천/동구")
    assert resolution.is_unique
    assert resolution.region.municipality_name == "제물포구"


def test_unverified_api_code_is_never_promoted_to_searchable_region():
    region = Region("검증대기지역", None, "9999999", aliases=("검증대기",))
    registry = RegionRegistry((region,), unverified_api_codes=frozenset({("9999999", None)}))
    resolution = registry.resolve("검증대기")
    assert not resolution.is_unique
    assert resolution.candidates == (region,)


def test_pyeongtaek_resolves_to_gyeonggi_municipality():
    resolution = RegionRegistry.from_package_data().resolve("평택")
    assert resolution.is_unique
    assert resolution.region.province_name == "경기도"
    assert resolution.region.municipality_name == "평택시"
    assert resolution.region.org.isdigit() and len(resolution.region.org) == 7
    assert resolution.region.sborg.isdigit() and len(resolution.region.sborg) == 7


def test_junggu_returns_multiple_candidates():
    resolution = RegionRegistry.from_package_data().resolve("중구")
    assert not resolution.is_unique
    assert len(resolution.candidates) >= 3
