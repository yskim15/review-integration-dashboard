import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch
from collectors.base import safe_run, stagger_offset_seconds, polite_sleep, RANDOM_SLEEP_RANGE


def test_safe_run_success():
    result, err = safe_run("gangnam_jstar", "네이버", lambda: [1, 2, 3])
    assert result == [1, 2, 3], f"결과 불일치: {result}"
    assert err is None, f"에러 없어야 하는데: {err}"
    print("PASS: test_safe_run_success")


def test_safe_run_failure_isolated():
    def boom():
        raise ValueError("차단됨")

    result, err = safe_run("gangnam_jstar", "네이버", boom)
    assert result is None, f"실패 시 result는 None이어야: {result}"
    assert "차단됨" in err, f"원본 예외 메시지가 포함돼야: {err}"
    assert "gangnam_jstar" in err and "네이버" in err, f"병원/채널 식별자가 포함돼야: {err}"
    print("PASS: test_safe_run_failure_isolated")


def test_stagger_offset_seconds():
    assert stagger_offset_seconds(0) == 0
    assert stagger_offset_seconds(1) == 15
    assert stagger_offset_seconds(2, gap_seconds=10) == 20
    print("PASS: test_stagger_offset_seconds")


def test_polite_sleep_within_range():
    with patch("collectors.base.time.sleep") as mock_sleep:
        polite_sleep()
    assert mock_sleep.call_count == 1, "sleep이 정확히 1번 호출돼야"
    slept_seconds = mock_sleep.call_args[0][0]
    assert RANDOM_SLEEP_RANGE[0] <= slept_seconds <= RANDOM_SLEEP_RANGE[1], (
        f"sleep 시간이 RANDOM_SLEEP_RANGE 범위를 벗어남: {slept_seconds}"
    )
    print("PASS: test_polite_sleep_within_range")


if __name__ == "__main__":
    test_safe_run_success()
    test_safe_run_failure_isolated()
    test_stagger_offset_seconds()
    test_polite_sleep_within_range()
