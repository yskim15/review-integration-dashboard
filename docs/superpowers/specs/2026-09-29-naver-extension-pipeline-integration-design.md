# 네이버 크롬 확장 수집 ↔ 메인 파이프라인 공통 처리 통합 설계

- 작성일: 2026-09-29
- 상태: 설계 승인(대화), 문서 검토 대기
- 관련: `naver_extension_bridge.py`(커밋 a207042), `main.py`, `dedup.py`, `sheets_writer.py`

## 1. 배경과 목표

2026-09-28에 네이버 수집을 **병행 구조**로 확정했다. GitHub Actions(`main.py`)가 매일 GraphQL로
자동 수집하고, 차단·실패한 병원은 담당자 브라우저의 크롬 확장으로 수집한 엑셀을
`naver_extension_bridge.py import --apply`로 보완 적재한다.

두 경로는 같은 시트에 쓰지만 **적재 로직이 따로** 구현되어 있다.

| | `main.py` | 브리지 |
|---|---|---|
| 중복 판정 | `dedup.find_new_reviews` — (channel, content) 완전 일치 | 자체 `select_new` — 공백 정규화 본문 일치 |
| 분류 | `classify` | `classify` |
| 시트 반영 | `sheets_writer.append_reviews` | `append_rows` 직접 호출 + `has_reply` 사후 덮어쓰기 |

**목표**: 두 경로가 하나의 공통 적재 함수를 쓰게 하고, 중복 판정 규칙을 하나로 합친다.
실행 방식(Actions 자동 + 확장 수동 보완)은 바꾸지 않는다.

**하지 않는 것**
- 확장을 Actions 안에서 무인 실행하는 것. 캡차를 사람 없이 넘겨야 하므로 기존 원칙상 불가
  (메모리 `feedback_no_stealth_scraping_no_fake_data`).
- 기존 시트 행의 수정·삭제·재계산.
- 카카오·구글 중복 판정 변경.

## 2. 실측으로 확인한 문제 (2026-09-29, 시트 838행)

1. **공백만 다른 같은 리뷰가 이중 적재될 수 있다.** 확장이 넣은 행을 다음 날 GraphQL이
   공백만 다른 본문으로 다시 가져오면, `main.py`의 완전 일치 판정은 신규로 본다.
   (현재 확장 반영 행은 0건이라 아직 발생 전.)
2. **본문만으로는 서로 다른 짧은 리뷰를 구분할 수 없다.** 공백 정규화 시 겹치는 2쌍
   (comp_midream "친절해요"/"좋아요")을 확인한 결과, 작성일·작성자가 달라 **실제로 다른
   리뷰**였다. 브리지의 정규화 규칙을 그대로 메인에 적용하면 이런 리뷰가 누락된다.
   현재 완전 일치 규칙도 "좋아요"처럼 글자까지 같은 다른 리뷰는 첫 건만 남긴다.
3. 네이버 `date` 값은 실측상 두 형식뿐이다: `M.D.요일`(453행, 올해) / `YY.M.D.요일`(196행).
   확장 엑셀의 `작성일(원문)`도 같은 형식이다.

## 3. 설계

### 3.1 중복 판정 키 (`dedup.py`)

- **네이버**: `("네이버", normalize(content), iso_date)`
  - `normalize`: 연속 공백·줄바꿈을 공백 하나로, 앞뒤 공백 제거.
  - `iso_date`: `parse_naver_date(date, reference)`가 `YYYY-MM-DD`를 반환한다.
    - `YY.M.D.요일` → `20YY-MM-DD`.
    - `M.D.요일` → reference의 연도로 만들되, 결과가 reference 날짜보다 미래면 1년 뺀다
      (1월에 수집한 "12.30.월"은 전년도).
    - `reference`: 기존 시트 행은 그 행의 `collected_at`, 새로 수집한 리뷰는 이번 실행의
      `collected_at`. 파싱 실패(빈 값·형식 불일치) 시 `None`.
  - `iso_date`가 `None`이면 `("네이버", normalize(content), None)` — 즉 본문만으로 비교
    (현재 동작과 같은 안전한 방향).
- **카카오맵·구글**: 기존 `(channel, content)` 그대로. 날짜가 "3일 전" 같은 상대 표기라
  키로 쓰면 매일 달라진다.
