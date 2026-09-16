"""Google Sheets 리더/라이터.

서비스 계정 인증과 실제 Sheets API 호출(connect())은 유닛테스트 대상이 아니다
(수동으로 실제 계정으로 검증한다). 행 변환·헤더 검증·append 로직은 gspread
워크시트를 흉내낸 가짜 객체로 테스트한다.
"""

import json

HEADER = [
    "hospital_id", "channel", "author", "rating", "date", "content", "has_reply",
    "sentiment", "confirmed", "score", "matched_words", "method", "collected_at",
]


def _row_is_blank(row):
    return all(not str(cell).strip() for cell in row)


def ensure_header(worksheet):
    """시트가 비어 있으면 A1에 헤더를 쓰고, 이미 있으면 정확히 일치하는지만
    확인한다. 다르면 조용히 덮어쓰지 않고 예외를 던진다 — 잘못된 시트에 계속
    쓰는 사고를 막는다.

    새로 만든 Google Sheet는 get_all_values()가 완전히 빈 리스트가 아니라
    빈 행 하나([[]])를 반환하기도 한다(실제 GitHub Actions 실행에서 확인됨) —
    그래서 "리스트가 비었는지"가 아니라 "첫 행이 비었는지"로 판단한다."""
    values = worksheet.get_all_values()
    if not values or _row_is_blank(values[0]):
        worksheet.update("A1", [HEADER])
        return
    if values[0] != HEADER:
        raise ValueError(f"시트 헤더가 예상과 다릅니다: {values[0]}")


def review_to_row(hospital_id, review, classification, collected_at):
    rating = review.get("rating")
    score = classification.get("score")
    return [
        hospital_id,
        review.get("channel"),
        review.get("author"),
        rating if rating is not None else "",
        review.get("date"),
        review.get("content"),
        bool(review.get("has_reply", False)),
        classification["sentiment"],
        classification["confirmed"],
        score if score is not None else "",
        ",".join(classification.get("matched_words") or []),
        classification["method"],
        collected_at,
    ]


def append_reviews(worksheet, hospital_id, reviews_with_classification, collected_at):
    """reviews_with_classification: [(review_dict, classification_dict), ...]
    반환값: 실제로 추가된 행 수."""
    rows = [review_to_row(hospital_id, review, classification, collected_at) for review, classification in reviews_with_classification]
    if rows:
        worksheet.append_rows(rows, value_input_option="RAW")
    return len(rows)


def read_existing_reviews(worksheet):
    """헤더를 키로 하는 dict 목록을 반환한다(hospital_id/channel/content 포함)."""
    return worksheet.get_all_records()


def connect(sheet_id, credentials_json):
    """서비스 계정 JSON(문자열)으로 인증해 첫 번째 워크시트를 반환한다.
    실제 네트워크 호출이라 유닛테스트 대상이 아니다."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(json.loads(credentials_json), scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id).sheet1
