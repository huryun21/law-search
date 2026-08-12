import argparse
import csv
import io
import json
import zipfile
from datetime import date
from pathlib import Path


SOURCE_URL = "https://code.go.kr/stdcode/orgCodeL.do"
LAW_API_URL = "https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=ordinListGuide"
INTEGRATION_LAW_URL = "https://www.law.go.kr/lsInfoP.do?lsiSeq=284111"
INCHEON_REORGANIZATION_LAW_URL = "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=281877"
INCHEON_ORIGINAL_LAW_URL = "https://www.law.go.kr/lsInfoP.do?lsiSeq=259479"
INCHEON_RENAME_LAW_URL = "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=286453"
PROVINCES = {
    "서울특별시": ("6110000", ("서울",)),
    "부산광역시": ("6260000", ("부산",)),
    "대구광역시": ("6270000", ("대구",)),
    "인천광역시": ("6280000", ("인천",)),
    "전남광주통합특별시": (
        "6130000",
        ("전남광주", "광주특별시", "광주광역시", "전라남도", "광주", "전남"),
    ),
    "대전광역시": ("6300000", ("대전",)),
    "울산광역시": ("6310000", ("울산",)),
    "세종특별자치시": ("5690000", ("세종",)),
    "경기도": ("6410000", ("경기",)),
    "강원특별자치도": ("6530000", ("강원",)),
    "충청북도": ("6430000", ("충북",)),
    "충청남도": ("6440000", ("충남",)),
    "전북특별자치도": ("6540000", ("전북",)),
    "경상북도": ("6470000", ("경북",)),
    "경상남도": ("6480000", ("경남",)),
    "제주특별자치도": ("6500000", ("제주",)),
}
SPECIAL_MUNICIPALITIES = {"6510000", "6520000"}
FORMER_GWANGJU_CODES = {"5805000", "5810000", "5815000", "5820000", "5825000"}
INCHEON_LEGACY_ALIASES = {
    "3491000": ("인천/중구", "인천광역시/중구", "인천광역시 중구", "중구"),
    "3501000": (
        "인천/중구",
        "인천광역시/중구",
        "인천광역시 중구",
        "중구",
        "인천/동구",
        "인천광역시/동구",
        "인천광역시 동구",
        "동구",
    ),
    "3561000": ("인천/서구", "인천광역시/서구", "인천광역시 서구", "서구"),
    "3565000": ("인천/서구", "인천광역시/서구", "인천광역시 서구", "서구"),
}
AFFECTED_ORGS = {"6130000"}
AFFECTED_CODE_PAIRS = {
    ("6280000", "3491000"),
    ("6280000", "3501000"),
    ("6280000", "3561000"),
    ("6280000", "3565000"),
}


def _open_export(path: Path):
    if zipfile.is_zipfile(path):
        archive = zipfile.ZipFile(path)
        name = next(name for name in archive.namelist() if "유형분류" in name)
        return archive, io.TextIOWrapper(archive.open(name), encoding="cp949", newline="")
    return None, path.open(encoding="cp949", newline="")


def _municipality_aliases(
    province_name: str,
    province_aliases: tuple[str, ...],
    municipality: str,
    sborg: str,
) -> list[str]:
    short_name = municipality[:-1] if municipality[-1:] in {"시", "군", "구"} else municipality
    prefixes = list(province_aliases)
    if province_name == "전남광주통합특별시":
        prefixes = ["전남광주"]
        prefixes += ["광주", "광주광역시"] if sborg in FORMER_GWANGJU_CODES else ["전남", "전라남도"]
    aliases = [f"{province_name}/{municipality}", f"{province_name} {municipality}"]
    aliases += [value for prefix in prefixes for value in (f"{prefix}/{municipality}", f"{prefix}/{short_name}")]
    aliases += INCHEON_LEGACY_ALIASES.get(sborg, ())
    return list(dict.fromkeys(aliases))


