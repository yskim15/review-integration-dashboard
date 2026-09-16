import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from collectors.google import parse_relative_date, _to_review_dict

FIXED_NOW = datetime(2026, 9, 16, 12, 0, 0)


def test_parse_relative_date_months():
    assert parse_relative_date("10개월 전", FIXED_NOW) == "2025-11 (10개월 전)"
    print("PASS: test_parse_relative_date_months")


def test_parse_relative_date_weeks():
    assert parse_relative_date("2주 전", FIXED_NOW) == "2026-09-02 (2주 전)"
    print("PASS: test_parse_relative_date_weeks")


def test_parse_relative_date_yesterday():
    assert parse_relative_date("어제", FIXED_NOW) == "2026-09-15 (어제)"
    print("PASS: test_parse_relative_date_yesterday")


def test_parse_relative_date_years_with_prefix():
    # 구글이 "수정일: 2년 전"처럼 접두어를 붙이는 경우도 처리해야 한다(2026-09-11 실측 버그)
    assert parse_relative_date("수정일: 2년 전", FIXED_NOW) == "2024-09 (수정일: 2년 전)"
    print("PASS: test_parse_relative_date_years_with_prefix")


def test_parse_relative_date_unrecognized_returns_none():
    assert parse_relative_date("알 수 없는 표기", FIXED_NOW) is None
    print("PASS: test_parse_relative_date_unrecognized_returns_none")


def test_to_review_dict():
    raw = {
        "author": "박민수",
        "ratingLabel": "별표 5개",
        "rawDate": "10개월 전",
        "content": "친절하고 좋았어요",
        "hasReply": True,
    }
    result = _to_review_dict(raw)
    assert result["channel"] == "구글"
    assert result["author"] == "박민수"
    assert result["rating"] == 5, f"실제: {result['rating']}"
    assert result["content"] == "친절하고 좋았어요"
    assert result["has_reply"] is True
    print("PASS: test_to_review_dict")


if __name__ == "__main__":
    test_parse_relative_date_months()
    test_parse_relative_date_weeks()
    test_parse_relative_date_yesterday()
    test_parse_relative_date_years_with_prefix()
    test_parse_relative_date_unrecognized_returns_none()
    test_to_review_dict()
