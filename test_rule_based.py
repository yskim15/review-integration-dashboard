import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from classifier.rule_based import classify


def test_rating_negative_confirmed():
    result = classify({"rating": 1, "content": "아무거나"})
    assert result == {"sentiment": "부정", "confirmed": True, "score": None, "matched_words": [], "method": "rating"}
    print("PASS: test_rating_negative_confirmed")


def test_rating_positive_confirmed():
    result = classify({"rating": 5, "content": "아무거나"})
    assert result["sentiment"] == "긍정" and result["confirmed"] is True and result["method"] == "rating"
    print("PASS: test_rating_positive_confirmed")


def test_rating_neutral_confirmed():
    result = classify({"rating": 3, "content": "아무거나"})
    assert result["sentiment"] == "중립" and result["confirmed"] is True
    print("PASS: test_rating_neutral_confirmed")


def test_text_positive_confirmed():
    result = classify({"rating": None, "content": "정말 친절하고 좋았어요"})
    assert result["sentiment"] == "긍정", f"실제: {result}"
    assert result["confirmed"] is True
    assert result["score"] == 2
    assert result["matched_words"] == ["친절"]
    print("PASS: test_text_positive_confirmed")


def test_text_negative_confirmed_domain_word():
    result = classify({"rating": None, "content": "직원이 너무 불친절해요"})
    assert result["sentiment"] == "부정", f"실제: {result}"
    assert result["confirmed"] is True
    assert result["score"] == -2
    assert result["matched_words"] == ["불친절"]
    print("PASS: test_text_negative_confirmed_domain_word")


def test_negation_prefix_flips_polarity():
    # "안 친절해요" — 긍정어 "친절" 앞에 부정어 "안"이 있으면 반전돼야 한다
    result = classify({"rating": None, "content": "직원이 안 친절해요"})
    assert result["sentiment"] == "부정", f"실제: {result}"
    assert result["confirmed"] is True
    assert result["score"] == -2
    print("PASS: test_negation_prefix_flips_polarity")


def test_negation_suffix_flips_polarity():
    # "친절하지 않아요" — 긍정어 뒤에 "~하지 않다" 패턴이 오면 반전돼야 한다
    result = classify({"rating": None, "content": "친절하지 않아요"})
    assert result["sentiment"] == "부정", f"실제: {result}"
    assert result["confirmed"] is True
    assert result["score"] == -2
    print("PASS: test_negation_suffix_flips_polarity")


def test_domain_phrase_wait_time():
    result = classify({"rating": None, "content": "대기시간이 길어서 힘들었어요"})
    assert result["sentiment"] == "부정", f"실제: {result}"
    assert result["confirmed"] is True
    assert result["score"] == -4
    print("PASS: test_domain_phrase_wait_time")


def test_ambiguous_text_marked_unconfirmed():
    # 사전에 매칭되는 단어가 거의 없거나 상쇄되는 문장은 무리하게 단정하지 않는다
    result = classify({"rating": None, "content": "네이버 지도 통해 예약하고 방문했습니다 진료 시간 확인 후 왔어요"})
    assert result["confirmed"] is False, f"실제: {result}"
    assert result["sentiment"] == "중립"
    print("PASS: test_ambiguous_text_marked_unconfirmed")


if __name__ == "__main__":
    test_rating_negative_confirmed()
    test_rating_positive_confirmed()
    test_rating_neutral_confirmed()
    test_text_positive_confirmed()
    test_text_negative_confirmed_domain_word()
    test_negation_prefix_flips_polarity()
    test_negation_suffix_flips_polarity()
    test_domain_phrase_wait_time()
    test_ambiguous_text_marked_unconfirmed()
