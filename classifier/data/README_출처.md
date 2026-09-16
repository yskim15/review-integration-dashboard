# knu_sentiment_lexicon.json 출처

- 원본: KNU 한국어 감성사전 (군산대학교 소프트웨어융합공학과 Data Intelligence Lab, 2018.05.11)
  - 저장소: https://github.com/park1200656/KnuSentiLex
  - 원본 파일: `KnuSentiLex/data/SentiWord_info.json` (14,843 단어)
  - 무료·공개 학술 자료로 다수의 오픈소스 한국어 NLP 프로젝트에 그대로 재배포되어 쓰인다.
- 이 파일은 원본에서 `word`→`polarity`(정수, -2~2)만 추출한 축약본이다
  (`word_root` 필드는 사용하지 않아 제외). 원본 중복 단어 2건은 마지막 값으로 병합되어
  14,841개로 줄었다.
- 2026-09-16 다운로드. `classifier/rule_based.py`가 이 파일을 로드해 사전 기반 점수를 매긴다.
