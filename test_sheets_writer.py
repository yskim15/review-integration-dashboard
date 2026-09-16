import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import sheets_writer


class FakeWorksheet:
    """gspread Worksheet를 흉내낸 가짜 객체. values[0]이 헤더 행이다."""

    def __init__(self, initial_values=None):
        self.values = [list(row) for row in (initial_values or [])]

    def get_all_values(self):
        return self.values

    def append_row(self, row):
        self.values.append(list(row))

    def append_rows(self, rows, value_input_option=None):
        for row in rows:
            self.values.append(list(row))

    def get_all_records(self):
        if not self.values:
            return []
        header = self.values[0]
        return [dict(zip(header, row)) for row in self.values[1:]]


def test_ensure_header_writes_header_when_sheet_empty():
    ws = FakeWorksheet()
    sheets_writer.ensure_header(ws)
    assert ws.values == [sheets_writer.HEADER], f"실제: {ws.values}"
    print("PASS: test_ensure_header_writes_header_when_sheet_empty")


def test_ensure_header_noop_when_header_already_correct():
    ws = FakeWorksheet(initial_values=[sheets_writer.HEADER, ["gangnam_jstar", "네이버", "홍길동", "", "2026-08-01", "좋아요", False, "긍정", True, 2, "친절", "lexicon", "2026-09-16T00:00:00"]])
    sheets_writer.ensure_header(ws)
    assert len(ws.values) == 2, "헤더가 중복 추가되면 안 됨"
    print("PASS: test_ensure_header_noop_when_header_already_correct")


def test_ensure_header_raises_when_mismatched():
    ws = FakeWorksheet(initial_values=[["엉뚱한", "헤더"]])
    raised = False
    try:
        sheets_writer.ensure_header(ws)
    except ValueError:
        raised = True
    assert raised, "헤더가 예상과 다르면 조용히 넘어가지 말고 예외를 던져야 함"
    print("PASS: test_ensure_header_raises_when_mismatched")


def test_review_to_row():
    review = {"channel": "네이버", "author": "홍길동", "rating": None, "date": "2026-08-01", "content": "친절하고 좋았어요", "has_reply": False}
    classification = {"sentiment": "긍정", "confirmed": True, "score": 2, "matched_words": ["친절"], "method": "lexicon"}
    row = sheets_writer.review_to_row("gangnam_jstar", review, classification, "2026-09-16T00:00:00")
    assert row == [
        "gangnam_jstar", "네이버", "홍길동", "", "2026-08-01", "친절하고 좋았어요", False,
        "긍정", True, 2, "친절", "lexicon", "2026-09-16T00:00:00",
    ], f"실제: {row}"
    print("PASS: test_review_to_row")


def test_review_to_row_with_rating_and_no_matched_words():
    review = {"channel": "카카오맵", "author": "이영희", "rating": 1, "date": "2026.07.15.", "content": "별로였어요", "has_reply": True}
    classification = {"sentiment": "부정", "confirmed": True, "score": None, "matched_words": [], "method": "rating"}
    row = sheets_writer.review_to_row("gangnam_jstar", review, classification, "2026-09-16T00:00:00")
    assert row == [
        "gangnam_jstar", "카카오맵", "이영희", 1, "2026.07.15.", "별로였어요", True,
        "부정", True, "", "", "rating", "2026-09-16T00:00:00",
    ], f"실제: {row}"
    print("PASS: test_review_to_row_with_rating_and_no_matched_words")


def test_append_reviews_writes_rows_and_returns_count():
    ws = FakeWorksheet(initial_values=[sheets_writer.HEADER])
    review = {"channel": "네이버", "author": "홍길동", "rating": None, "date": "2026-08-01", "content": "좋아요", "has_reply": False}
    classification = {"sentiment": "긍정", "confirmed": False, "score": 0, "matched_words": [], "method": "lexicon"}
    count = sheets_writer.append_reviews(ws, "gangnam_jstar", [(review, classification)], "2026-09-16T00:00:00")
    assert count == 1
    assert len(ws.values) == 2, f"실제: {ws.values}"
    print("PASS: test_append_reviews_writes_rows_and_returns_count")


def test_append_reviews_noop_when_empty_list():
    ws = FakeWorksheet(initial_values=[sheets_writer.HEADER])
    count = sheets_writer.append_reviews(ws, "gangnam_jstar", [], "2026-09-16T00:00:00")
    assert count == 0
    assert len(ws.values) == 1, "빈 목록이면 시트에 아무것도 추가되면 안 됨"
    print("PASS: test_append_reviews_noop_when_empty_list")


def test_read_existing_reviews_returns_records():
    ws = FakeWorksheet(initial_values=[
        sheets_writer.HEADER,
        ["gangnam_jstar", "네이버", "홍길동", "", "2026-08-01", "좋아요", False, "긍정", True, 2, "친절", "lexicon", "2026-09-16T00:00:00"],
    ])
    records = sheets_writer.read_existing_reviews(ws)
    assert len(records) == 1
    assert records[0]["channel"] == "네이버"
    assert records[0]["content"] == "좋아요"
    assert records[0]["hospital_id"] == "gangnam_jstar"
    print("PASS: test_read_existing_reviews_returns_records")


if __name__ == "__main__":
    test_ensure_header_writes_header_when_sheet_empty()
    test_ensure_header_noop_when_header_already_correct()
    test_ensure_header_raises_when_mismatched()
    test_review_to_row()
    test_review_to_row_with_rating_and_no_matched_words()
    test_append_reviews_writes_rows_and_returns_count()
    test_append_reviews_noop_when_empty_list()
    test_read_existing_reviews_returns_records()
