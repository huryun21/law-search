import csv
import json

import pytest

from scripts import build_regions


FIELDS = [
    "기관코드",
    "전체기관명",
    "최하위기관명",
    "차수",
    "최상위기관코드",
    "대표기관코드",
    "유형분류_중_의미",
    "존폐여부",
]


def _write_export(path, rows):
    with path.open("w", encoding="cp949", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _row(code, name, *, municipality=False, current=True):
    return {
        "기관코드": code,
        "전체기관명": f"테스트도 {name}" if municipality else name,
        "최하위기관명": name,
        "차수": "2" if municipality else "1",
        "최상위기관코드": "6130000",
        "대표기관코드": code,
        "유형분류_중_의미": "기초자치단체" if municipality else "광역자치단체",
        "존폐여부": "0" if current else "1",
    }


@pytest.fixture
def one_province(monkeypatch):
    monkeypatch.setattr(build_regions, "PROVINCES", {"테스트도": ("6130000", ("테스트",))})


def test_generator_defaults_affected_codes_to_unverified(tmp_path, one_province):
    source = tmp_path / "regions.tsv"
    output = tmp_path / "regions.json"
    _write_export(source, [_row("6130000", "테스트도"), _row("5805000", "동구", municipality=True)])

    build_regions.build(source, output, "2026-08-12")

    compatibility = json.loads(output.read_text(encoding="utf-8"))["metadata"]["api_compatibility"]
    assert compatibility["status"] == "unverified"
    assert compatibility["unverified_codes"] == [
        {"org": "6130000", "sborg": None},
        {"org": "6130000", "sborg": "5805000"},
    ]


def test_generator_uses_explicit_verification_artifact(tmp_path, one_province):
    source = tmp_path / "regions.tsv"
    output = tmp_path / "regions.json"
    verification = tmp_path / "verification.json"
    _write_export(source, [_row("6130000", "테스트도"), _row("5805000", "동구", municipality=True)])
    verification.write_text(
        json.dumps(
            {
                "source_url": "https://www.law.go.kr/DRF/lawSearch.do",
                "verified_on": "2026-08-12",
                "verified_codes": [
                    {"org": "6130000", "sborg": None},
                    {"org": "6130000", "sborg": "5805000"},
                ],
            }
        ),
        encoding="utf-8",
    )

    build_regions.build(source, output, "2026-08-12", verification)

    compatibility = json.loads(output.read_text(encoding="utf-8"))["metadata"]["api_compatibility"]
    assert compatibility["status"] == "verified"
    assert compatibility["verification_artifact"] == verification.as_posix()
    assert compatibility["unverified_codes"] == []
    legal_sources = json.loads(output.read_text(encoding="utf-8"))["metadata"]["legal_sources"]
    assert any(
        item["law_number"] == "21247" and "lsiSeq=281877" in item["url"]
        for item in legal_sources
    )


def test_generator_is_deterministic_and_excludes_abolished_rows(tmp_path, one_province):
    source = tmp_path / "regions.tsv"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write_export(
        source,
        [
            _row("6130000", "테스트도"),
            _row("5805000", "동구", municipality=True),
            _row("5806000", "옛구", municipality=True, current=False),
        ],
    )

    build_regions.build(source, first, "2026-08-12")
    build_regions.build(source, second, "2026-08-12")

    assert first.read_bytes() == second.read_bytes()
    assert "옛구" not in first.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_code", ["", "123", "abcdefg", "12345678"])
def test_generator_rejects_malformed_codes(tmp_path, one_province, bad_code):
    source = tmp_path / "regions.tsv"
    output = tmp_path / "regions.json"
    _write_export(source, [_row("6130000", "테스트도"), _row(bad_code, "동구", municipality=True)])

    with pytest.raises(ValueError, match="seven-digit"):
        build_regions.build(source, output, "2026-08-12")


def test_generator_rejects_duplicate_code_pairs(tmp_path, one_province):
    source = tmp_path / "regions.tsv"
    output = tmp_path / "regions.json"
    municipality = _row("5805000", "동구", municipality=True)
    _write_export(source, [_row("6130000", "테스트도"), municipality, municipality])

    with pytest.raises(ValueError, match="duplicate"):
        build_regions.build(source, output, "2026-08-12")
