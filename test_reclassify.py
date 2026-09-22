import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

import reclassify
from test_sheets_writer import FakeWorksheet
import sheets_writer


def _row(hospital_id="gangnam_jstar", channel="네이버", content="좋아요", sentiment="부정", confirmed=True, score=-4, matched_words="염증,스트레스", method="lexicon"):
    return {
        "hospital_id": hospital_id, "channel": channel, "author": "홍길동", "rating": "",
        "date": "2026-08-01", "content": content, "has_reply": False,
        "sentiment": sentiment, "confirmed": confirmed, "score": score,
        "matched_words": matched_words, "method": method, "collected_at": "2026-09-16T00:00:00",
    }


def test_find_candidates_filters_lexicon_only():
    existing = [
        _row(method="lexicon"),
        _row(channel="카카오맵", content="별로예요", method="rating", matched_words=""),
    ]
    candidates = reclassify.find_candidates(existing)
    assert len(candidates) == 1, f"실제: {candidates}"
    assert candidates[0]["channel"] == "네이버"
    assert candidates[0]["id"] == 0
    print("PASS: test_find_candidates_filters_lexicon_only")


def test_find_candidates_splits_matched_words_into_list():
    existing = [_row(matched_words="염증,스트레스,친절")]
    candidates = reclassify.find_candidates(existing)
    assert candidates[0]["current_matched_words"] == ["염증", "스트레스", "친절"], f"실제: {candidates[0]}"
    print("PASS: test_find_candidates_splits_matched_words_into_list")


def test_find_candidates_empty_matched_words_becomes_empty_list():
    existing = [_row(matched_words="")]
    candidates = reclassify.find_candidates(existing)
    assert candidates[0]["current_matched_words"] == [], f"실제: {candidates[0]}"
    print("PASS: test_find_candidates_empty_matched_words_becomes_empty_list")


def test_export_for_claude_writes_json_and_returns_path():
    work_dir = tempfile.mkdtemp()
    try:
        candidates = reclassify.find_candidates([_row()])
        path = reclassify.export_for_claude(candidates, work_dir)
        assert path is not None
        assert os.path.exists(path)
        payload = json.loads(open(path, encoding="utf-8").read())
        assert "generated_at" in payload
        assert payload["candidates"] == candidates
        print("PASS: test_export_for_claude_writes_json_and_returns_path")
    finally:
        shutil.rmtree(work_dir)


def test_export_for_claude_returns_none_and_writes_no_file_when_no_candidates():
    work_dir = tempfile.mkdtemp()
    try:
        path = reclassify.export_for_claude([], work_dir)
        assert path is None
        assert not os.path.exists(os.path.join(work_dir, reclassify.REQUEST_FILENAME))
        print("PASS: test_export_for_claude_returns_none_and_writes_no_file_when_no_candidates")
    finally:
        shutil.rmtree(work_dir)


def test_apply_results_updates_matching_row_and_logs():
    work_dir = tempfile.mkdtemp()
    try:
        existing = [_row(content="염증 때문에 병원 갔는데 친절해서 좋았어요")]
        candidates = reclassify.find_candidates(existing)
        reclassify.export_for_claude(candidates, work_dir)

        result_payload = {
            "reviewed_at": "2026-09-22T10:00:00+09:00",
            "results": [{"id": 0, "sentiment": "긍정", "confirmed": True, "note": "내원 사유 설명일 뿐 불만 아님"}],
        }
        with open(os.path.join(work_dir, reclassify.RESULT_FILENAME), "w", encoding="utf-8") as f:
            json.dump(result_payload, f, ensure_ascii=False)

        ws = FakeWorksheet(initial_values=[sheets_writer.HEADER, sheets_writer.review_to_row(
            "gangnam_jstar",
            {"channel": "네이버", "author": "홍길동", "rating": None, "date": "2026-08-01",
             "content": "염증 때문에 병원 갔는데 친절해서 좋았어요", "has_reply": False},
            {"sentiment": "부정", "confirmed": True, "score": -4, "matched_words": ["염증", "스트레스"], "method": "lexicon"},
            "2026-09-16T00:00:00",
        )])

        updated = reclassify.apply_results(ws, existing, work_dir)

        assert updated == 1, f"실제: {updated}"
        assert ws.values[1][sheets_writer.HEADER.index("sentiment")] == "긍정"
        assert ws.values[1][sheets_writer.HEADER.index("confirmed")] is True
        assert ws.values[1][sheets_writer.HEADER.index("method")] == "claude_review"
        # score/matched_words는 그대로 남아야 한다
        assert ws.values[1][sheets_writer.HEADER.index("score")] == -4
        assert ws.values[1][sheets_writer.HEADER.index("matched_words")] == "염증,스트레스"

        log_path = os.path.join(work_dir, reclassify.LOG_FILENAME)
        assert os.path.exists(log_path)
        log_lines = open(log_path, encoding="utf-8").read().strip().splitlines()
        assert len(log_lines) == 1
        log_entry = json.loads(log_lines[0])
        assert log_entry["new_sentiment"] == "긍정"
        print("PASS: test_apply_results_updates_matching_row_and_logs")
    finally:
        shutil.rmtree(work_dir)


def test_apply_results_skips_when_row_not_found_in_existing_reviews():
    work_dir = tempfile.mkdtemp()
    try:
        existing = [_row(content="찾을 수 있는 리뷰")]
        candidates = reclassify.find_candidates(existing)
        reclassify.export_for_claude(candidates, work_dir)

        # existing_reviews를 apply 시점에 다른 내용으로 바꿔, 시트에서 매칭 실패를 재현
        existing_at_apply_time = [_row(content="그 사이 내용이 바뀐 리뷰")]

        result_payload = {"reviewed_at": "2026-09-22T10:00:00+09:00",
                           "results": [{"id": 0, "sentiment": "긍정", "confirmed": True, "note": ""}]}
        with open(os.path.join(work_dir, reclassify.RESULT_FILENAME), "w", encoding="utf-8") as f:
            json.dump(result_payload, f, ensure_ascii=False)

        ws = FakeWorksheet(initial_values=[sheets_writer.HEADER])
        updated = reclassify.apply_results(ws, existing_at_apply_time, work_dir)

        assert updated == 0, f"실제: {updated}"
        assert not os.path.exists(os.path.join(work_dir, reclassify.LOG_FILENAME))
        print("PASS: test_apply_results_skips_when_row_not_found_in_existing_reviews")
    finally:
        shutil.rmtree(work_dir)


def test_apply_results_raises_when_request_file_missing():
    work_dir = tempfile.mkdtemp()
    try:
        raised = False
        try:
            reclassify.apply_results(FakeWorksheet(), [], work_dir)
        except FileNotFoundError:
            raised = True
        assert raised, "요청 파일이 없으면 명확한 예외로 중단해야 함"
        print("PASS: test_apply_results_raises_when_request_file_missing")
    finally:
        shutil.rmtree(work_dir)


if __name__ == "__main__":
    test_find_candidates_filters_lexicon_only()
    test_find_candidates_splits_matched_words_into_list()
    test_find_candidates_empty_matched_words_becomes_empty_list()
    test_export_for_claude_writes_json_and_returns_path()
    test_export_for_claude_returns_none_and_writes_no_file_when_no_candidates()
    test_apply_results_updates_matching_row_and_logs()
    test_apply_results_skips_when_row_not_found_in_existing_reviews()
    test_apply_results_raises_when_request_file_missing()
