"""find_naver_place_ids.py 매칭 로직 테스트 (네트워크 호출 없음, 가상 병원명 사용)."""

from find_naver_place_ids import jibun_key, names_match, needs_lookup, parse_place_id, pick_match, render_check_page

COMP = {"name": "가나다피부과의원", "address": "강원특별자치도 원주시 가상동 100-2"}


def test_jibun_key():
    assert jibun_key("강원특별자치도 원주시 가상동 100-2") == "가상동 100-2"
    assert jibun_key("강원 원주시 가상동 100-2 3층") == "가상동 100-2"
    assert jibun_key("강원특별자치도 원주시 가상로 12") is None
    print("PASS: test_jibun_key")


def test_needs_lookup():
    assert needs_lookup("")
    assert needs_lookup("https://booking.naver.com/booking/13/bizes/1")
    assert not needs_lookup("https://m.place.naver.com/hospital/1/review/visitor")
    print("PASS: test_needs_lookup")


def test_names_match():
    assert names_match("가나다피부과의원", "가나다피부과")
    assert names_match("라마의원 원주점", "라마의원")
    assert not names_match("가나다피부과의원", "바사피부과의원")
    print("PASS: test_names_match")


def test_pick_match_single_confirmed():
    items = [
        {"id": "111", "name": "가나다피부과", "address": "강원 원주시 가상동 100-2"},
        {"id": "222", "name": "바사피부과의원", "address": "강원 원주시 가상동 100-2"},  # 같은 건물 다른 병원
    ]
    assert pick_match(COMP, items) == ("111", "확정(지번주소+상호명 일치)")
    print("PASS: test_pick_match_single_confirmed")


def test_pick_match_same_name_other_address_rejected():
    items = [{"id": "333", "name": "가나다피부과의원", "address": "서울 강남구 가상동 5"}]
    place_id, reason = pick_match(COMP, items)
    assert place_id is None and reason == "일치 후보 없음"
    print("PASS: test_pick_match_same_name_other_address_rejected")


def test_pick_match_ambiguous_rejected():
    items = [
        {"id": "111", "name": "가나다피부과", "address": "강원 원주시 가상동 100-2"},
        {"id": "444", "name": "가나다피부과의원 2관", "address": "강원 원주시 가상동 100-2"},
    ]
    place_id, reason = pick_match(COMP, items)
    assert place_id is None and "2개" in reason
    print("PASS: test_pick_match_ambiguous_rejected")


def test_parse_place_id():
    assert parse_place_id("12345") == "12345"
    assert parse_place_id(" https://m.place.naver.com/hospital/12345/review/visitor ") == "12345"
    assert parse_place_id("https://map.naver.com/p/search/abc/place/67890?c=15") == "67890"
    assert parse_place_id("https://map.naver.com/p/entry/place/67890") == "67890"
    assert parse_place_id("https://pcmap.place.naver.com/hospital/555/home") == "555"
    assert parse_place_id("https://booking.naver.com/booking/13/bizes/1") is None
    assert parse_place_id("https://naver.me/abcd") is None
    assert parse_place_id("모름") is None
    print("PASS: test_parse_place_id")


def test_render_check_page():
    rows = [{"competitor_id": "comp_x", "name": "가나<다>의원", "check_address": "강원특별자치도 원주시 가상동 1-1",
             "search_url": "https://map.naver.com/p/search/%EA%B0%80", "naver_place_id": "777"}]
    page = render_check_page(rows)
    assert "가나&lt;다&gt;의원" in page and "<다>" not in page.split("const ROWS=")[0]
    assert 'href="https://map.naver.com/p/search/%EA%B0%80"' in page
    assert 'data-id="comp_x" value="777"' in page
    assert "원주시 가상동 1-1" in page and "강원특별자치도" not in page.split("const ROWS=")[0]
    print("PASS: test_render_check_page")


if __name__ == "__main__":
    test_render_check_page()
    test_parse_place_id()
    test_jibun_key()
    test_needs_lookup()
    test_names_match()
    test_pick_match_single_confirmed()
    test_pick_match_same_name_other_address_rejected()
    test_pick_match_ambiguous_rejected()
