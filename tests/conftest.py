import json
from pathlib import Path

import pytest

from lawsearch.models import Region
from lawsearch.regions import RegionRegistry


def load_fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8"))


@pytest.fixture(name="load_fixture")
def load_fixture_fixture():
    return load_fixture


@pytest.fixture
def pyeongtaek() -> Region:
    resolution = RegionRegistry.from_package_data().resolve("평택")
    assert resolution.region is not None
    return resolution.region
