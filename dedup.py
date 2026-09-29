"""신규 리뷰 판별 (main.py와 naver_extension_bridge.py 공통, review_ingest를 거쳐 호출).

id나 author로 비교하지 않는다 — "리뷰 컨트롤타워" 프로젝트에서 실제 겪은
사고(2026-09-11: 수동입력 리뷰의 마스킹된 작성자명과 자동수집기가 가져온 실명이
달라 중복 적재됨, 카카오 11→22건)를 피하기 위함이다.

- 카카오맵·구글: (channel, content) 완전 일치. 날짜가 "3일 전" 같은 상대 표기라 키로
  쓰면 매일 달라진다.
- 네이버: (공백 정규화 본문, 작성일). GraphQL 본문과 크롬 확장이 DOM에서 읽은 본문은
  공백·줄바꿈이 다를 수 있고, "좋아요"처럼 짧은 리뷰는 서로 다른 사람이 같은 글자로
  쓴다(2026-09-29 실측: comp_midream "좋아요" 22.10.5/22.5.8은 서로 다른 리뷰). 작성일을
  모르는 쪽이 하나라도 있으면 본문만으로 비교한다 — 키를 (본문, None)으로만 두면 날짜를
  아는 쪽과 키가 달라져 같은 리뷰가 이중 적재된다.
"""

import datetime
import re

_NAVER = "네이버"
_KST = datetime.timezone(datetime.timedelta(hours=9))
# 네이버 작성일 실측 형식: "M.D.요일"(올해) / "YY.M.D.요일"
_NAVER_DATE_RE = re.compile(r"^(?:(\d{2})\.)?(\d{1,2})\.(\d{1,2})\.[가-힣]$")


def normalize_content(text):
    # 시트 get_all_records()는 "5" 같은 본문을 int로 돌려준다 — 문자열로 맞춰 비교한다
    return re.sub(r"\s+", " ", "" if text is None else str(text)).strip()


def _reference_date(collected_at):
    """collected_at의 KST 날짜. 네이버 작성일은 KST인데 Actions는 UTC로 collected_at을 남겨,
    KST 00~09시 수동 실행 때 오늘 리뷰가 '미래'로 보여 전년도로 해석되는 것을 막는다."""
    try:
        moment = datetime.datetime.fromisoformat(str(collected_at or ""))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(_KST)
    return moment.date()


def parse_naver_date(value, collected_at):
    """네이버 작성일 → "YYYY-MM-DD". 연도 없는 형식은 collected_at 기준으로 연도를 붙이고,
    그 결과가 수집일보다 미래면 전년도로 본다. 해석할 수 없으면 None."""
    match = _NAVER_DATE_RE.match(str(value or "").strip())
    if not match:
        return None
    yy, month, day = match.groups()
    try:
        if yy:
            return datetime.date(2000 + int(yy), int(month), int(day)).isoformat()
        reference = _reference_date(collected_at)
        if reference is None:
            return None
        parsed = datetime.date(reference.year, int(month), int(day))
        if parsed > reference:
            parsed = datetime.date(reference.year - 1, int(month), int(day))
        return parsed.isoformat()
    except ValueError:  # 2.30 같은 존재하지 않는 날짜
        return None


class _SeenReviews:
    def __init__(self):
        self.exact = set()           # 카카오·구글: (channel, content)
        self.naver_dated = set()     # (정규화 본문, 작성일)
        self.naver_undated = set()   # 작성일을 모르는 네이버 본문
        self.naver_all = set()       # 모든 네이버 본문

    @staticmethod
    def _naver_key(review, collected_at):
        return normalize_content(review.get("content")), parse_naver_date(review.get("date"), collected_at)

    def add(self, review, collected_at):
        if review.get("channel") != _NAVER:
            self.exact.add((review.get("channel"), review.get("content")))
            return
        content, date = self._naver_key(review, collected_at)
        self.naver_all.add(content)
        if date is None:
            self.naver_undated.add(content)
        else:
            self.naver_dated.add((content, date))

    def contains(self, review, collected_at):
        if review.get("channel") != _NAVER:
            return (review.get("channel"), review.get("content")) in self.exact
        content, date = self._naver_key(review, collected_at)
        if date is None:
            return content in self.naver_all
        return (content, date) in self.naver_dated or content in self.naver_undated


def find_new_reviews(existing_reviews, incoming_reviews, collected_at=None):
    """existing_reviews에 없는 incoming_reviews만 반환한다. 같은 배치 안 중복은 첫 건만 남긴다.
    기존 행의 연도 추론 기준은 각 행의 collected_at, 신규 리뷰는 인자 collected_at."""
    seen = _SeenReviews()
    for review in existing_reviews:
        seen.add(review, review.get("collected_at"))
    new_reviews = []
    for review in incoming_reviews:
        if seen.contains(review, collected_at):
            continue
        seen.add(review, collected_at)
        new_reviews.append(review)
    return new_reviews
