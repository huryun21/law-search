from lawsearch.regions import RegionRegistry


def test_registry_contains_all_current_provinces_and_municipalities():
    registry = RegionRegistry.from_package_data()
    assert len({region.org for region in registry.regions}) == 17
    assert sum(region.sborg is not None for region in registry.regions) >= 226


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
