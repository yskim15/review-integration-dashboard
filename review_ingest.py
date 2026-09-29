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
