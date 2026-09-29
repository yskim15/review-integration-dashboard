# 부정 리뷰 주요 포인트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 부정 리뷰마다 Claude가 주요 불만 포인트를 `key_points` 컬럼에 기록하고, 대시보드 부정 TOP 5를 이것으로 집계한다.

**Architecture:** 시트 끝에 `key_points` 컬럼(자동 확장), `reclassify.py` 후보에 작업 종류(`tasks`) 추가, 반영은 batch_update 1회, 프런트는 부정 TOP 5만 `key_points` 사용.

**Tech Stack:** Python 3.13, gspread, 바닐라 JS(index.html). 테스트는 `test_*.py` 직접 실행.

**Spec:** `docs/superpowers/specs/2026-09-29-negative-key-points-design.md`

## Global Constraints
- `$PY` = `/c/Users/SEMACONSULTING/AppData/Local/Programs/Python/Python313/python.exe`, `PYTHONIOENCODING=utf-8` 붙여 실행, `리뷰 통합 시트/`에서 실행.
- 새 테스트 함수는 각 파일 `__main__`에 호출을 추가해야 실행된다.
- 시트 쓰기는 호출 1회로 묶는다(Sheets quota). 기존 컬럼 위치 불변(`key_points`는 맨 끝).
- `reclassify_work/`는 커밋 금지. 테스트 데이터는 가상 이름.
- 커밋 메시지 끝 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. 헤더가 13개(구버전)인 실제 시트 → 첫 실행에서 `key_points` 헤더가 붙고 예외가 나지 않아야 한다 (T1 `test_ensure_header_extends_missing_trailing_columns`).
2. `get_all_records`가 구버전 행에 `key_points`를 빈 값으로 준다 → 부정+본문 행은 포인트 후보가 된다 (T2 `test_find_candidates_adds_key_point_task_for_negative_rows`).
3. 본문이 같은 짧은 부정 리뷰 여러 행 → 서로 다른 행에 반영 (T2 `test_apply_results_key_points_distinct_rows`).
4. 포인트를 못 찾은 리뷰 `["-"]` → 다시 후보로 안 나오고 대시보드 집계에서 빠짐 (T2 `test_find_candidates_skips_rows_with_key_points`, T3 수동 확인).
5. 감성 작업 없이 포인트만 쓰는 결과 → sentiment/method는 그대로 (T2 `test_apply_results_key_points_only_keeps_sentiment`).

---

### Task 1: sheets_writer — key_points 컬럼 + 헤더 자동 확장 + 범용 batch 갱신
**Files:** `sheets_writer.py`, `test_sheets_writer.py`

**Produces:** `HEADER`(끝에 `"key_points"`), `ensure_header(ws)`(앞부분 일치 시 빠진 뒤 컬럼 헤더를 `batch_update` 1회로 추가), `batch_update_fields(ws, [(row_number, {field: value})])`(1회 호출), `batch_update_sentiments`는 이를 이용하도록 유지.

- [ ] 실패 테스트:
  - `test_ensure_header_extends_missing_trailing_columns`: 시트 헤더 = `HEADER[:-1]` → 호출 후 `values[0] == HEADER`, `batch_update_calls == 1`.
  - 기존 `test_ensure_header_raises_when_mismatched`는 그대로 통과해야 함(앞부분 불일치).
  - `test_batch_update_fields_writes_arbitrary_columns_in_one_call`: 2행에 `{"key_points": "주차,가격"}`, 3행에 `{"sentiment": "부정", "key_points": "-"}` → 한 번 호출, 해당 셀만 변경.
  - `test_review_to_row_key_points_blank`: 새 행 길이 == `len(HEADER)`, `key_points` 칸 `""`.
  - FakeWorksheet `_set_cell`이 행 길이보다 뒤 칸이면 `""`로 채워 늘리게 수정(테스트 유틸).
