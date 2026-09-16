import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch
import main

_FULL_CHANNELS = {
    "naver_place_url": "https://m.place.naver.com/hospital/1/review/visitor",
    "kakao_place_url": "https://place.map.kakao.com/1",
    "google_place_id": "0x1:0x1",
}


def test_collect_hospital_aggregates_all_channels():
    hospital = {"hospital_id": "gangnam_jstar", "hospital_name": "강남제이스타의원", "channels": _FULL_CHANNELS}
    with patch("main.naver.collect_full", return_value=[{"channel": "네이버", "content": "좋아요"}]), \
         patch("main.kakao.collect_full", return_value=[{"channel": "카카오맵", "content": "별로예요"}]), \
         patch("main.google.collect_full", return_value=[{"channel": "구글", "content": "그저 그래요"}]):
        raw, errors = main.collect_hospital(hospital)
    assert len(raw) == 3, f"실제: {raw}"
    assert errors == [], f"실제: {errors}"
    print("PASS: test_collect_hospital_aggregates_all_channels")


def test_collect_hospital_isolates_single_channel_failure():
    hospital = {"hospital_id": "gangnam_jstar", "hospital_name": "강남제이스타의원", "channels": _FULL_CHANNELS}

    def boom(_hospital):
        raise ValueError("차단됨")

    with patch("main.naver.collect_full", side_effect=boom), \
         patch("main.kakao.collect_full", return_value=[{"channel": "카카오맵", "content": "별로예요"}]), \
         patch("main.google.collect_full", return_value=[{"channel": "구글", "content": "그저 그래요"}]):
        raw, errors = main.collect_hospital(hospital)
    assert len(raw) == 2, f"실제: {raw}"
    assert len(errors) == 1, f"실제: {errors}"
    assert "차단됨" in errors[0]
    print("PASS: test_collect_hospital_isolates_single_channel_failure")


def test_collect_hospital_all_channels_fail_returns_empty_list_not_exception():
    hospital = {"hospital_id": "gangnam_jstar", "hospital_name": "강남제이스타의원", "channels": _FULL_CHANNELS}

    def boom(_hospital):
        raise ValueError("실패")

    with patch("main.naver.collect_full", side_effect=boom), \
         patch("main.kakao.collect_full", side_effect=boom), \
         patch("main.google.collect_full", side_effect=boom):
        raw, errors = main.collect_hospital(hospital)
    assert raw == [], f"실제: {raw}"
    assert len(errors) == 3, f"실제: {errors}"
    print("PASS: test_collect_hospital_all_channels_fail_returns_empty_list_not_exception")


def test_collect_hospital_skips_channel_with_missing_url():
    # 경쟁병원처럼 일부 채널 URL을 못 찾은 경우, 그 채널은 호출조차 하지 않고
    # 조용히 건너뛴다(에러로 취급하지 않는다) — 도다나/고은미래의원의 실제 상황.
    hospital = {
        "hospital_id": "comp_dodana",
        "hospital_name": "도다나피부과의원",
        "channels": {
            "naver_place_url": "",
            "kakao_place_url": "https://place.map.kakao.com/262226489",
            "google_place_id": "0x3563758ac4f80f23:0x18d044a90c353c30",
        },
    }
    with patch("main.naver.collect_full") as mock_naver, \
         patch("main.kakao.collect_full", return_value=[{"channel": "카카오맵", "content": "좋아요"}]), \
         patch("main.google.collect_full", return_value=[{"channel": "구글", "content": "좋아요"}]):
        raw, errors = main.collect_hospital(hospital)
    mock_naver.assert_not_called()
    assert len(raw) == 2, f"실제: {raw}"
    assert errors == [], f"채널 미설정은 에러가 아니어야 함: {errors}"
    print("PASS: test_collect_hospital_skips_channel_with_missing_url")


def test_load_competitors_reads_config():
    competitors = main.load_competitors()
    ids = [c["hospital_id"] for c in competitors]
    assert "comp_audrey" in ids and "comp_dodana" in ids, f"실제: {ids}"
    assert len(competitors) == 5, f"실제: {len(competitors)}"
    dodana = next(c for c in competitors if c["hospital_id"] == "comp_dodana")
    assert dodana["hospital_name"] == "도다나피부과의원"
    assert dodana["channels"]["naver_place_url"] == ""
    print("PASS: test_load_competitors_reads_config")


if __name__ == "__main__":
    test_collect_hospital_aggregates_all_channels()
    test_collect_hospital_isolates_single_channel_failure()
    test_collect_hospital_all_channels_fail_returns_empty_list_not_exception()
    test_collect_hospital_skips_channel_with_missing_url()
    test_load_competitors_reads_config()
