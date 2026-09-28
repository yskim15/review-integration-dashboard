"""네이버 리뷰 수집 크롬 확장("PEI 네이버 리뷰 수집(내부용)") 연동 브리지 (로컬 실행 전용).

`main.py`(GitHub Actions, 네이버 GraphQL 자동 수집)는 그대로 두고 병행한다
(2026-09-28 사용자 결정). 자동 수집이 차단·실패한 병원을, 담당자가 자기 브라우저에서
확장으로 수집한 엑셀로 보완하는 경로다. 확장은 사용자가 직접 연 탭에서 동작하고
캡차도 사람이 직접 푼다 — 자동화 흔적 은폐가 없다(확장 content.js 주석·코드로 확인).

    python naver_extension_bridge.py export-targets
        → naver_extension_work/step2_targets.json 생성
          (확장 batch.html "여러 병원 자동 수집"에서 불러오는 입력 파일)
    확장으로 수집 → 다운로드 폴더에 네이버리뷰수집_<병원명>_<YYYYMMDD>.xlsx 생성
    python naver_extension_bridge.py import <xlsx 파일 또는 폴더...>          # 미리보기(dry-run)
    python naver_extension_bridge.py import <xlsx 파일 또는 폴더...> --apply  # 시트 반영

import --apply는 main.py와 같은 흐름(중복 제거 → 규칙기반 분류 → Sheets append)을
탄다. `GOOGLE_SHEET_ID`/`GCP_SA_KEY` 환경변수가 필요하다(reclassify.py와 동일).

확장 엑셀에는 작성자·사장님 답글 여부가 없다 — author는 빈 값(프론트가 "익명"으로 표시),
has_reply는 빈 값(모름)으로 적는다. 추정해서 채우지 않는다.
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

import dedup
import sheets_writer
from classifier.rule_based import classify

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "naver_extension_work"
HOSPITALS_CONFIG = BASE_DIR / "config" / "hospitals_config.json"
COMPETITORS_CONFIG = BASE_DIR / "config" / "competitors_config.json"

# 확장 background.js 파일명 규칙: `네이버리뷰수집${_병원명}_${YYYYMMDD}.xlsx`
# (병원명의 \/:*?"<>| 는 _로 치환됨). 브라우저가 중복 다운로드에 붙이는 " (1)"도 허용.
FILENAME_RE = re.compile(r"^네이버리뷰수집_(?P<name>.+)_(?P<stamp>\d{8})(?: \(\d+\))?\.xlsx$")
EXPECTED_HEADER = ["플랫폼", "작성일(원문)", "작성일", "리뷰내용"]
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')
_NON_PLACE_URL_MARKERS = ("booking.naver.com", "naver.me/")


def _load_entities():
    """자사+경쟁 병원을 [{hospital_id, name, naver_place_url}]로 반환한다."""
    with open(HOSPITALS_CONFIG, encoding="utf-8") as f:
        hospitals = json.load(f)["hospitals"]
    entities = [{"hospital_id": h["hospital_id"], "name": h["hospital_name"],
                 "naver_place_url": h["channels"].get("naver_place_url", "")} for h in hospitals]
    if COMPETITORS_CONFIG.exists():
        with open(COMPETITORS_CONFIG, encoding="utf-8") as f:
            competitors = json.load(f).get("competitors", [])
        entities += [{"hospital_id": c["competitor_id"], "name": c["name"],
                      "naver_place_url": c["channels"].get("naver_place_url", "")} for c in competitors]
    return entities


def safe_name(name):
    """확장이 파일명에 넣는 병원명과 같은 규칙으로 치환한다."""
    return _UNSAFE_CHARS.sub("_", name)


def build_targets(entities):
    """확장 lib/queueBuilder.js가 읽는 step2_targets.json 형식을 만든다.
    플레이스 URL이 있는 병원만 넣는다(빈 값·예약·단축 URL은 확장도 수집 못 함)."""
    targets, skipped = [], []
    for e in entities:
        url = e["naver_place_url"]
        if not url or any(m in url for m in _NON_PLACE_URL_MARKERS):
            skipped.append(e["name"])
            continue
        targets.append({"name": e["name"], "status": "active", "urls": [url]})
    return {"targets": targets}, skipped


def name_to_id_map(entities):
    """파일명 속 병원명 → hospital_id. 치환 후 이름이 겹치면 오매핑 위험이라 에러."""
    mapping = {}
    for e in entities:
        key = safe_name(e["name"])
        if key in mapping:
            raise ValueError(f"파일명 기준 병원명이 겹칩니다: {key!r} ({mapping[key]}, {e['hospital_id']})")
        mapping[key] = e["hospital_id"]
    return mapping


def normalize_content(text):
    """GraphQL 본문과 확장이 DOM에서 읽은 본문은 줄바꿈·공백이 다를 수 있다 — 비교용 정규화."""
    return re.sub(r"\s+", " ", text or "").strip()


def rows_to_reviews(rows):
    """엑셀 행(헤더 포함) → 수집기와 같은 리뷰 dict 목록. 헤더가 다르면 에러."""
    if not rows or list(rows[0][:4]) != EXPECTED_HEADER:
        raise ValueError(f"확장 엑셀 헤더가 예상과 다릅니다: {list(rows[0][:4]) if rows else '빈 파일'}")
    reviews = []
    for row in rows[1:]:
        platform, date_raw, _date_iso, content = (list(row) + [None] * 4)[:4]
        content = (content or "").strip()
        if platform != "네이버" or not content:
            continue
        reviews.append({"channel": "네이버", "author": "", "rating": None,
                        "date": date_raw or "", "content": content, "has_reply": None})
    return reviews


def select_new(existing_for_hospital, reviews):
    """이미 시트에 있는 리뷰(정규화 본문 기준)를 빼고, 파일 안 중복도 1건만 남긴다."""
    seen = {normalize_content(r.get("content")) for r in existing_for_hospital if r.get("channel") == "네이버"}
    fresh = [r for r in reviews if normalize_content(r["content"]) not in seen]
    # 같은 파일 안 완전 중복은 기존 dedup 규칙(channel, content)으로 한 번 더 거른다
    unique, keys = [], set()
    for r in dedup.find_new_reviews([], fresh):
        k = normalize_content(r["content"])
        if k not in keys:
            keys.add(k)
            unique.append(r)
    return unique


def _read_xlsx(path):
    import openpyxl  # 로컬 전용 의존성(Actions의 requirements.txt에는 넣지 않음)

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()


def _collect_files(paths):
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(x for x in p.iterdir() if FILENAME_RE.match(x.name))
        else:
            files.append(p)
    return files


def cmd_export_targets():
    targets, skipped = build_targets(_load_entities())
    WORK_DIR.mkdir(exist_ok=True)
    out = WORK_DIR / "step2_targets.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(targets, f, ensure_ascii=False, indent=2)
    print(f"{len(targets['targets'])}곳 대상 파일 생성: {out}")
    if skipped:
        print(f"네이버 플레이스 URL이 없어 제외한 {len(skipped)}곳: {', '.join(skipped)}")
    return 0


def cmd_import(paths, apply):
    mapping = name_to_id_map(_load_entities())
    plan, problems = [], []
    for path in _collect_files(paths):
        m = FILENAME_RE.match(path.name)
        if not m:
            problems.append(f"{path.name}: 확장 파일명 형식이 아님")
            continue
        hospital_id = mapping.get(m.group("name"))
        if not hospital_id:
            problems.append(f"{path.name}: 등록된 병원명과 일치하지 않음({m.group('name')!r})")
            continue
        try:
            reviews = rows_to_reviews(_read_xlsx(path))
        except Exception as e:  # noqa: BLE001 - 한 파일 문제로 나머지를 막지 않는다
            problems.append(f"{path.name}: 읽기 실패 - {e}")
            continue
        plan.append((path, hospital_id, reviews))

    for msg in problems:
        print(f"[건너뜀] {msg}")
    if not plan:
        print("가져올 파일이 없습니다.")
        return 1 if problems else 0

    worksheet = existing = None
    if apply:
        worksheet = sheets_writer.connect(os.environ["GOOGLE_SHEET_ID"], os.environ["GCP_SA_KEY"])
        sheets_writer.ensure_header(worksheet)
        existing = sheets_writer.read_existing_reviews(worksheet)
    collected_at = datetime.datetime.now().astimezone().isoformat()

    total = 0
    for path, hospital_id, reviews in plan:
        if not apply:
            print(f"- {path.name} -> {hospital_id}: 리뷰 {len(reviews)}건 (시트 중복 여부는 --apply 때 확인)")
            continue
        new = select_new([r for r in existing if r.get("hospital_id") == hospital_id], reviews)
        rows = []
        for review in new:
            row = sheets_writer.review_to_row(hospital_id, review, classify(review), collected_at)
            row[sheets_writer.HEADER.index("has_reply")] = ""  # 확장 엑셀엔 답글 정보가 없음(모름)
            rows.append(row)
        if rows:
            worksheet.append_rows(rows, value_input_option="RAW")
        total += len(rows)
        print(f"- {path.name} -> {hospital_id}: 파일 {len(reviews)}건 중 신규 {len(rows)}건 반영")
    if apply:
        print(f"총 {total}건 반영 완료.")
    else:
        print("dry-run입니다. 확인 후 --apply로 시트에 반영하세요.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="네이버 리뷰 크롬 확장 연동")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export-targets", help="확장 일괄 수집용 step2_targets.json 생성")
    p_import = sub.add_parser("import", help="확장이 내려받은 엑셀을 시트에 반영")
    p_import.add_argument("paths", nargs="+", help="xlsx 파일 또는 폴더(다운로드 폴더 등)")
    p_import.add_argument("--apply", action="store_true", help="실제로 시트에 반영")
    args = parser.parse_args()
    if args.cmd == "export-targets":
        return cmd_export_targets()
    return cmd_import(args.paths, args.apply)


if __name__ == "__main__":
    sys.exit(main())