- [ ] 실행 → FAIL 확인 → 구현 → PASS → 커밋 `feat: 시트 key_points 컬럼 + 헤더 자동 확장`.

### Task 2: reclassify — 포인트 작업 후보·반영
**Files:** `reclassify.py`, `test_reclassify.py`

**Consumes:** `sheets_writer.batch_update_fields`, `ensure_header`.
**Produces:** 후보 `{"id", "hospital_id", "channel", "content", "current_sentiment", "current_score", "current_matched_words", "tasks"}`, 요청 파일 `existing_key_points: {포인트: 건수}`, 결과 항목 `{"id", "sentiment"?, "confirmed"?, "key_points"?: [str], "note"}`.

- [ ] 실패 테스트:
  - `test_find_candidates_adds_key_point_task_for_negative_rows`: rating 부정+본문+포인트 없음 → `tasks == ["key_points"]`; lexicon → `["sentiment", "key_points"]`.
  - `test_find_candidates_skips_rows_with_key_points`: `key_points` 있음(`"-"` 포함), 본문 없음, 부정 아님(비lexicon) → 제외.
  - `test_export_includes_existing_key_points`: 시트의 `"주차,가격"`, `"주차"` → `{"주차": 2, "가격": 1}` (`-` 제외).
  - `test_apply_results_key_points_only_keeps_sentiment`: rating 부정 행에 `{"id":0,"key_points":["주차"]}` → `key_points == "주차"`, sentiment/method 불변, `batch_update_calls == 1`.
  - `test_apply_results_sentiment_and_key_points`: lexicon 행에 부정+`["상담 태도"]` → 세 컬럼 + key_points 반영.
  - `test_apply_results_key_points_distinct_rows`: 본문 "별로" 부정 rating 행 2개 → 각각 반영.
  - 기존 reclassify 테스트는 그대로 통과해야 함.
- [ ] 구현:
  - 후보 선정 규칙은 spec 3.2 그대로. `_eligible(review, tasks)`로 반영 시에도 같은 규칙 재사용(감성 작업은 lexicon 행, 포인트 작업만이면 부정+포인트 빈 행).
  - 로그 항목에 `key_points` 추가.
  - `run_export`에서 `ensure_header` 호출, `existing_key_points` 계산해 export에 전달.
- [ ] 실행 → FAIL → 구현 → PASS → 전체 스위트 → 커밋 `feat: 재분류 단계에서 부정 리뷰 주요 포인트 기록`.

### Task 3: 대시보드 + 문서
**Files:** `index.html`, `CLAUDE.md`

- [ ] `toReview`: `keyPoints = key_points 분리 → trim → "-"·빈 값 제외`.
- [ ] `renderKeywordLists`: 부정은 `r.keyPoints`, 긍정은 `r.keywords`.
- [ ] 설명 문구: "긍정 키워드는 네이버 리뷰의 규칙기반 분류에서 매칭된 단어, 부정 키워드는 모든 채널의 부정 리뷰에서 Claude가 정리한 주요 불만 포인트를 집계한 것입니다." 코드 주석도 갱신.
- [ ] `CLAUDE.md`: 요청/결과 형식(`tasks`, `existing_key_points`, `key_points`)과 spec 4절 작성 규칙 추가.
- [ ] 로컬 서버(`$PY -m http.server 8765 --bind 127.0.0.1`)로 열어 콘솔 오류 없음 확인 → 커밋 `feat: 대시보드 부정 TOP 5를 주요 포인트로 집계`.

### Task 4: 배포 + 기존 부정 리뷰 채우기
- [ ] 최종 리뷰(별도 검토자) → 지적 반영.
- [ ] 사용자 확인 후 push.
- [ ] `reclassify.py --export`(헤더 확장 확인) → Claude가 전체 후보 판단 → `--apply` → 재export 후보 0건.
- [ ] 라이브 대시보드에서 부정 TOP 5 확인.
