"""수집기 공통 유틸리티 — 안티블로킹(랜덤 지연)과 실패 격리를 담당한다.

각 채널 수집기(naver.py/kakao.py/google.py)는 polite_sleep()을 그대로
재사용한다. safe_run()은 "리뷰 컨트롤타워" 프로젝트의 동명 함수와 달리
웹푸시 알림을 보내지 않는다 — 이 프로젝트는 실시간 알림이 없다는 것이
설계문서에서 확정됐으므로, 실패 시 (None, 에러메시지) 튜플을 반환해
호출부(향후 GitHub Actions 워크플로우 스크립트)가 로그로 남기게 한다.
"""

import random
import time

RANDOM_SLEEP_RANGE = (2.0, 3.0)


def polite_sleep():
    time.sleep(random.uniform(*RANDOM_SLEEP_RANGE))


def safe_run(hospital_id, channel, func, *args, **kwargs):
    """수집 함수를 감싸서, 실패해도 배치 전체가 멈추지 않게 한다.

    실패 시 (None, 에러메시지)를 반환한다 — 호출부는 에러메시지를 로그로
    남기고 해당 병원/채널만 건너뛰면 된다.
    """
    try:
        return func(*args, **kwargs), None
    except Exception as e:  # noqa: BLE001 - 수집기는 어떤 예외든 배치를 죽이면 안 된다
        return None, f"[{hospital_id}/{channel}] 수집 실패: {e}"


def stagger_offset_seconds(hospital_index, gap_seconds=15):
    """병원 인덱스 기반으로 시작 시각을 분산시켜 동시 요청 폭주를 막는다."""
    return hospital_index * gap_seconds
