"""매일 자동 수집 파이프라인 진입점 (GitHub Actions에서 실행).

collectors(네이버/카카오/구글) -> dedup -> classifier(규칙기반) -> sheets_writer
순서로 병원별 신규 리뷰를 Google Sheets에 append한다. 사람/Claude 세션 개입이
필요 없는 완전 무인 실행을 전제로 한다(설계문서 2절 확정사항).
"""

import argparse
import datetime
import json
import os
from pathlib import Path

import dedup
import sheets_writer
from classifier.rule_based import classify
from collectors import google, kakao, naver
from collectors.base import safe_run

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "hospitals_config.json"
COMPETITORS_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "competitors_config.json"

_CHANNEL_COLLECTORS = (
    ("네이버", naver, "naver_place_url"),
    ("카카오맵", kakao, "kakao_place_url"),
    ("구글", google, "google_place_id"),
)


def load_hospitals():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)["hospitals"]


def load_competitors():
    """경쟁 병원도 동일한 hospital 형태({hospital_id, hospital_name, channels})로
    반환해, collect_hospital 이하 파이프라인을 그대로 재사용할 수 있게 한다.
    naver_place_url이 빈 문자열인 곳은 그 채널을 못 찾은 것 — 채널만 건너뛴다."""
    if not COMPETITORS_CONFIG_PATH.exists():
        return []
    with open(COMPETITORS_CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [
        {
            "hospital_id": c["competitor_id"],
            "hospital_name": c["name"],
            "channels": c["channels"],
        }
        for c in data.get("competitors", [])
    ]


def collect_hospital(hospital):
    """모든 채널을 수집해 (전체 리뷰 목록, 실패 메시지 목록)을 반환한다.
    채널 URL이 설정 안 된 경우(경쟁병원 일부처럼)는 호출 자체를 건너뛰고
    에러로 취급하지 않는다. 설정된 채널이 실패하면 나머지는 계속 진행한다
    (설계문서 7절)."""
    raw_reviews = []
    errors = []
    channels = hospital.get("channels", {})
    for channel_name, collector_module, config_key in _CHANNEL_COLLECTORS:
        if not channels.get(config_key):
            continue
        result, err = safe_run(hospital["hospital_id"], channel_name, collector_module.collect_full, hospital)
        if err:
            errors.append(err)
        else:
            raw_reviews.extend(result)
    return raw_reviews, errors


def run(hospital_id_filter=None):
    hospitals = load_hospitals() + load_competitors()
    if hospital_id_filter:
        hospitals = [h for h in hospitals if h["hospital_id"] == hospital_id_filter]
        if not hospitals:
            print(f"등록되지 않은 hospital_id입니다: {hospital_id_filter!r}")
            return

    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    credentials_json = os.environ["GCP_SA_KEY"]
    worksheet = sheets_writer.connect(sheet_id, credentials_json)
    sheets_writer.ensure_header(worksheet)

    all_existing = sheets_writer.read_existing_reviews(worksheet)
    collected_at = datetime.datetime.now().astimezone().isoformat()

    for hospital in hospitals:
        hospital_id = hospital["hospital_id"]
        raw_reviews, errors = collect_hospital(hospital)
        for err in errors:
            print(err)

        existing_for_hospital = [r for r in all_existing if r.get("hospital_id") == hospital_id]
        new_reviews = dedup.find_new_reviews(existing_for_hospital, raw_reviews)
        classified = [(review, classify(review)) for review in new_reviews]

        added = sheets_writer.append_reviews(worksheet, hospital_id, classified, collected_at)
        print(f"{hospital_id}: 수집 {len(raw_reviews)}건 중 신규 {added}건 반영 (실패 채널 {len(errors)}건)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="병원 리뷰 매일 자동 수집")
    parser.add_argument("--hospital", help="특정 hospital_id만 실행 (생략 시 전체 병원)")
    args = parser.parse_args()
    run(args.hospital)