def _load_verification(path: Path | None) -> tuple[set[tuple[str, str | None]], dict | None]:
    if path is None:
        return set(), None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("source_url") != "https://www.law.go.kr/DRF/lawSearch.do":
        raise ValueError("verification artifact must cite the official law API endpoint")
    if not payload.get("verified_on"):
        raise ValueError("verification artifact is missing verified_on")
    verified = set()
    for item in payload.get("verified_codes", []):
        pair = (item.get("org"), item.get("sborg"))
        if not pair[0] or len(pair[0]) != 7 or not pair[0].isdigit():
            raise ValueError(f"invalid verification org code: {pair[0]}")
        if pair[1] is not None and (len(pair[1]) != 7 or not pair[1].isdigit()):
            raise ValueError(f"invalid verification sborg code: {pair[1]}")
        if pair in verified:
            raise ValueError(f"duplicate verification code: {pair[0]}/{pair[1]}")
        verified.add(pair)
    return verified, payload


def build(
    export_path: Path,
    output_path: Path,
    retrieved_on: str,
    verification_path: Path | None = None,
) -> None:
    archive, stream = _open_export(export_path)
    try:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    finally:
        stream.close()
        if archive:
            archive.close()

    by_name = {row["전체기관명"]: row for row in rows}
    regions = []
    pairs = set()
    for province_name, (org, province_aliases) in PROVINCES.items():
        province = by_name.get(province_name)
        if not province or province["기관코드"] != org:
            raise ValueError(f"missing province code: {province_name}")
        regions.append({"province_name": province_name, "municipality_name": None, "org": org, "sborg": None, "aliases": list(province_aliases)})
        for row in rows:
            sborg = row["기관코드"]
            is_municipality = row["유형분류_중_의미"] == "기초자치단체" or sborg in SPECIAL_MUNICIPALITIES
            if row["최상위기관코드"] != org or row["차수"] != "2" or row["대표기관코드"] != sborg or not is_municipality:
                continue
            if row["존폐여부"] != "0":
                continue
            if len(org) != 7 or not org.isdigit() or len(sborg) != 7 or not sborg.isdigit():
                raise ValueError(f"invalid seven-digit code: {org}/{sborg}")
            pair = (org, sborg)
            if pair in pairs:
                raise ValueError(f"duplicate code pair: {org}/{sborg}")
            pairs.add(pair)
            municipality = row["최하위기관명"]
            aliases = _municipality_aliases(province_name, province_aliases, municipality, sborg)
            regions.append({"province_name": province_name, "municipality_name": municipality, "org": org, "sborg": sborg, "aliases": aliases})

    regions.sort(key=lambda item: (item["province_name"], item["municipality_name"] or ""))
    verified_codes, verification = _load_verification(verification_path)
    affected_codes = {
        (item["org"], item["sborg"])
        for item in regions
        if item["org"] in AFFECTED_ORGS or (item["org"], item["sborg"]) in AFFECTED_CODE_PAIRS
    }
    unverified_codes = sorted(affected_codes - verified_codes, key=lambda pair: (pair[0], pair[1] or ""))
    payload = {
        "metadata": {
            "source_url": SOURCE_URL,
            "law_api_url": LAW_API_URL,
            "retrieved_on": retrieved_on,
            "effective_on": "2026-07-01",
            "legal_sources": [
                {"url": INTEGRATION_LAW_URL, "law_number": "21446", "effective_on": "2026-07-01"},
                {"url": INCHEON_REORGANIZATION_LAW_URL, "law_number": "21247", "effective_on": "2026-07-01"},
                {"url": INCHEON_ORIGINAL_LAW_URL, "law_number": "20161", "effective_on": "2026-07-01", "role": "original_enactment"},
                {"url": INCHEON_RENAME_LAW_URL, "law_number": "21734", "effective_on": "2026-07-01"},
            ],
            "api_compatibility": {
                "status": "verified" if not unverified_codes else "unverified",
                "verified_on": verification.get("verified_on") if verification else None,
                "verification_artifact": verification_path.as_posix() if verification_path else None,
                "verification_source_url": verification.get("source_url") if verification else None,
                "unverified_codes": [
                    {"org": org, "sborg": sborg} for org, sborg in unverified_codes
                ],
                "fallback": "unverified codes resolve as candidates and are never promoted to a searchable region",
            },
        },
        "regions": regions,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("export_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--retrieved-on", default=date.today().isoformat())
    parser.add_argument("--verification-path", type=Path)
    args = parser.parse_args()
    build(args.export_path, args.output_path, args.retrieved_on, args.verification_path)


if __name__ == "__main__":
    main()
