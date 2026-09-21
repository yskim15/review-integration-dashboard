# Claude Code 검수(재분류) 단계 설계

- 작성일: 2026-09-21
- 상태: 승인됨 (사용자 승인, 구현 전)

## 배경

`classifier/rule_based.py`는 별점이 없는(네이버) 리뷰를 KNU 감성사전+병원 특화사전
단어 합산으로 분류한다. 2026-09-21 실제 시트 데이터(`method=="lexicon"`인 행 3건)를
점검한 결과 **3건 전부** 실제로는 긍정 리뷰인데 부정으로 확정(`confirmed=True`)되어
있었다.

원인 두 가지를 실측으로 확인:

1. **재분류 경로 부재**: `main.py`는 append-only라, 코드를 고쳐도(예: `져서` 제외
   처리, 2026-09-16) 이미 시트에 쓰인 과거 행은 절대 재계산되지 않는다.
2. **구조적 한계**: 형태소분석·문맥 없는 bag-of-words 합산이라
   - 병원 리뷰 특유의 "증상 설명" 단어(통증/염증/걱정/스트레스 등)가 실제로는
     "그래서 병원 갔더니 좋았다"는 내원 사유 설명인데 무조건 부정으로 잡힘
     (예: "염증"×2 + "스트레스" = -6이 "친절" +2를 압도).
   - "아팠지만 참을만 했다" 같은 양보구문을 단순 합산이 못 잡음.
   - KNU 사전의 2글자 잡음 항목(`ㅇㄴ` 등)이 무관한 약어 안에서 우연히 매칭됨 —
     `져서` 제외 처리와 같은 계열의 문제가 재발한 것.

단어 하나씩 예외처리로 땜질하는 방식(1글자 항목 제외 → `져서` 제외 → 이번 `ㅇㄴ`)이
반복 재발하는 패턴이므로, 개별 사전 수정 대신 **Claude Code가 저신뢰 판단을 주기적으로
검수하는 단계**를 파이프라인에 추가하기로 한다.

이 프로젝트는 [[project_review_integration_sheet]] 메모리에 기록된 서버리스
(GitHub Actions + Sheets + Pages) 아키텍처를 그대로 유지한다 — 이 설계는 그 위에
Claude Code 세션이 살아있는 동안 도는 **추가 검수 레이어**를 얹는 것이지, 매일 자동
수집 파이프라인(`main.py`) 자체를 바꾸지 않는다.

## 범위

- **대상**: `method=="lexicon"`인 시트 행 전체. 별점 기반(`method=="rating"`) 행은
  별점 자체가 근거라 재해석 여지가 없으므로 제외.
  - 신규 행(앞으로 수집되는 것)뿐 아니라 **기존에 이미 쌓인 행도 1회성으로 포함**한다
    (confirmed=True인 행도 대상 — 이번에 발견한 오분류 3건이 전부 confirmed=True였음).
- **비범위**: `rule_based.py`의 사전·로직 자체를 고치는 것은 이 설계에 포함하지 않는다
  (별도 코드 수정 사안). 이 설계는 이미 쌓인/쌓일 시트 데이터의 재분류만 다룬다.

## 아키텍처

`main.py`(매일 자동 수집, GitHub Actions, 완전 무인)와 별도로 동작하는
`reclassify.py`(Claude Code 세션이 켜져있을 때만 도는 검수 파이프라인)를 신설한다.

```
reclassify.py --export
    → 시트에서 method=="lexicon" 행 스캔
    → reclassify_work/[재분류요청].json 생성 (후보 0건이면 종료)

Claude Code가 JSON을 읽고 판단        ← Claude의 몫
    → reclassify_work/[재분류결과].json 작성

reclassify.py --apply
    → 결과 JSON을 읽어 (channel, content)로 시트 행을 찾아
      sentiment/confirmed/method 컬럼만 수정
    → 실제로 바뀐 행만 reclassify_work/reclassify_log.jsonl에 append
```

