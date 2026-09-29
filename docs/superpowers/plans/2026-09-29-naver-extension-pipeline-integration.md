# 네이버 확장 수집 ↔ 메인 파이프라인 공통 처리 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `main.py`(Actions GraphQL 수집)와 `naver_extension_bridge.py`(크롬 확장 엑셀 적재)가 같은 적재 함수·같은 중복 판정 규칙을 쓰게 한다.

**Architecture:** 신규 `review_ingest.ingest()`가 중복 제거→규칙기반 분류→시트 append(1회)를 담당하고 두 진입점이 이것만 호출한다. `dedup.find_new_reviews`는 네이버에 한해 (정규화 본문, ISO 작성일) 키를 쓰고, 어느 한쪽이라도 작성일을 모르면 본문만 비교한다.

**Tech Stack:** Python 3.13, gspread, openpyxl(브리지 로컬 전용). 테스트는 pytest가 아니라 각 `test_*.py`를 직접 실행하는 기존 방식.

**Spec:** `docs/superpowers/specs/2026-09-29-naver-extension-pipeline-integration-design.md`

## Global Constraints

- 모든 명령은 `리뷰 통합 시트/` 폴더를 현재 디렉터리로 두고 실행한다.
- Python: `C:\Users\SEMACONSULTING\AppData\Local\Programs\Python\Python313\python.exe` (Bash에선 `/c/Users/SEMACONSULTING/AppData/Local/Programs/Python/Python313/python.exe`, 이하 `$PY`). 한글 출력 깨짐 방지로 `PYTHONIOENCODING=utf-8`을 붙인다.
- 테스트 실행: `PYTHONIOENCODING=utf-8 $PY test_<name>.py` — 각 파일 하단 `__main__`에 새 테스트 함수를 **반드시 추가**해야 실행된다.
- 카카오맵·구글의 중복 판정은 기존 `(channel, content)` 완전 일치 그대로.
- 기존 시트 행은 수정·삭제하지 않는다. Actions 워크플로우(`.github/workflows/daily_collect.yml`)와 수집기(`collectors/`)는 바꾸지 않는다.
- 시트 쓰기는 병원당 `append_rows` 1회(Sheets 쓰기 quota).
- `reclassify_work/`, `naver_extension_work/`는 실제 리뷰 원문 — 커밋 금지(저장소 public).
- 테스트 데이터에 실제 병원명·실명 금지(가상 이름 사용).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. 날짜를 아는 쪽/모르는 쪽이 섞인 같은 리뷰 → 중복으로 판정돼야 한다 (Task 1 `test_naver_date_known_on_one_side_only_is_duplicate`).
2. 연초(1월)에 수집한 `12.30.월` → 전년도로 해석돼야 한다 (Task 1 `test_parse_naver_date_year_rollover`).
3. 존재하지 않는 날짜(`2.30.화`, 평년 `2.29`)·빈 값·"3일 전" → 예외 없이 `None` (Task 1 `test_parse_naver_date_invalid_returns_none`).
4. 기존 시트 행의 `collected_at`이 비었거나 깨진 경우 → `M.D.요일` 행은 날짜 모름으로 취급, 크래시 없음 (Task 1 `test_existing_row_without_collected_at_falls_back_to_content`).
5. 확장 엑셀과 GraphQL이 같은 리뷰를 공백만 다르게 가져온 경우 → 브리지 적재 시 신규 0건 (Task 5 `test_import_apply_skips_whitespace_variant_of_existing`).

---

## File Structure

