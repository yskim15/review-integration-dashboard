import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch
import main


def test_collect_hospital_aggregates_all_channels():
    hospital = {"hospital_id": "gangnam_jstar", "hospital_name": "강남제이스타의원", "channels": {}}
    with patch("main.naver.collect_full", return_value=[{"channel": "네이버", "content": "좋아요"}]), \
         patch("main.kakao.collect_full", return_value=[{"channel": "카카오맵", "content": "별로예요"}]), \
         patch("main.google.collect_full", return_value=[{"channel": "구글", "content": "그저 그래요"}]):
        raw, errors = main.collect_hospital(hospital)
    assert len(raw) == 3, f"실제: {raw}"
    assert errors == [], f"실제: {errors}"
    print("PASS: test_collect_hospital_aggregates_all_channels")


def test_collect_hospital_isolates_single_channel_failure():
    hospital = {"hospital_id": "gangnam_jstar", "hospital_name": "강남제이스타의원", "channels": {}}

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
    hospital = {"hospital_id": "gangnam_jstar", "hospital_name": "강남제이스타의원", "channels": {}}

    def boom(_hospital):
        raise ValueError("실패")

    with patch("main.naver.collect_full", side_effect=boom), \
         patch("main.kakao.collect_full", side_effect=boom), \
         patch("main.google.collect_full", side_effect=boom):
        raw, errors = main.collect_hospital(hospital)
    assert raw == [], f"실제: {raw}"
    assert len(errors) == 3, f"실제: {errors}"
    print("PASS: test_collect_hospital_all_channels_fail_returns_empty_list_not_exception")


if __name__ == "__main__":
    test_collect_hospital_aggregates_all_channels()
    test_collect_hospital_isolates_single_channel_failure()
    test_collect_hospital_all_channels_fail_returns_empty_list_not_exception()
