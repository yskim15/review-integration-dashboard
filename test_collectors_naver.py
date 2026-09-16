import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch, MagicMock
from collectors.naver import _extract_place_id, _via_graphql, collect_full, NaverBlockedError


def test_extract_place_id_hospital_segment():
    url = "https://m.place.naver.com/hospital/31605858/review/visitor"
    assert _extract_place_id(url) == "31605858", f"실제: {_extract_place_id(url)}"
    print("PASS: test_extract_place_id_hospital_segment")


def test_extract_place_id_no_digits():
    url = "https://m.place.naver.com/place/review/visitor"
    assert _extract_place_id(url) is None
    print("PASS: test_extract_place_id_no_digits")


def _fake_response(status_code=200, text="{}", json_value=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_value is not None:
        resp.json.return_value = json_value
    return resp


def test_via_graphql_success():
    json_value = [{
        "data": {
            "visitorReviews": {
                "items": [{
                    "id": "r1",
                    "rating": None,
                    "body": "친절하고 좋았어요",
                    "created": "2026-08-01",
                    "visitCount": 1,
                    "author": {"nickname": "홍길동"},
                    "reply": {"body": "감사합니다"},
                }],
                "total": 1,
            }
        }
    }]
    fake = _fake_response(json_value=json_value)
    with patch("collectors.naver.requests.post", return_value=fake):
        reviews, err = _via_graphql("31605858")
    assert err is None, f"에러 없어야: {err}"
    assert len(reviews) == 1
    r = reviews[0]
    assert r["channel"] == "네이버"
    assert r["author"] == "홍길동"
    assert r["content"] == "친절하고 좋았어요"
    assert r["has_reply"] is True
    print("PASS: test_via_graphql_success")


def test_via_graphql_blocked():
    fake = _fake_response(status_code=429, text="captcha")
    with patch("collectors.naver.requests.post", return_value=fake):
        reviews, err = _via_graphql("31605858")
    assert reviews is None
    assert "429" in err or "차단" in err, f"실제: {err}"
    print("PASS: test_via_graphql_blocked")


def test_collect_full_raises_when_place_id_missing():
    hospital = {"channels": {"naver_place_url": "https://m.place.naver.com/place/review/visitor"}}
    raised = False
    try:
        collect_full(hospital)
    except NaverBlockedError:
        raised = True
    assert raised, "businessId 추출 실패 시 NaverBlockedError가 발생해야 함"
    print("PASS: test_collect_full_raises_when_place_id_missing")


def test_collect_full_success_via_graphql():
    hospital = {"channels": {"naver_place_url": "https://m.place.naver.com/hospital/31605858/review/visitor"}}
    fake = _fake_response(json_value=[{"data": {"visitorReviews": {"items": [], "total": 0}}}])
    with patch("collectors.naver.polite_sleep"), patch("collectors.naver.requests.post", return_value=fake):
        reviews = collect_full(hospital)
    assert reviews == [], f"실제: {reviews}"
    print("PASS: test_collect_full_success_via_graphql")


if __name__ == "__main__":
    test_extract_place_id_hospital_segment()
    test_extract_place_id_no_digits()
    test_via_graphql_success()
    test_via_graphql_blocked()
    test_collect_full_raises_when_place_id_missing()
    test_collect_full_success_via_graphql()