| 파일 | 변경 | 책임 |
|---|---|---|
| `dedup.py` | 수정 | `normalize_content`, `parse_naver_date`, 채널별 키 규칙을 가진 `find_new_reviews(existing, incoming, collected_at=None)` |
| `sheets_writer.py` | 수정 | `review_to_row`: `has_reply=None` → `""` |
| `review_ingest.py` | 신규 | `ingest(worksheet, existing_for_hospital, hospital_id, reviews, collected_at) -> int` |
| `main.py` | 수정 | 병원 루프에서 `review_ingest.ingest` 호출 |
| `naver_extension_bridge.py` | 수정 | `select_new`·직접 `append_rows`·`has_reply` 덮어쓰기 제거, `review_ingest.ingest` 호출 |
| `test_dedup.py`, `test_sheets_writer.py`, `test_review_ingest.py`(신규), `test_main.py`, `test_naver_extension_bridge.py` | 수정/신규 | 위 동작 고정 |
| `CLAUDE.md`(이 폴더) | 수정 | `main.py` 고정 문구·중복 규칙 설명 갱신 |

---

### Task 1: dedup — 네이버 작성일 키

**Files:**
- Modify: `dedup.py` (전체 교체)
- Test: `test_dedup.py`

**Interfaces:**
- Produces: `dedup.normalize_content(text) -> str`, `dedup.parse_naver_date(value, collected_at) -> str | None` (`"YYYY-MM-DD"`), `dedup.find_new_reviews(existing_reviews, incoming_reviews, collected_at=None) -> list[dict]`. 기존 행의 기준 시점은 각 행의 `collected_at` 키, 신규 리뷰는 인자 `collected_at`.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_dedup.py`의 `if __name__` 블록 **위에** 추가하고, import 줄을 `from dedup import find_new_reviews, normalize_content, parse_naver_date`로 바꾼다.

```python
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
```

`__main__` 블록에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인** — `PYTHONIOENCODING=utf-8 $PY test_dedup.py` → `ImportError: cannot import name 'normalize_content'`.

- [ ] **Step 3: 구현** — `dedup.py` 전체를 교체:

```python
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
# 네이버 작성일 실측 형식: "M.D.요일"(올해) / "YY.M.D.요일"
_NAVER_DATE_RE = re.compile(r"^(?:(\d{2})\.)?(\d{1,2})\.(\d{1,2})\.[가-힣]$")


