"""naver_extension_bridge.py 테스트 (네트워크·시트 호출 없음, 가상 병원명 사용)."""

import os
import tempfile
from unittest.mock import patch
from pathlib import Path

import openpyxl

import sheets_writer

from naver_extension_bridge import (
    EXPECTED_HEADER, FILENAME_RE, _read_xlsx, build_targets, name_to_id_map,
    cmd_import, rows_to_reviews, safe_name,
)
from test_sheets_writer import FakeWorksheet

ENTITIES = [
    {"hospital_id": "h_a", "name": "가나다의원", "naver_place_url": "https://m.place.naver.com/hospital/111/review/visitor"},
    {"hospital_id": "h_b", "name": "라마피부과", "naver_place_url": ""},
    {"hospital_id": "h_c", "name": "바사의원", "naver_place_url": "https://booking.naver.com/booking/13/bizes/9"},
    {"hospital_id": "h_d", "name": "아자/차의원", "naver_place_url": "https://m.place.naver.com/hospital/222/review/visitor"},
]


def test_build_targets_only_place_urls():
    targets, skipped = build_targets(ENTITIES)
    assert [t["name"] for t in targets["targets"]] == ["가나다의원", "아자/차의원"]
    assert targets["targets"][0] == {"name": "가나다의원", "status": "active",
                                     "urls": ["https://m.place.naver.com/hospital/111/review/visitor"]}
    assert skipped == ["라마피부과", "바사의원"]
    print("PASS: test_build_targets_only_place_urls")


def test_filename_and_name_mapping():
    mapping = name_to_id_map(ENTITIES)
    assert safe_name("아자/차의원") == "아자_차의원" and mapping["아자_차의원"] == "h_d"
    m = FILENAME_RE.match("네이버리뷰수집_아자_차의원_20260928 (1).xlsx")
    assert m and m.group("name") == "아자_차의원" and mapping[m.group("name")] == "h_d"
    assert FILENAME_RE.match("네이버리뷰수집_20260928.xlsx") is None  # 병원명 없는 단일 수동 실행 파일
    assert FILENAME_RE.match("구글리뷰수집_가나다의원_20260928.xlsx") is None
    print("PASS: test_filename_and_name_mapping")


def test_name_collision_raises():
    try:
        name_to_id_map([{"hospital_id": "x", "name": "A/B", "naver_place_url": ""},
                        {"hospital_id": "y", "name": "A_B", "naver_place_url": ""}])
        raised = False
    except ValueError:
        raised = True
    assert raised
    print("PASS: test_name_collision_raises")


def test_rows_to_reviews():
    rows = [EXPECTED_HEADER,
            ["네이버", "9.16.수", "2026-09-16", " 친절해요\n또 올게요 "],
            ["네이버", "9.15.화", "2026-09-15", ""],
            ["구글", "3일 전", "2026-09-25", "다른 플랫폼"]]
    reviews = rows_to_reviews(rows)
    assert reviews == [{"channel": "네이버", "author": "", "rating": None, "date": "9.16.수",
                        "content": "친절해요\n또 올게요", "has_reply": None}]
    try:
        rows_to_reviews([["날짜", "내용"]])
        raised = False
    except ValueError:
        raised = True
    assert raised, "헤더가 다르면 에러여야 함"
    print("PASS: test_rows_to_reviews")


def test_read_xlsx_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "네이버리뷰수집_가나다의원_20260928.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(EXPECTED_HEADER)
        ws.append(["네이버", "9.16.수", "2026-09-16", "좋았어요"])
        wb.save(path)
        rows = _read_xlsx(path)
    assert rows_to_reviews(rows)[0]["content"] == "좋았어요"
    print("PASS: test_read_xlsx_roundtrip")


def _write_extension_xlsx(folder, rows):
    path = Path(folder) / "네이버리뷰수집_가나다의원_20260929.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(EXPECTED_HEADER)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def _existing_row(content, date):
    review = {"channel": "네이버", "author": "홍*", "rating": None, "date": date, "content": content, "has_reply": False}
    classification = {"sentiment": "긍정", "confirmed": True, "score": 2, "matched_words": [], "method": "claude_review"}
    return sheets_writer.review_to_row("h_a", review, classification, "2026-09-28T13:00:00+09:00")


def _run_import(folder, sheet_rows):
    ws = FakeWorksheet(initial_values=[sheets_writer.HEADER] + sheet_rows)
    with patch.dict(os.environ, {"GOOGLE_SHEET_ID": "x", "GCP_SA_KEY": "{}"}), \
         patch("naver_extension_bridge._load_entities", return_value=ENTITIES), \
         patch("naver_extension_bridge.sheets_writer.connect", return_value=ws):
        assert cmd_import([folder], apply=True) == 0
    return ws


def test_import_apply_goes_through_shared_ingest_with_blank_has_reply():
    with tempfile.TemporaryDirectory() as d:
        _write_extension_xlsx(d, [["네이버", "9.16.수", "2026-09-16", "좋았어요"],
                                  ["네이버", "9.17.목", "2026-09-17", "좋았어요"]])  # 같은 글, 다른 날 → 2건
        ws = _run_import(d, [])
    added = ws.values[1:]
    assert [r[sheets_writer.HEADER.index("date")] for r in added] == ["9.16.수", "9.17.목"], f"실제: {added}"
    assert all(r[sheets_writer.HEADER.index("has_reply")] == "" for r in added)
    assert all(r[sheets_writer.HEADER.index("hospital_id")] == "h_a" for r in added)
    print("PASS: test_import_apply_goes_through_shared_ingest_with_blank_has_reply")


def test_import_apply_skips_whitespace_variant_of_existing():
    with tempfile.TemporaryDirectory() as d:
        _write_extension_xlsx(d, [["네이버", "25.9.16.화", "2025-09-16", "친절해요 또 올게요"]])  # 연도 명시: 실행 시점과 무관
        ws = _run_import(d, [_existing_row("친절해요\n또 올게요", "25.9.16.화")])
    assert len(ws.values) == 2, f"신규 0건이어야 함: {ws.values}"
    print("PASS: test_import_apply_skips_whitespace_variant_of_existing")


if __name__ == "__main__":
    test_build_targets_only_place_urls()
    test_filename_and_name_mapping()
    test_name_collision_raises()
    test_rows_to_reviews()
    test_read_xlsx_roundtrip()
    test_import_apply_goes_through_shared_ingest_with_blank_has_reply()
    test_import_apply_skips_whitespace_variant_of_existing()
