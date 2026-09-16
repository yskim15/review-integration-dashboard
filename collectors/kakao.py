"""카카오맵 리뷰 수집기 (헤드리스 브라우저 렌더링).

"리뷰 통합 관리 html/backend/collectors/kakao.py"(2026-09-11 실측 검증됨)에서
이식. light_ping()은 이 프로젝트에 실시간 알림이 없어 제거했다(카카오는
원래도 브라우저 비용 때문에 light_ping에서 제외돼 있었음).

DOM 셀렉터(2026-09-11 실측, 강남제이스타의원 기준):
    .group_review .list_review > li   리뷰 카드
    .name_user                        작성자 (숨김 span "리뷰어 이름, " 포함 — 제거 필요)
    .starred_grade > span.screen_out  [0]="별점" 라벨, [1]="5.0" 실제 점수
    .review_detail .txt_date          리뷰 작성일
    .wrap_review .desc_review         리뷰 본문
    .info_reply                       있으면 사장님 답글 존재
    a.link_more (텍스트에 "후기" 포함)  리뷰 더 불러오기 버튼
"""

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from collectors.base import polite_sleep

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

MAX_LOAD_MORE_CLICKS = 15


def _extract_place_id(kakao_place_url):
    return kakao_place_url.rstrip("/").split("/")[-1]


def _clean_text(el, drop_selectors=(".screen_out", ".btn_more", ".btn_less")):
    if el is None:
        return ""
    for sel in drop_selectors:
        for child in el.select(sel):
            child.decompose()
    return el.get_text(strip=True)


def _render_review_html(place_url):
    """실제 브라우저 렌더링 — 유닛테스트 대상이 아니다(계획 문서 Task 4 Step 6에서 수동 확인)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR")
            page.goto(place_url, wait_until="networkidle", timeout=30000)
            try:
                page.wait_for_selector("text=후기미제공", timeout=3000)
                return None
            except PlaywrightTimeoutError:
                pass
            page.wait_for_selector(".group_review", timeout=15000)

            for _ in range(MAX_LOAD_MORE_CLICKS):
                clicked = page.evaluate(
                    """() => {
                        const btn = Array.from(document.querySelectorAll('a.link_more'))
                            .find(a => a.textContent.includes('후기'));
                        if (btn) { btn.click(); return true; }
                        return false;
                    }"""
                )
                if not clicked:
                    break
                page.wait_for_timeout(1200)

            page.evaluate(
                "document.querySelectorAll('.btn_more').forEach(el => el.click())"
            )
            page.wait_for_timeout(500)

            return page.content()
        finally:
            browser.close()


def _parse_reviews(html):
    soup = BeautifulSoup(html, "html.parser")
    reviews = []
    for li in soup.select(".group_review .list_review > li"):
        author = _clean_text(li.select_one(".name_user")) or "익명"

        rating = None
        grade_vals = li.select(".starred_grade > span.screen_out")
        if len(grade_vals) >= 2:
            try:
                rating = round(float(grade_vals[1].get_text(strip=True)))
            except ValueError:
                rating = None

        review_detail = li.select_one(".review_detail")
        date_el = (review_detail or li).select_one(".txt_date")
        date = date_el.get_text(strip=True) if date_el else None

        content = _clean_text(li.select_one(".wrap_review .desc_review"))

        reply_block = li.select_one(".info_reply")
        has_reply = reply_block is not None

        reviews.append(
            {
                "channel": "카카오맵",
                "author": author,
                "rating": rating,
                "date": date,
                "content": content,
                "has_reply": has_reply,
            }
        )
    return reviews


def collect_full(hospital):
    """전체 리뷰 수집 (매일 정기 집계용)."""
    place_id = _extract_place_id(hospital["channels"]["kakao_place_url"])
    place_url = f"https://place.map.kakao.com/{place_id}"
    polite_sleep()
    html = _render_review_html(place_url)
    if html is None:
        return []
    return _parse_reviews(html)
