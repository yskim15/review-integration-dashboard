import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from collectors.kakao import _parse_reviews, _extract_place_id

_HTML = """
<div class="group_review">
  <ul class="list_review">
    <li>
      <span class="name_user">김철수<span class="screen_out">, 리뷰어 이름</span></span>
      <div class="starred_grade">
        <span class="screen_out">별점</span><span class="screen_out">5.0</span>
      </div>
      <div class="review_detail"><span class="txt_date">2026.08.01.</span></div>
      <div class="wrap_review"><p class="desc_review">친절하고 좋았어요</p></div>
    </li>
    <li>
      <span class="name_user">이영희</span>
      <div class="starred_grade">
        <span class="screen_out">별점</span><span class="screen_out">1.0</span>
      </div>
      <div class="review_detail"><span class="txt_date">2026.07.15.</span></div>
      <div class="wrap_review"><p class="desc_review">불친절했어요</p></div>
      <div class="info_reply">
        <div class="head_reply"><span class="txt_date">2026.07.16.</span></div>
        <p class="desc_reply">불편을 드려 죄송합니다</p>
      </div>
    </li>
  </ul>
</div>
"""


def test_extract_place_id():
    assert _extract_place_id("https://place.map.kakao.com/18731017") == "18731017"
    assert _extract_place_id("https://place.map.kakao.com/18731017/") == "18731017"
    print("PASS: test_extract_place_id")


def test_parse_reviews_basic():
    reviews = _parse_reviews(_HTML)
    assert len(reviews) == 2, f"실제: {len(reviews)}"
    r1, r2 = reviews
    assert r1["channel"] == "카카오맵"
    assert r1["author"] == "김철수", f"실제: {r1['author']!r}"
    assert r1["rating"] == 5, f"실제: {r1['rating']}"
    assert r1["date"] == "2026.08.01."
    assert r1["content"] == "친절하고 좋았어요"
    assert r1["has_reply"] is False
    assert r2["rating"] == 1
    assert r2["has_reply"] is True
    print("PASS: test_parse_reviews_basic")


def test_parse_reviews_empty_when_no_cards():
    assert _parse_reviews("<div>후기미제공</div>") == []
    print("PASS: test_parse_reviews_empty_when_no_cards")


if __name__ == "__main__":
    test_extract_place_id()
    test_parse_reviews_basic()
    test_parse_reviews_empty_when_no_cards()
