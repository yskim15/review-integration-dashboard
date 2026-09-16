"""(channel, content) 기준 신규 리뷰 판별.

id나 author/date로 비교하지 않는다 — "리뷰 컨트롤타워" 프로젝트에서 실제
겪은 사고(2026-09-11: 수동입력 리뷰의 마스킹된 작성자명과 자동수집기가
가져온 실명이 달라 중복 적재됨, 카카오 11→22건)를 피하기 위함이다. content는
한 번 작성되면 바뀌지 않고, 서로 다른 리뷰가 완전히 같은 문장일 가능성은
사실상 없으므로 channel+content만으로 충분히 안정적이다.
"""


def find_new_reviews(existing_reviews, incoming_reviews):
    """existing_reviews에 없는 incoming_reviews만 반환한다.
    같은 배치 안에 동일한 (channel, content)가 중복 포함된 경우 첫 건만 남긴다."""
    seen = {(r.get("channel"), r.get("content")) for r in existing_reviews}
    new_reviews = []
    for review in incoming_reviews:
        key = (review.get("channel"), review.get("content"))
        if key in seen:
            continue
        seen.add(key)
        new_reviews.append(review)
    return new_reviews