- `find_new_reviews(existing, incoming, collected_at)` 시그니처에 `collected_at`을 추가한다.
  같은 배치 안 중복은 기존처럼 첫 건만 남긴다.

**알려진 한계(수용)**: 같은 병원에서 같은 날 글자까지 같은 짧은 리뷰("좋아요")를 두 사람이
쓰면 여전히 1건만 남는다. 작성자는 마스킹 차이로 키에 쓸 수 없고(dedup.py 주석의
2026-09-11 사고), 확장 엑셀엔 작성자도 없다.

### 3.2 공통 적재 함수 (`review_ingest.py`, 신규)

```python
def ingest(worksheet, existing_for_hospital, hospital_id, reviews, collected_at):
    """중복 제거 → 규칙기반 분류 → 시트 append(1회 호출). 추가된 행 수를 반환한다."""
```

- `dedup.find_new_reviews(existing_for_hospital, reviews, collected_at)` →
  `classify` → `sheets_writer.append_reviews`.
- `main.py`와 브리지는 이 함수만 호출한다.

### 3.3 호출부 변경

- **`main.py`**: `run()` 안 병원별 루프의 dedup/classify/append 3줄을 `review_ingest.ingest`
  한 줄로 바꾼다. 수집·실패 처리·출력 문구·Actions 워크플로우는 그대로.
- **`naver_extension_bridge.py`**: `select_new`와 `append_rows` 직접 호출·`has_reply`
  덮어쓰기를 지우고 `review_ingest.ingest`를 호출한다. 파일명 매칭·엑셀 읽기·
  `rows_to_reviews`·dry-run은 그대로.
- **`sheets_writer.review_to_row`**: `has_reply`가 `None`(모름)이면 빈 값으로 쓴다.
  `True`/`False`는 기존대로.

### 3.4 문서

- `리뷰 통합 시트/CLAUDE.md`: "`main.py` 절대 건드리지 않는다"를 "수집·스케줄 구조는
  고정, 적재 로직은 `review_ingest.py` 공통 함수로 관리"로 고치고, 중복 판정 규칙을
  브리지 절에 반영한다.
- `dedup.py` 모듈 주석: 네이버 키에 작성일이 들어간 이유(2절 2번 실측)를 추가한다.

## 4. 오류 처리

- 날짜 파싱 실패는 예외가 아니라 `None` → 본문만 비교로 폴백한다.
- `ingest`는 시트 쓰기를 병원당 `append_rows` 1회로 유지한다(Sheets 쓰기 quota, 2026-09-22 429 사고).
- 그 밖의 실패 처리(채널 실패 격리, 브리지의 파일 단위 건너뜀)는 바꾸지 않는다.

## 5. 테스트 (TDD)

- `test_dedup.py`
  - 네이버: 본문이 같아도 작성일이 다르면 둘 다 신규.
  - 네이버: 공백·줄바꿈만 다르고 작성일이 같으면 중복.
  - 네이버: 작성일 파싱 실패 시 본문만으로 비교.
  - 카카오: 기존 (channel, content) 동작 유지(기존 테스트 통과).
  - `parse_naver_date`: `YY.M.D.요일`, `M.D.요일`, 연초 수집 시 전년도 추론, 잘못된 형식 → `None`.
- `test_review_ingest.py`: FakeWorksheet로 dedup→분류→append 1회 호출, 추가 건수 반환.
- `test_main.py` / `test_naver_extension_bridge.py`: 두 경로가 `review_ingest.ingest`를 거치는지,
  브리지 반영 행의 `has_reply`가 빈 값인지.
- `test_sheets_writer.py`: `has_reply=None` → 빈 값.

## 6. 검증 (실행 후)

- 전체 테스트 통과.
- 실제 시트 대상 dry-run 성격의 검증: 현재 시트 838행을 새 키로 계산해 "기존 행끼리 중복으로
  판정되는 그룹 0건"(2절 2번의 2쌍이 서로 다른 리뷰로 판정됨)을 확인한다. 시트에는 쓰지 않는다.
- Actions는 `workflow_dispatch`로 한 번 수동 실행해 신규 적재 건수가 비정상적으로 늘지 않는지
  확인한다(기존 행이 신규로 재적재되면 키 계산 오류).
