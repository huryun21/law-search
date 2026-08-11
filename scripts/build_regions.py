import argparse
import csv
import io
import json
import zipfile
from datetime import date
from pathlib import Path


SOURCE_URL = "https://code.go.kr/stdcode/orgCodeL.do"
LAW_API_URL = "https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=ordinListGuide"
PROVINCES = {
    "서울특별시": ("6110000", ("서울",)),
    "부산광역시": ("6260000", ("부산",)),
    "대구광역시": ("6270000", ("대구",)),
    "인천광역시": ("6280000", ("인천",)),
    "광주광역시": ("6290000", ("광주",)),
    "대전광역시": ("6300000", ("대전",)),
    "울산광역시": ("6310000", ("울산",)),
    "세종특별자치시": ("5690000", ("세종",)),
    "경기도": ("6410000", ("경기",)),
    "강원특별자치도": ("6530000", ("강원",)),
    "충청북도": ("6430000", ("충북",)),
    "충청남도": ("6440000", ("충남",)),
    "전북특별자치도": ("6540000", ("전북",)),
    "전라남도": ("6460000", ("전남",)),
    "경상북도": ("6470000", ("경북",)),
    "경상남도": ("6480000", ("경남",)),
    "제주특별자치도": ("6500000", ("제주",)),
}
SPECIAL_MUNICIPALITIES = {"6510000", "6520000"}
PRE_REORGANIZATION = {"6280000", "6290000", "6460000"}


def _open_export(path: Path):
    if zipfile.is_zipfile(path):
        archive = zipfile.ZipFile(path)
        name = next(name for name in archive.namelist() if "유형분류" in name)
        return archive, io.TextIOWrapper(archive.open(name), encoding="cp949", newline="")
    return None, path.open(encoding="cp949", newline="")


def build(export_path: Path, output_path: Path, retrieved_on: str) -> None:
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
            if row["존폐여부"] != "0" and not (org in PRE_REORGANIZATION and row["폐지일자"] == "20260701"):
                continue
            if row["생성일자"] == "20260320":
                continue
            if len(org) != 7 or not org.isdigit() or len(sborg) != 7 or not sborg.isdigit():
                raise ValueError(f"invalid seven-digit code: {org}/{sborg}")
            pair = (org, sborg)
            if pair in pairs:
                raise ValueError(f"duplicate code pair: {org}/{sborg}")
            pairs.add(pair)
            municipality = row["최하위기관명"]
            aliases = [f"{alias}/{municipality[:-1]}" for alias in province_aliases]
            regions.append({"province_name": province_name, "municipality_name": municipality, "org": org, "sborg": sborg, "aliases": aliases})

    regions.sort(key=lambda item: (item["province_name"], item["municipality_name"] or ""))
    payload = {
        "metadata": {
            "source_url": SOURCE_URL,
            "law_api_url": LAW_API_URL,
            "retrieved_on": retrieved_on,
            "selection_note": "17-region law API compatibility set; 2026-07-01 transition rows retained where required",
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
    args = parser.parse_args()
    build(args.export_path, args.output_path, args.retrieved_on)


if __name__ == "__main__":
    main()
