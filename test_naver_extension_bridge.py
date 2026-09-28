"""naver_extension_bridge.py 테스트 (네트워크·시트 호출 없음, 가상 병원명 사용)."""

import tempfile
from pathlib import Path

import openpyxl

from naver_extension_bridge import (
    EXPECTED_HEADER, FILENAME_RE, _read_xlsx, build_targets, name_to_id_map,
    rows_to_reviews, safe_name, select_new,
)

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


def test_select_new_ignores_whitespace_differences():
    existing = [{"hospital_id": "h_a", "channel": "네이버", "content": "친절해요\n또 올게요"},
                {"hospital_id": "h_a", "channel": "카카오맵", "content": "좋아요"}]
    incoming = [{"channel": "네이버", "content": "친절해요 또 올게요"},   # 시트에 이미 있음(공백만 다름)
                {"channel": "네이버", "content": "좋아요"},              # 카카오에만 있음 → 신규
                {"channel": "네이버", "content": "새 리뷰"},
                {"channel": "네이버", "content": "새  리뷰"}]            # 파일 안 중복
    new = select_new(existing, incoming)
    assert [r["content"] for r in new] == ["좋아요", "새 리뷰"], f"실제: {new}"
    print("PASS: test_select_new_ignores_whitespace_differences")


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


if __name__ == "__main__":
    test_build_targets_only_place_urls()
    test_filename_and_name_mapping()
    test_name_collision_raises()
    test_rows_to_reviews()
    test_select_new_ignores_whitespace_differences()
    test_read_xlsx_roundtrip()
