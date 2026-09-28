# CLAUDE.md — 리뷰 통합 시트

이 폴더 전용 작업 지침이다. 전체 아키텍처·배경은 루트 CLAUDE.md와 상위 메모리
(`project_review_integration_sheet`, `project_review_reclassify_step_design`)를 참고한다.

## 이 폴더의 두 파이프라인

1. **`main.py`** — 매일 13:00 KST GitHub Actions가 완전 무인으로 실행하는 수집
   파이프라인(collectors → dedup → `classifier/rule_based.py` → Sheets append).
   이 폴더 작업 중 절대 건드리지 않는다(설계상 고정).
2. **`reclassify.py`** — Claude Code 세션이 켜져 있을 때만 도는 검수(재분류)
   파이프라인. `method=="lexicon"`인 시트 행(규칙기반 감성분류)을 Claude가 다시
   판단해 `sentiment`/`confirmed`/`method` 컬럼만 갱신한다. 아래는 이 파이프라인
   전용 절차다.

## `/loop` 주기마다 수행할 절차

```
python reclassify.py --export
    → reclassify_work/[재분류요청].json 생성 (후보 0건이면 파일 없이 종료)

Claude Code가 JSON을 읽고 판단        ← Claude의 몫
    → reclassify_work/[재분류결과].json 작성

python reclassify.py --apply
    → 결과를 시트에 반영, reclassify_work/reclassify_log.jsonl에 변경 로그 추가
```

`GOOGLE_SHEET_ID`/`GCP_SA_KEY` 환경변수가 필요하다(`main.py`와 동일).
`[재분류요청].json`이 없으면(후보 0건) 그 주기는 판단 없이 건너뛴다.

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

- `id`는 요청 파일의 `id`와 그대로 매칭한다(인덱스 매칭 — 실제 시트 행 찾기는
  `reclassify.py`가 `(channel, content)`로 별도 처리한다).
- `sentiment`: `"긍정"|"중립"|"부정"` 중 하나.
- `confirmed`: 항상 `true`로 쓴다. 애매하면 `"중립"`으로 판단하고 `confirmed=true`
  — 이 단계는 사람 대신 최종 판단을 내리는 단계이므로 "판단 보류" 상태를 두지 않는다.
- `note`: 로그에만 남고 시트에는 안 쓴다. 판단 근거를 반드시 적는다.
- `results`에 없는 `id`(판단을 건너뛴 후보)는 다음 주기에 다시 후보로 나온다.

## 판단 기준 (실측된 규칙기반 분류기의 오분류 패턴)

`classifier/rule_based.py`는 형태소분석·문맥 이해 없는 bag-of-words 감성사전
합산 방식이라, 2026-09-21 실측으로 아래 3가지 오분류가 확인되었다. 재분류 시
반드시 이 기준으로 판단한다.

1. **증상·통증 어휘는 문맥으로 구분한다**: 통증/염증/걱정/스트레스 등은 "서비스에
   대한 불만"이 아니라 "내원 사유 설명"일 수 있다(예: "염증 때문에 병원 갔는데
   친절해서 좋았어요"). 후자는 부정 신호로 보지 않는다.
2. **양보구문은 결론(뒤 절)을 따른다**: "아팠지만 참을만했다/괜찮았다" 같은 문장은
   앞 절의 부정 단어가 아니라 뒤 절의 결론으로 감성을 판단한다.
3. **전체 흐름이 우선이다**: 재방문 의사·추천·감사 표현으로 끝나면, 중간에 부정
   단어가 섞여 있어도 전체는 긍정으로 판단한다.

애매하되 위 세 패턴에 해당하지 않으면 `"중립"`으로 판단한다(추측으로 긍정/부정을
단정하지 않는다 — 루트 CLAUDE.md의 "데이터 없음의 정직한 표기" 원칙과 동일선상).

## 경쟁 병원 온보딩 — 네이버 플레이스 ID

네이버는 스크립트 검색에 캡차를 요구해(2026-09-28 실측) 플레이스 ID 자동 조회가
불가능하다. 우회하지 않는다. 신규 경쟁 병원을 `config/competitors_config.json`에
추가하면(`naver_place_url`은 빈 값) 다음 순서로 채운다.

```
python find_naver_place_ids.py --make-manual naver_place_manual.json
    → naver_place_manual.json + naver_place_manual.html(브라우저 확인 페이지) 생성
사람이 .html을 브라우저로 열어 병원별 ID 확인·입력 → [결과 JSON 복사] → .json 덮어쓰기
python find_naver_place_ids.py --manual naver_place_manual.json   # 형식 검증 후 반영(백업 생성)
```

- ID가 없는 동안에도 수집은 멈추지 않는다(네이버 채널만 건너뛰고 카카오·구글은 수집).
- 예약 URL(`booking.naver.com`)·단축 URL(`naver.me`)은 플레이스 ID가 아니다.
  `collectors/naver.py`가 해당 채널을 실패로 기록하고 Actions에 경고를 띄운다.
- 자사 고객 병원은 온보딩 시 병원에 스마트플레이스 URL을 직접 받는다.

## 보안

이 저장소(`review-integration-dashboard`)는 GitHub Pages 무료 호스팅을 위해
**public**이다. `reclassify_work/`에는 실제 고객 리뷰 원문이 그대로 들어가므로
`.gitignore`에 이미 등록되어 있다 — 이 폴더를 절대 커밋하지 않는다.
