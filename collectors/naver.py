"""네이버 스마트플레이스 리뷰 수집기.

"리뷰 통합 관리 html/backend/collectors/naver.py"(2026-09-09/09-11 실측
검증됨)에서 이식. light_ping()은 이 프로젝트에 실시간 알림이 없어(설계문서
확정사항) 제거했다. 나머지 로직(GraphQL 우선 → Apollo state → HTML 셀렉터
3단 폴백, 차단 시 명시적 NaverBlockedError)은 그대로 유지한다.
"""

import json
import re

import requests
from bs4 import BeautifulSoup

from collectors.base import polite_sleep

MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Referer": "https://m.place.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

GRAPHQL_HEADERS = dict(MOBILE_HEADERS, **{"Content-Type": "application/json", "Accept": "*/*", "Origin": "https://m.place.naver.com"})

GRAPHQL_URL = "https://pcmap-api.place.naver.com/graphql"

_VISITOR_REVIEWS_QUERY = """
query getVisitorReviews($input: VisitorReviewsInput) {
  visitorReviews(input: $input) {
    items {
      id
      rating
      body
      created
      visitCount
      author { nickname }
      reply { body }
    }
    total
  }
}
"""


class NaverBlockedError(Exception):
    """네이버가 자동화 요청으로 감지해 차단했을 때, 또는 businessId를 추출하지
    못했을 때 발생한다. 이 예외를 우회하지 않는다 — 수동 입력으로 대체한다."""


def _extract_place_id(naver_place_url):
    """URL 경로에서 숫자로만 된 첫 세그먼트를 businessId로 뽑는다.
    (업종별 세그먼트명이 "hospital"/"beauty" 등으로 달라도 안전하게 동작)"""
    parts = [p for p in naver_place_url.split("/") if p]
    for p in parts:
        if p.isdigit():
            return p
    return None


_BLOCK_MARKERS = ("captcha", "자동화된 요청", "비정상적인 접근", "unusual traffic", "차단")


def _looks_blocked(resp):
    if resp.status_code in (401, 403, 429):
        return True
    body_head = resp.text[:3000].lower()
    return any(marker.lower() in body_head for marker in _BLOCK_MARKERS)


def _via_graphql(place_id, page=1, display=30):
    headers = dict(GRAPHQL_HEADERS, Referer=f"https://m.place.naver.com/hospital/{place_id}/review/visitor")
    body = [{
        "operationName": "getVisitorReviews",
        "variables": {"input": {"businessId": str(place_id), "businessType": "hospital", "page": page, "display": display}},
        "query": _VISITOR_REVIEWS_QUERY,
    }]
    resp = requests.post(GRAPHQL_URL, headers=headers, json=body, timeout=15)
    if _looks_blocked(resp):
        return None, f"graphql status={resp.status_code} (차단/캡차로 추정)"
    try:
        data = resp.json()
    except ValueError:
        return None, "graphql 응답이 JSON이 아님 (쿼리 스키마가 실제와 다를 수 있음)"

    try:
        items = data[0]["data"]["visitorReviews"]["items"]
    except (KeyError, IndexError, TypeError):
        return None, f"graphql 응답 구조가 예상과 다름: {json.dumps(data, ensure_ascii=False)[:300]}"

    reviews = [
        {
            "channel": "네이버",
            "author": (item.get("author") or {}).get("nickname", "익명"),
            "rating": item.get("rating"),
            "date": item.get("created"),
            "content": item.get("body", ""),
            "has_reply": bool(item.get("reply") and item["reply"].get("body")),
        }
        for item in items
    ]
    return reviews, None


_APOLLO_STATE_RE = re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)


def _via_embedded_state(review_page_url):
    resp = requests.get(review_page_url, headers=MOBILE_HEADERS, timeout=15)
    if _looks_blocked(resp):
        return None, f"페이지 status={resp.status_code} (차단/캡차로 추정)"

    m = _APOLLO_STATE_RE.search(resp.text)
    if not m:
        return None, "__APOLLO_STATE__ 를 찾지 못함"
    try:
        state = json.loads(m.group(1))
    except ValueError:
        return None, "__APOLLO_STATE__ JSON 파싱 실패"

    review_entries = [v for k, v in state.items() if isinstance(v, dict) and "VisitorReview" in k]
    if not review_entries:
        return None, "__APOLLO_STATE__ 안에 리뷰 데이터 없음"

    reviews = [
        {
            "channel": "네이버",
            "author": ((entry.get("author") or {}).get("nickname", "익명")),
            "rating": entry.get("rating"),
            "date": entry.get("created"),
            "content": entry.get("body", ""),
        }
        for entry in review_entries
    ]
    return reviews, None


SELECTORS = {
    "review_card": "li.place_apply_pui",
    "author": ".pui__NMi-Dp",
    "date": ".pui__gfuUIT time",
    "content": ".pui__vn15t2",
}


def _via_html_selectors(review_page_url):
    resp = requests.get(review_page_url, headers=MOBILE_HEADERS, timeout=15)
    if _looks_blocked(resp):
        return None, f"페이지 status={resp.status_code} (차단/캡차로 추정)"
    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select(SELECTORS["review_card"])
    if not cards:
        return None, "CSS 셀렉터로 리뷰 카드를 찾지 못함 (구조 변경 또는 SPA 렌더링)"
    reviews = []
    for c in cards:
        author_el = c.select_one(SELECTORS["author"])
        date_el = c.select_one(SELECTORS["date"])
        content_el = c.select_one(SELECTORS["content"])
        reviews.append({
            "channel": "네이버",
            "author": author_el.get_text(strip=True) if author_el else "익명",
            "rating": None,
            "date": date_el.get_text(strip=True) if date_el else None,
            "content": content_el.get_text(strip=True) if content_el else "",
        })
    return reviews, None


def collect_full(hospital):
    place_id = _extract_place_id(hospital["channels"]["naver_place_url"])
    if not place_id:
        raise NaverBlockedError(
            f"naver_place_url에서 businessId(숫자)를 추출하지 못했습니다: "
            f"{hospital['channels']['naver_place_url']!r}"
        )
    review_page_url = hospital["channels"]["naver_place_url"]
    polite_sleep()

    failures = []

    reviews, err = _via_graphql(place_id)
    if reviews is not None:
        return reviews
    failures.append(f"graphql: {err}")

    reviews, err = _via_embedded_state(review_page_url)
    if reviews is not None:
        return reviews
    failures.append(f"embedded_state: {err}")

    reviews, err = _via_html_selectors(review_page_url)
    if reviews is not None:
        return reviews
    failures.append(f"html_selectors: {err}")

    raise NaverBlockedError(
        "네이버 리뷰 수집 3가지 방법이 모두 실패했습니다 — " + " / ".join(failures) +
        ". 수동 입력이 필요합니다."
    )