트리거는 `/loop`로, 이 Claude Code 세션이 켜져있는 동안 주기적으로(기본 1시간 간격,
조정 가능) 위 3단계를 반복 실행한다. 세션이 꺼져있으면 그 주기는 건너뛰고, 다음
세션 시작 시 밀린 후보가 자동으로 처리된다. 클라우드 cron이나 신규 비밀키 배포는
쓰지 않는다 — CLAUDE.md의 "상시 무인 배치가 실제 필요하다는 근거가 확인되기 전에는
그 목적으로 유료 외부 API를 도입하지 않는다" 원칙에 따름.

## 컴포넌트

### `sheets_writer.py` (기존 파일에 추가)

```python
def update_sentiment(worksheet, row_number, classification):
    """row_number: 1-based 시트 행 번호(헤더=1행).
    sentiment/confirmed/method 3개 컬럼(H, I, L)만 갱신한다.
    score/matched_words(J, K)는 원래 규칙기반 판단의 증거로 그대로 남긴다."""
```
- 기존 `append_reviews`와 달리 update 경로. `worksheet.update(f"H{row_number}", ...)`
  형태로 H, I, L 셀만 개별 갱신(연속 범위가 아니므로 batch 하나로 묶지 않고 셀 단위로
  갱신 — 구현 단순성 우선, YAGNI).
- `content`/`rating`/`author`/`channel`/`date`/`has_reply`/`collected_at`은 이
  함수가 절대 건드리지 않는다(원본 데이터 보존 원칙).

### `reclassify.py` (신규)

- `find_candidates(existing_reviews) -> list[dict]`: `method=="lexicon"`인 행만
  필터링. 순수 함수, 유닛테스트 대상.
- `export_for_claude(candidates, work_dir) -> str`: `[재분류요청].json` 생성,
  경로 반환. 후보 0건이면 파일을 만들지 않고 `None` 반환.
- `apply_results(worksheet, existing_reviews, work_dir)`: `[재분류결과].json`을
  읽어, 각 결과 항목을 `id`로 원본 후보와 매칭하고 그 `(channel, content)`로
  `existing_reviews`에서 시트상의 실제 행 번호를 찾아 `update_sentiment` 호출.
  매칭 실패(그 사이 시트가 바뀐 경우)는 건너뛰고 경고만 출력, 나머지는 계속 진행.
  실제로 값이 바뀐 항목만 `reclassify_log.jsonl`에 append.
- CLI: `python reclassify.py --export` / `python reclassify.py --apply`
  (`main.py`처럼 `argparse` 사용, `--hospital` 필터는 불필요 — 시트 전체가 검수
  대상이므로 병원 단위로 나눌 이유 없음).

### `reclassify_work/` (신규 폴더)

- `[재분류요청].json`, `[재분류결과].json`, `reclassify_log.jsonl`이 여기 쌓인다.
- **`.gitignore`에 `reclassify_work/` 추가** — 이 저장소는 GitHub Pages 호스팅을
  위해 public이고(메모리 [[project_review_integration_sheet]] 참고), 이 폴더에는
  실제 고객 리뷰 원문이 그대로 들어가므로 커밋 대상에서 제외한다.

### `리뷰 통합 시트/CLAUDE.md` (신규)

"CS영상 교육" 폴더 패턴과 동일하게, 이 폴더 전용 Claude 작업 지침을 둔다. 내용:
- `/loop` 주기마다 수행할 3단계 절차(위 아키텍처 그대로).
- `[재분류요청].json` / `[재분류결과].json` 형식 명세(아래).
- 판단 기준: 오늘 실측한 3가지 오분류 패턴을 명시.
  1. 증상·통증 어휘(통증/염증/걱정/스트레스 등)가 "내원 사유 설명"인지 "서비스에
     대한 불만"인지 문맥으로 구분한다. 전자는 부정 신호로 보지 않는다.
  2. "~하지만 참을만/괜찮았다" 같은 양보구문은 최종 결론(뒤 절)을 따른다.
  3. 전체 흐름이 재방문 의사·추천·감사 표현으로 끝나면 중간에 부정 단어가
     섞여 있어도 전체는 긍정으로 판단한다.
