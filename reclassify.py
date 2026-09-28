"""Claude Code 검수(재분류) 단계.

`main.py`(매일 자동 수집, GitHub Actions, 완전 무인)와 별도로 동작한다.
Claude Code 세션이 켜져 있을 때만 /loop 등으로 주기 실행되어, method=="lexicon"인
시트 행(규칙기반 감성분류)을 Claude가 다시 판단해 sentiment/confirmed/method만
갱신한다. 설계: docs/superpowers/specs/2026-09-21-claude-reclassify-review-design.md
"""

import argparse
import datetime
import json
import os
from pathlib import Path

import sheets_writer

WORK_DIR = Path(__file__).resolve().parent / "reclassify_work"
REQUEST_FILENAME = "[재분류요청].json"
RESULT_FILENAME = "[재분류결과].json"
LOG_FILENAME = "reclassify_log.jsonl"


def find_candidates(existing_reviews):
    """method=="lexicon"인 행만 골라 Claude에게 보낼 후보 목록으로 변환한다."""
    candidates = []
    for review in existing_reviews:
        if review.get("method") != "lexicon":
            continue
        matched_words = review.get("matched_words") or ""
        candidates.append({
            "id": len(candidates),
            "hospital_id": review.get("hospital_id"),
            "channel": review.get("channel"),
            "content": review.get("content"),
            "current_sentiment": review.get("sentiment"),
            "current_score": review.get("score"),
            "current_matched_words": [w for w in matched_words.split(",") if w],
        })
    return candidates


def export_for_claude(candidates, work_dir):
    """[재분류요청].json을 work_dir에 쓰고 경로를 반환한다.
    후보가 없으면 파일을 만들지 않고 None을 반환한다."""
    if not candidates:
        return None
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / REQUEST_FILENAME
    payload = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(),
        "candidates": candidates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def apply_results(worksheet, existing_reviews, work_dir):
    """[재분류결과].json을 읽어 시트에 반영한다. 실제로 바뀐 행 수를 반환한다.

    (hospital_id, channel, content)가 같고 method=="lexicon"인 행을 시트 순서대로
    하나씩 배정해 existing_reviews에서 실제 시트 행을 찾는다. 그 사이
    시트가 바뀌어 못 찾으면 그 건은 건너뛰고 경고만 출력, 나머지는 계속 진행한다."""
    work_dir = Path(work_dir)
    request_path = work_dir / REQUEST_FILENAME
    result_path = work_dir / RESULT_FILENAME
    if not request_path.exists():
        raise FileNotFoundError(f"{REQUEST_FILENAME}가 없습니다. 먼저 --export를 실행하세요.")
    if not result_path.exists():
        raise FileNotFoundError(f"{RESULT_FILENAME}가 없습니다. Claude가 검수 결과를 작성했는지 확인하세요.")

    candidates_by_id = {c["id"]: c for c in json.loads(request_path.read_text(encoding="utf-8"))["candidates"]}
    results = json.loads(result_path.read_text(encoding="utf-8"))["results"]

    row_updates = []
    log_entries = []
    claimed_indexes = set()
    for result in sorted(results, key=lambda r: r["id"]):
        candidate = candidates_by_id.get(result["id"])
        if candidate is None:
            print(f"경고: 결과 id={result['id']}에 해당하는 요청 후보를 찾을 수 없어 건너뜁니다.")
            continue

        # 본문이 같은 짧은 리뷰("굿", "좋아요" 등)가 여러 행일 수 있어, 아직 lexicon이고
        # 이번 실행에서 쓰지 않은 행만 매칭한다 (2026-09-28 실측: 전부 첫 행에 반영되던 버그).
        row_number = None
        for index, review in enumerate(existing_reviews):
            if (index in claimed_indexes
                    or review.get("method") != "lexicon"
                    or review.get("hospital_id") != candidate["hospital_id"]
                    or review.get("channel") != candidate["channel"]
                    or review.get("content") != candidate["content"]):
                continue
            claimed_indexes.add(index)
            row_number = index + 2  # 헤더가 1행이므로 실제 데이터 행은 +2
            break
        if row_number is None:
            print(f"경고: channel={candidate['channel']!r} content={str(candidate['content'])[:20]!r}... 에 해당하는 "
                  f"시트 행을 찾을 수 없어 건너뜁니다 (그 사이 시트가 바뀌었을 수 있음).")
            continue

        classification = {
            "sentiment": result["sentiment"],
            "confirmed": result["confirmed"],
            "method": "claude_review",
        }
        row_updates.append((row_number, classification))
        log_entries.append({
            "reviewed_at": datetime.datetime.now().astimezone().isoformat(),
            "hospital_id": candidate["hospital_id"],
            "channel": candidate["channel"],
            "content": candidate["content"],
            "old_sentiment": candidate["current_sentiment"],
            "new_sentiment": result["sentiment"],
            "note": result.get("note", ""),
        })

    # 행마다 개별 API 호출하면 Sheets 쓰기 quota(분당 요청 수)를 초과할 수 있어
    # (2026-09-22 실측: 85행 x 3컬럼=255회 호출로 429 에러 발생) 한 번에 묶어 반영한다.
    sheets_writer.batch_update_sentiments(worksheet, row_updates)
    updated = len(row_updates)

    if log_entries:
        with open(work_dir / LOG_FILENAME, "a", encoding="utf-8") as f:
            for entry in log_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return updated


def run_export():
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    credentials_json = os.environ["GCP_SA_KEY"]
    worksheet = sheets_writer.connect(sheet_id, credentials_json)
    existing = sheets_writer.read_existing_reviews(worksheet)
    candidates = find_candidates(existing)
    path = export_for_claude(candidates, WORK_DIR)
    if path:
        print(f"재분류 후보 {len(candidates)}건 -> {path}")
    else:
        print("재분류 대상(method==lexicon)이 없습니다.")


def run_apply():
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    credentials_json = os.environ["GCP_SA_KEY"]
    worksheet = sheets_writer.connect(sheet_id, credentials_json)
    existing = sheets_writer.read_existing_reviews(worksheet)
    updated = apply_results(worksheet, existing, WORK_DIR)
    print(f"{updated}건 반영 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="리뷰 감성 재분류(Claude Code 검수)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true", help="재분류 후보를 JSON으로 내보낸다")
    group.add_argument("--apply", action="store_true", help="Claude가 작성한 결과를 시트에 반영한다")
    args = parser.parse_args()

    if args.export:
        run_export()
    else:
        run_apply()