def normalize_content(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _reference_date(collected_at):
    try:
        return datetime.date.fromisoformat(str(collected_at or "")[:10])
    except ValueError:
        return None


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
```

- [ ] **Step 4: 통과 확인** — `PYTHONIOENCODING=utf-8 $PY test_dedup.py` → 기존 4개 + 신규 10개 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add dedup.py test_dedup.py
git commit -m "feat: 네이버 중복 판정에 작성일 추가 + 공백 정규화

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: sheets_writer — has_reply 모름은 빈 값

**Files:**
- Modify: `sheets_writer.py:36-53` (`review_to_row`)
- Test: `test_sheets_writer.py`

**Interfaces:**
- Produces: `review_to_row`가 `review["has_reply"] is None`이면 해당 칸을 `""`로, 키가 없으면 기존대로 `False`.

- [ ] **Step 1: 실패하는 테스트** — `test_sheets_writer.py`에 추가하고 `__main__`에 호출 추가:

```python
def test_review_to_row_has_reply_none_is_blank():
    classification = {"sentiment": "긍정", "confirmed": True, "score": 2, "matched_words": [], "method": "lexicon"}
    col = sheets_writer.HEADER.index("has_reply")
    base = {"channel": "네이버", "author": "", "rating": None, "date": "9.16.수", "content": "좋아요"}
    assert sheets_writer.review_to_row("h_a", {**base, "has_reply": None}, classification, "t")[col] == ""
    assert sheets_writer.review_to_row("h_a", {**base, "has_reply": True}, classification, "t")[col] is True
    assert sheets_writer.review_to_row("h_a", base, classification, "t")[col] is False
    print("PASS: test_review_to_row_has_reply_none_is_blank")
```

- [ ] **Step 2: 실패 확인** — `PYTHONIOENCODING=utf-8 $PY test_sheets_writer.py` → `AssertionError` (현재 `False`).

- [ ] **Step 3: 구현** — `review_to_row` 안:

```python
    rating = review.get("rating")
    score = classification.get("score")
    has_reply = review.get("has_reply", False)  # None = 모름(확장 엑셀엔 답글 정보 없음)
```

반환 리스트의 `bool(review.get("has_reply", False)),` 줄을 다음으로 교체:

```python
        "" if has_reply is None else bool(has_reply),
```

- [ ] **Step 4: 통과 확인** — `PYTHONIOENCODING=utf-8 $PY test_sheets_writer.py` → 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add sheets_writer.py test_sheets_writer.py
git commit -m "feat: has_reply 모름(None)을 시트에 빈 값으로 기록

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: review_ingest — 공통 적재 함수

**Files:**
- Create: `review_ingest.py`
- Test: `test_review_ingest.py` (신규)

**Interfaces:**
- Consumes: `dedup.find_new_reviews(existing, incoming, collected_at)` (Task 1), `sheets_writer.append_reviews(worksheet, hospital_id, [(review, classification)], collected_at) -> int`, `classifier.rule_based.classify(review) -> dict`.
- Produces: `review_ingest.ingest(worksheet, existing_for_hospital, hospital_id, reviews, collected_at) -> int` (추가된 행 수).

- [ ] **Step 1: 실패하는 테스트** — `test_review_ingest.py` 생성:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import review_ingest
import sheets_writer
from test_sheets_writer import FakeWorksheet

NOW = "2026-09-29T13:00:00+09:00"


class CountingWorksheet(FakeWorksheet):
    def __init__(self, initial_values=None):
        super().__init__(initial_values)
        self.append_rows_calls = 0

    def append_rows(self, rows, value_input_option=None):
        self.append_rows_calls += 1
        super().append_rows(rows, value_input_option)


def test_ingest_dedups_classifies_and_appends_once():
    ws = CountingWorksheet(initial_values=[sheets_writer.HEADER])
    existing = [{"hospital_id": "h_a", "channel": "네이버", "content": "친절해요", "date": "9.16.수", "collected_at": NOW}]
    reviews = [
        {"channel": "네이버", "author": "", "rating": None, "date": "9.16.수", "content": "친절해요 ", "has_reply": None},
        {"channel": "네이버", "author": "", "rating": None, "date": "9.17.목", "content": "친절해요", "has_reply": None},
        {"channel": "네이버", "author": "", "rating": None, "date": "9.18.금", "content": "새 리뷰 좋아요", "has_reply": False},
    ]

    added = review_ingest.ingest(ws, existing, "h_a", reviews, NOW)

    assert added == 2, f"실제: {added}"
    assert ws.append_rows_calls == 1
    assert [row[sheets_writer.HEADER.index("date")] for row in ws.values[1:]] == ["9.17.목", "9.18.금"]
    assert all(row[sheets_writer.HEADER.index("method")] for row in ws.values[1:]), "분류 결과가 기록돼야 함"
    assert ws.values[1][sheets_writer.HEADER.index("collected_at")] == NOW
    print("PASS: test_ingest_dedups_classifies_and_appends_once")


def test_ingest_no_new_reviews_makes_no_api_call():
    ws = CountingWorksheet(initial_values=[sheets_writer.HEADER])
    existing = [{"hospital_id": "h_a", "channel": "카카오맵", "content": "좋아요", "collected_at": NOW}]
    added = review_ingest.ingest(ws, existing, "h_a", [{"channel": "카카오맵", "content": "좋아요"}], NOW)
    assert added == 0
    assert ws.append_rows_calls == 0
    print("PASS: test_ingest_no_new_reviews_makes_no_api_call")


if __name__ == "__main__":
    test_ingest_dedups_classifies_and_appends_once()
    test_ingest_no_new_reviews_makes_no_api_call()
```

- [ ] **Step 2: 실패 확인** — `PYTHONIOENCODING=utf-8 $PY test_review_ingest.py` → `ModuleNotFoundError: No module named 'review_ingest'`.

- [ ] **Step 3: 구현** — `review_ingest.py` 생성:

```python
"""신규 리뷰 적재 공통 경로: 중복 제거 → 규칙기반 분류 → 시트 append(1회).

main.py(GitHub Actions 자동 수집)와 naver_extension_bridge.py(크롬 확장 엑셀 보완)가
둘 다 이 함수만 호출해, 두 경로의 중복 판정·분류 규칙이 어긋나지 않게 한다.
"""

import dedup
import sheets_writer
from classifier.rule_based import classify


def ingest(worksheet, existing_for_hospital, hospital_id, reviews, collected_at):
    """existing_for_hospital: 그 병원의 기존 시트 행(dict). 추가된 행 수를 반환한다."""
    new_reviews = dedup.find_new_reviews(existing_for_hospital, reviews, collected_at)
    classified = [(review, classify(review)) for review in new_reviews]
    return sheets_writer.append_reviews(worksheet, hospital_id, classified, collected_at)
```

- [ ] **Step 4: 통과 확인** — `PYTHONIOENCODING=utf-8 $PY test_review_ingest.py` → 2개 PASS.

- [ ] **Step 5: 커밋**

```bash
git add review_ingest.py test_review_ingest.py
git commit -m "feat: 수집 경로 공통 적재 함수 review_ingest.ingest

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: main.py가 review_ingest를 쓰게 전환

**Files:**
- Modify: `main.py` (import 블록, `run()` 병원 루프 93-98행)
- Test: `test_main.py`

**Interfaces:**
- Consumes: `review_ingest.ingest(...)` (Task 3).

- [ ] **Step 1: 실패하는 테스트** — `test_main.py`에 추가하고 `__main__`에 호출 추가:

```python
def test_run_routes_new_reviews_through_review_ingest():
    hospital = {"hospital_id": "h_a", "hospital_name": "가나다의원", "channels": _FULL_CHANNELS}
    existing = [{"hospital_id": "h_a", "channel": "네이버", "content": "기존"},
                {"hospital_id": "h_other", "channel": "네이버", "content": "다른 병원"}]
    raw = [{"channel": "네이버", "content": "새 리뷰"}]
    with patch.dict(os.environ, {"GOOGLE_SHEET_ID": "x", "GCP_SA_KEY": "{}"}), \
         patch("main.load_hospitals", return_value=[hospital]), \
         patch("main.load_competitors", return_value=[]), \
         patch("main.sheets_writer.connect", return_value="WS"), \
         patch("main.sheets_writer.ensure_header"), \
         patch("main.sheets_writer.read_existing_reviews", return_value=existing), \
         patch("main.collect_hospital", return_value=(raw, [])), \
         patch("main.review_ingest.ingest", return_value=1) as ingest:
        main.run()
    ingest.assert_called_once()
    worksheet, existing_arg, hospital_id, reviews, collected_at = ingest.call_args.args
    assert worksheet == "WS" and hospital_id == "h_a" and reviews == raw
    assert existing_arg == [existing[0]], "그 병원 행만 넘겨야 함"
    assert collected_at
    print("PASS: test_run_routes_new_reviews_through_review_ingest")
```

- [ ] **Step 2: 실패 확인** — `PYTHONIOENCODING=utf-8 $PY test_main.py` → `AttributeError: <module 'main'> does not have the attribute 'review_ingest'`.

- [ ] **Step 3: 구현** — `main.py` import 블록에서 `import dedup`과 `from classifier.rule_based import classify`를 지우고 `import review_ingest`를 추가:

```python
import review_ingest
import sheets_writer
from collectors import google, kakao, naver
from collectors.base import safe_run
```

`run()` 병원 루프의

```python
        existing_for_hospital = [r for r in all_existing if r.get("hospital_id") == hospital_id]
        new_reviews = dedup.find_new_reviews(existing_for_hospital, raw_reviews)
        classified = [(review, classify(review)) for review in new_reviews]

        added = sheets_writer.append_reviews(worksheet, hospital_id, classified, collected_at)
```

를 다음으로 교체:

```python
        existing_for_hospital = [r for r in all_existing if r.get("hospital_id") == hospital_id]
        added = review_ingest.ingest(worksheet, existing_for_hospital, hospital_id, raw_reviews, collected_at)
```

모듈 docstring 첫 단락의 `collectors(네이버/카카오/구글) -> dedup -> classifier(규칙기반) -> sheets_writer` 뒤에 한 줄 추가: `(dedup -> 분류 -> 적재는 review_ingest.ingest 공통 함수 — 크롬 확장 브리지와 같은 경로)`.

- [ ] **Step 4: 통과 확인** — `PYTHONIOENCODING=utf-8 $PY test_main.py` → 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add main.py test_main.py
git commit -m "refactor: main.py 적재를 review_ingest 공통 함수로 전환

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 브리지가 review_ingest를 쓰게 전환 + 문서

**Files:**
- Modify: `naver_extension_bridge.py` (import, `normalize_content`/`select_new` 삭제, `cmd_import` apply 루프, docstring)
- Modify: `CLAUDE.md` (이 폴더)
- Test: `test_naver_extension_bridge.py`

**Interfaces:**
- Consumes: `review_ingest.ingest(...)` (Task 3), `review_to_row`의 `has_reply=None → ""` (Task 2).

- [ ] **Step 1: 실패하는 테스트** — `test_naver_extension_bridge.py`:
  - import에서 `select_new`를 빼고 `cmd_import`를 추가, 상단에 `import os`, `from unittest.mock import patch`, `import sheets_writer`, `from test_sheets_writer import FakeWorksheet` 추가.
  - `test_select_new_ignores_whitespace_differences` 함수와 `__main__`의 호출을 삭제(같은 규칙은 Task 1 `test_dedup.py`로 옮겨짐).
  - 아래 두 테스트 추가 + `__main__`에 호출 추가:

```python
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
        ws = _run_import(d, [_existing_row("친절해요\n또 올게요", "9.16.수")])
    assert len(ws.values) == 2, f"신규 0건이어야 함: {ws.values}"
    print("PASS: test_import_apply_skips_whitespace_variant_of_existing")
```

- [ ] **Step 2: 실패 확인** — `PYTHONIOENCODING=utf-8 $PY test_naver_extension_bridge.py` → 첫 테스트에서 `AssertionError` (현재 `select_new`가 본문만 비교해 "좋았어요" 두 번째를 버림 → 1건).

- [ ] **Step 3: 구현** — `naver_extension_bridge.py`:
  - import에서 `import dedup`, `from classifier.rule_based import classify`를 지우고 `import review_ingest`를 추가(`import sheets_writer`는 유지).
  - `normalize_content`와 `select_new` 함수 전체 삭제.
  - `cmd_import`의 apply 루프:

```python
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
```

를 다음으로 교체:

```python
        existing_for_hospital = [r for r in existing if r.get("hospital_id") == hospital_id]
        added = review_ingest.ingest(worksheet, existing_for_hospital, hospital_id, reviews, collected_at)
        total += added
        print(f"- {path.name} -> {hospital_id}: 파일 {len(reviews)}건 중 신규 {added}건 반영")
```

  - 모듈 docstring의 `import --apply는 main.py와 같은 흐름(중복 제거 → 규칙기반 분류 → Sheets append)을\n탄다.`를 `import --apply는 main.py와 같은 review_ingest.ingest(중복 제거 → 규칙기반 분류 →\nSheets append)를 호출한다.`로 교체.

- [ ] **Step 4: 통과 확인** — `PYTHONIOENCODING=utf-8 $PY test_naver_extension_bridge.py` → 전부 PASS.

- [ ] **Step 5: CLAUDE.md 갱신** — `리뷰 통합 시트/CLAUDE.md`:
  - `이 폴더 작업 중 절대 건드리지 않는다(설계상 고정).` →
    `수집 채널·스케줄·Actions 워크플로우는 설계상 고정이다. 적재(중복 제거 → 분류 → append)는 \`review_ingest.ingest\` 공통 함수로, 크롬 확장 브리지와 같은 경로를 쓴다(2026-09-29).`
  - 브리지 절의 `- 중복 판정은 본문 공백·줄바꿈을 정규화해 비교한다(GraphQL 본문과 확장이 DOM에서 읽은\n  본문의 공백이 다를 수 있음). 확장 엑셀엔 작성자·답글 정보가 없어 빈 값으로 둔다.` →
    `- 중복 판정은 \`dedup.py\` 공통 규칙을 따른다: 네이버는 (공백 정규화 본문, 작성일), 한쪽이라도 작성일을\n  모르면 본문만 비교. 카카오·구글은 (channel, content) 완전 일치. 확장 엑셀엔 작성자·답글 정보가 없어\n  빈 값으로 둔다.`

- [ ] **Step 6: 전체 테스트** — 아래가 모두 PASS인지 확인:

```bash
for t in test_dedup.py test_sheets_writer.py test_review_ingest.py test_main.py test_naver_extension_bridge.py test_reclassify.py test_rule_based.py test_collectors_base.py test_collectors_naver.py test_collectors_kakao.py test_collectors_google.py test_find_naver_place_ids.py; do echo "== $t"; PYTHONIOENCODING=utf-8 $PY $t || echo "FAIL: $t"; done
```

- [ ] **Step 7: 커밋**

```bash
git add naver_extension_bridge.py test_naver_extension_bridge.py CLAUDE.md
git commit -m "refactor: 확장 브리지 적재를 review_ingest 공통 함수로 전환

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 실데이터 검증 + 배포

**Files:** 없음(스크래치패드 스크립트만). 시트 쓰기는 Step 3에서 사용자 확인 후에만.

- [ ] **Step 1: 기존 시트에 새 규칙 적용 (읽기 전용)** — PowerShell에서 사용자 환경변수를 불러와 실행:

```powershell
$env:GOOGLE_SHEET_ID = [Environment]::GetEnvironmentVariable('GOOGLE_SHEET_ID','User'); $env:GCP_SA_KEY = [Environment]::GetEnvironmentVariable('GCP_SA_KEY','User')
& "C:\Users\SEMACONSULTING\AppData\Local\Programs\Python\Python313\python.exe" -X utf8 -c "
import os, dedup, sheets_writer as s
from collections import defaultdict
rows = s.read_existing_reviews(s.connect(os.environ['GOOGLE_SHEET_ID'], os.environ['GCP_SA_KEY']))
by_h = defaultdict(list)
for r in rows: by_h[r['hospital_id']].append(r)
collide = 0
for h, rs in by_h.items():
    for i, r in enumerate(rs):
        if not dedup.find_new_reviews(rs[:i], [r], r.get('collected_at')): collide += 1
undated = sum(1 for r in rows if r['channel']=='네이버' and dedup.parse_naver_date(r['date'], r.get('collected_at')) is None)
print('rows', len(rows), 'existing rows judged duplicate of earlier rows:', collide, 'naver undated:', undated)
"
```

Expected: `existing rows judged duplicate of earlier rows: 0`, `naver undated: 0`. 0이 아니면 해당 행을 출력해 원인을 확인하고 멈춘다.

- [ ] **Step 2: GitHub push** — 사용자 확인 후 `git push origin main`.

- [ ] **Step 3: Actions 수동 실행 (시트에 씀 — 사용자 확인 후)** — `gh workflow run daily_collect.yml`, `gh run watch`로 완료까지 대기, 로그의 병원별 "신규 N건"을 기록.

- [ ] **Step 4: 실행 후 검증** — Step 1 스크립트를 다시 실행해 `collide`가 0인지 확인(0이 아니면 기존 행이 재적재된 것 = 키 오류). 새로 들어온 네이버 행 중 기존 행과 본문이 같은 것은 작성일이 서로 다른지 확인.

- [ ] **Step 5: 재분류** — 새로 적재된 `method=="lexicon"` 행은 `reclassify.py --export` → Claude 판단 → `--apply` 절차(이 폴더 CLAUDE.md)로 처리.
