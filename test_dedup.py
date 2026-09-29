import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dedup import find_new_reviews, normalize_content, parse_naver_date


def test_all_new_when_existing_empty():
    incoming = [{"channel": "네이버", "content": "좋아요"}, {"channel": "카카오맵", "content": "별로예요"}]
    result = find_new_reviews([], incoming)
    assert result == incoming
    print("PASS: test_all_new_when_existing_empty")


def test_excludes_existing_by_channel_and_content_only():
    existing = [{"channel": "네이버", "content": "좋아요", "author": "홍길동", "date": "2026-08-01"}]
    incoming = [{"channel": "네이버", "content": "좋아요", "author": "이**", "date": "2026-09-01"}]
    # author/date가 달라도 (channel, content)가 같으면 기존 리뷰로 판정해야 한다
    # (2026-09-11 실제 겪은 버그: 마스킹된 작성자명 불일치로 중복 적재됨)
    result = find_new_reviews(existing, incoming)
    assert result == [], f"실제: {result}"
    print("PASS: test_excludes_existing_by_channel_and_content_only")


def test_different_channel_same_content_is_new():
    existing = [{"channel": "네이버", "content": "좋아요"}]
    incoming = [{"channel": "카카오맵", "content": "좋아요"}]
    result = find_new_reviews(existing, incoming)
    assert result == incoming
    print("PASS: test_different_channel_same_content_is_new")


def test_duplicate_within_same_batch_kept_once():
    incoming = [
        {"channel": "네이버", "content": "좋아요"},
        {"channel": "네이버", "content": "좋아요"},
    ]
    result = find_new_reviews([], incoming)
    assert len(result) == 1, f"실제: {len(result)}"
    print("PASS: test_duplicate_within_same_batch_kept_once")


NOW = "2026-09-29T13:00:00+09:00"


def _naver(content, date, collected_at=None):
    r = {"channel": "네이버", "content": content, "date": date}
    if collected_at is not None:
        r["collected_at"] = collected_at
    return r


def test_normalize_content_collapses_whitespace():
    assert normalize_content("  친절해요\n또  올게요 ") == "친절해요 또 올게요"
    assert normalize_content(None) == ""
    print("PASS: test_normalize_content_collapses_whitespace")


def test_parse_naver_date_formats():
    assert parse_naver_date("23.3.6.월", NOW) == "2023-03-06"
    assert parse_naver_date("9.16.수", NOW) == "2026-09-16"
    print("PASS: test_parse_naver_date_formats")


def test_parse_naver_date_year_rollover():
    # 1월에 수집한 "12.30.월"은 전년도 리뷰
    assert parse_naver_date("12.30.월", "2027-01-03T13:00:00+09:00") == "2026-12-30"
    print("PASS: test_parse_naver_date_year_rollover")


def test_parse_naver_date_invalid_returns_none():
    for value in ["", None, "3일 전", "2026-09-16", "2.30.화", "25.2.29.토"]:
        assert parse_naver_date(value, NOW) is None, f"{value!r}"
    assert parse_naver_date("9.16.수", "") is None      # 기준 시점 없으면 연도 추론 불가
    assert parse_naver_date("9.16.수", "깨진값") is None
    assert parse_naver_date("23.3.6.월", "") == "2023-03-06"  # 연도가 있으면 기준 불필요
    print("PASS: test_parse_naver_date_invalid_returns_none")


def test_naver_same_content_different_date_is_new():
    # 2026-09-29 실측: comp_midream "좋아요" 22.10.5 / 22.5.8은 서로 다른 리뷰
    existing = [_naver("좋아요", "22.10.5.수", NOW)]
    incoming = [_naver("좋아요 ", "22.5.8.일")]
    assert find_new_reviews(existing, incoming, NOW) == incoming
    print("PASS: test_naver_same_content_different_date_is_new")


def test_naver_whitespace_variant_same_date_is_duplicate():
    existing = [_naver("친절해요\n또 올게요", "9.16.수", NOW)]
    incoming = [_naver("친절해요 또  올게요", "9.16.수")]
    assert find_new_reviews(existing, incoming, NOW) == []
    print("PASS: test_naver_whitespace_variant_same_date_is_duplicate")


def test_naver_date_known_on_one_side_only_is_duplicate():
    existing = [_naver("좋았어요", "9.16.수", NOW)]
    assert find_new_reviews(existing, [_naver("좋았어요", "")], NOW) == []
    existing = [_naver("좋았어요", "", NOW)]
    assert find_new_reviews(existing, [_naver("좋았어요", "9.16.수")], NOW) == []
    print("PASS: test_naver_date_known_on_one_side_only_is_duplicate")


def test_existing_row_without_collected_at_falls_back_to_content():
    existing = [_naver("좋았어요", "9.16.수")]  # collected_at 키 없음
    assert find_new_reviews(existing, [_naver("좋았어요", "9.20.일")], NOW) == []
    print("PASS: test_existing_row_without_collected_at_falls_back_to_content")


def test_naver_same_batch_same_date_kept_once_different_date_both_kept():
    incoming = [_naver("굿", "9.16.수"), _naver("굿 ", "9.16.수"), _naver("굿", "9.17.목")]
    result = find_new_reviews([], incoming, NOW)
    assert [r["date"] for r in result] == ["9.16.수", "9.17.목"], f"실제: {result}"
    print("PASS: test_naver_same_batch_same_date_kept_once_different_date_both_kept")


def test_kakao_still_exact_content_only():
    existing = [{"channel": "카카오맵", "content": "좋아요", "date": "3일 전", "collected_at": NOW}]
    assert find_new_reviews(existing, [{"channel": "카카오맵", "content": "좋아요", "date": "1주 전"}], NOW) == []
    assert len(find_new_reviews(existing, [{"channel": "카카오맵", "content": "좋아요 ", "date": ""}], NOW)) == 1
    print("PASS: test_kakao_still_exact_content_only")


if __name__ == "__main__":
    test_all_new_when_existing_empty()
    test_excludes_existing_by_channel_and_content_only()
    test_different_channel_same_content_is_new()
    test_duplicate_within_same_batch_kept_once()
    test_normalize_content_collapses_whitespace()
    test_parse_naver_date_formats()
    test_parse_naver_date_year_rollover()
    test_parse_naver_date_invalid_returns_none()
    test_naver_same_content_different_date_is_new()
    test_naver_whitespace_variant_same_date_is_duplicate()
    test_naver_date_known_on_one_side_only_is_duplicate()
    test_existing_row_without_collected_at_falls_back_to_content()
    test_naver_same_batch_same_date_kept_once_different_date_both_kept()
    test_kakao_still_exact_content_only()