- 루트 CLAUDE.md에는 이 폴더의 존재와 역할을 한 줄로만 참조(CS영상 교육 항목과
  동일한 방식).

## `[재분류요청].json` 형식

```json
{
  "generated_at": "2026-09-21T10:00:00+09:00",
  "candidates": [
    {
      "id": 0,
      "hospital_id": "gangnam_jstar",
      "channel": "네이버",
      "content": "피부에 염증성 트러블 올라올 때마다...",
      "current_sentiment": "부정",
      "current_score": -4,
      "current_matched_words": ["염증", "염증", "스트레스", "친절"]
    }
  ]
}
```

## `[재분류결과].json` 형식 (Claude가 작성)

```json
{
  "reviewed_at": "2026-09-21T10:05:00+09:00",
  "results": [
    {
      "id": 0,
      "sentiment": "긍정",
      "confirmed": true,
      "note": "염증/스트레스는 내원 사유 설명이며 전체 흐름은 재방문 의사로 끝남"
    }
  ]
}
```

- `id`는 요청 파일의 `id`와 그대로 매칭(내용이 아니라 인덱스로 매칭 — 검수 단계
  자체의 매칭은 단순하게, 실제 시트 행 찾기만 `(channel, content)` 키 사용).
- `sentiment`: `"긍정"|"중립"|"부정"` 중 하나.
- `confirmed`: 시트에 그대로 반영되는 최종 확신 플래그. Claude의 판단은 항상
  `true`로 쓴다(애매하면 `"중립"`으로 판단하고 `confirmed=true` — 규칙기반의
  `confirmed=False`와 달리, 이 단계는 사람 대신 최종 판단을 내리는 단계이므로
  "판단 보류" 상태를 두지 않는다).
- `note`: 로그에만 남고 시트에는 안 씀. 왜 이렇게 판단했는지 근거.
- 시트 반영 시 `method`는 무조건 `"claude_review"`로 덮어쓴다 — 헤더 스키마 변경
  없이 "이미 검수 완료" 표시를 겸하며, 다음 `--export`에서 `method=="lexicon"`
  필터에 안 걸려 자연히 재검수 대상에서 빠진다.

## 에러 처리

- `--apply`에서 결과의 `(channel, content)`가 시트에서 안 찾아지면(그 사이 시트가
  바뀌었거나 사람이 직접 수정한 경우) 해당 건은 건너뛰고 경고 출력, 나머지 계속
  진행. `main.py`의 "채널 하나 실패해도 나머지는 진행" 원칙과 동일.
- 시트 헤더 불일치는 기존 `sheets_writer.ensure_header`가 이미 예외를 던짐 — 그대로
  재사용.
- `[재분류요청].json`이 없는데 `--apply`를 실행하면 명확한 에러 메시지로 중단.

## 테스트

- `test_reclassify.py`: `find_candidates`(method 필터링), `apply_results`(매칭·
  컬럼 갱신·매칭 실패 skip·로그 append)를 가짜 worksheet/시트 데이터로 단위 테스트
  (`test_sheets_writer.py`의 가짜 워크시트 패턴 재사용).
- `sheets_writer.update_sentiment` 단위 테스트: 지정된 3개 컬럼만 바뀌고 나머지는
  안 바뀌는지 확인.

## 관련 메모리

[[project_review_integration_sheet]], [[feedback_no_stealth_scraping_no_fake_data]],
[[feedback_pei_raw_data_no_silent_overwrite]] (원본 컬럼 절대 미수정 원칙과 동일선상)
