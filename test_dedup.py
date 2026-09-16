import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dedup import find_new_reviews


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


if __name__ == "__main__":
    test_all_new_when_existing_empty()
    test_excludes_existing_by_channel_and_content_only()
    test_different_channel_same_content_is_new()
    test_duplicate_within_same_batch_kept_once()
