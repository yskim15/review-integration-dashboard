"""경쟁 병원의 네이버 플레이스 ID(businessId) 조회 도구 (수동 실행 전용).

config/competitors_config.json에서 naver_place_url이 비어 있거나 예약 URL
(booking.naver.com — 예약 bizes 번호는 플레이스 businessId가 아니라서 수집기가
오류 없이 0건을 반환함, 2026-09-28 시트 실측)인 병원을 대상으로, 네이버 지도
검색 결과에서 플레이스 ID를 찾는다.

오매칭 방지 규칙:
- 검색 결과의 지번주소가 config의 지번주소(동 + 번지)와 정확히 일치하고,
- 상호명이 서로 포함 관계일 때만 "확정"으로 본다.
- 확정 후보가 정확히 1개가 아니면(0개 또는 2개 이상) 채우지 않고 보고만 한다.

차단 처리: 네이버가 차단(401/403/429, captcha 등)하면 즉시 전체 중단한다.
우회(헤더 위장, 재시도 반복 등)하지 않는다 — 남은 병원은 수동으로 확인한다.

사용법:
    python find_naver_place_ids.py            # 조회만(dry-run), 결과 보고서 출력
    python find_naver_place_ids.py --apply    # 확정된 것만 config에 반영(백업 생성)

자동 조회는 네이버 캡차로 막혀 있다(2026-09-28 실측). 수동 확인 경로:
    python find_naver_place_ids.py --make-manual naver_place_manual.json
        → 같은 이름의 .html 확인 페이지가 함께 생긴다. 브라우저로 열어 병원별로 확인·입력 후
          [결과 JSON 복사] 내용으로 입력 JSON 파일을 덮어쓴다
    python find_naver_place_ids.py --manual naver_place_manual.json   # 형식 검증 후 반영(백업 생성)
"""

import argparse
import datetime
import html
import json
import random
import re
import shutil
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "competitors_config.json"
REPORT_PATH = BASE_DIR / "naver_place_lookup_report.json"

SEARCH_URL = "https://map.naver.com/p/api/search/allSearch"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Referer": "https://map.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
SLEEP_RANGE = (5.0, 9.0)
_BLOCK_MARKERS = ("captcha", "자동화된 요청", "비정상적인 접근", "unusual traffic")
_NAME_NOISE = ("의원", "피부과", "성형외과", "원주점", "원주", " ")


class NaverBlockedError(Exception):
    pass


def needs_lookup(naver_place_url):
    return (not naver_place_url) or ("booking.naver.com" in naver_place_url)


def jibun_key(address):
    """'강원특별자치도 원주시 무실동 1857-10' -> '무실동 1857-10'. 추출 실패 시 None."""
    m = re.search(r"([가-힣0-9]+동)\s+(산?\d+(?:-\d+)?)", address or "")
    return f"{m.group(1)} {m.group(2)}" if m else None


def normalize_name(name):
    n = name or ""
    for noise in _NAME_NOISE:
        n = n.replace(noise, "")
    return n


def names_match(a, b):
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def pick_match(competitor, items):
    """검색 결과 items(각 {id, name, address})에서 확정 후보를 고른다.
    반환: (place_id 또는 None, 사유 문자열)"""
    target_key = jibun_key(competitor["address"])
    if not target_key:
        return None, "config 주소에서 지번(동+번지)을 추출하지 못함"
    matched = [
        it for it in items
        if jibun_key(it.get("address", "")) == target_key and names_match(competitor["name"], it.get("name", ""))
    ]
    ids = sorted({str(it["id"]) for it in matched if str(it.get("id", "")).isdigit()})
    if len(ids) == 1:
        return ids[0], "확정(지번주소+상호명 일치)"
    if not ids:
        return None, "일치 후보 없음"
    return None, f"일치 후보 {len(ids)}개, 수동 확인 필요: {ids}"


def search(query, lng, lat):
    resp = requests.get(
        SEARCH_URL,
        params={"query": query, "type": "all", "searchCoord": f"{lng};{lat}"},
        headers=HEADERS,
        timeout=15,
    )
    # 캡차 응답에는 요청자 공인 IP가 들어 있어, 보고서에 남기기 전에 가린다
    head = re.sub(r'"ip"\s*:\s*"[^"]*"', '"ip":"(삭제됨)"', resp.text[:3000])
    hit = [m for m in _BLOCK_MARKERS if m in head.lower()]
    if resp.status_code in (401, 403, 429) or hit:
        # 차단/오탐 판별용으로 응답 앞부분을 보고서에 남긴다(우회 목적 아님)
        raise NaverBlockedError(json.dumps(
            {"status": resp.status_code, "markers": hit,
             "content_type": resp.headers.get("content-type"), "body_head": head[:1500]},
            ensure_ascii=False))
    resp.raise_for_status()
    place = ((resp.json().get("result") or {}).get("place") or {})
    return [
        {"id": it.get("id"), "name": it.get("name"), "address": it.get("address"), "roadAddress": it.get("roadAddress")}
        for it in place.get("list") or []
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="확정된 ID만 competitors_config.json에 반영")
    parser.add_argument("--make-manual", metavar="FILE", help="수동 확인용 입력 파일 생성")
    parser.add_argument("--manual", metavar="FILE", help="수동 입력 파일의 값을 검증 후 반영")
    args = parser.parse_args()

    if args.make_manual:
        n = make_manual_template(args.make_manual)
        print(f"{n}곳 입력 파일 생성: {args.make_manual} (브라우저 확인 페이지: "
              f"{Path(args.make_manual).with_suffix('.html').name})")
        return 0
    if args.manual:
        return apply_manual(args.manual)

    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    targets = [c for c in config["competitors"] if needs_lookup(c["channels"].get("naver_place_url", ""))]
    print(f"조회 대상 {len(targets)}곳")

    report = []
    blocked = None
    for i, comp in enumerate(targets):
        if i:
            time.sleep(random.uniform(*SLEEP_RANGE))
        try:
            items = search(f"원주 {comp['name']}", comp["lng"], comp["lat"])
        except NaverBlockedError as e:
            blocked = json.loads(str(e))
            print(f"[중단] 네이버 차단 감지(status={blocked['status']}, markers={blocked['markers']}). "
                  "우회하지 않고 종료합니다. 응답 앞부분은 보고서의 blocked 항목 참고.")
            break
        except (requests.RequestException, ValueError) as e:
            report.append({"competitor_id": comp["competitor_id"], "name": comp["name"], "place_id": None,
                           "reason": f"요청 실패: {e}", "candidates": []})
            continue
        place_id, reason = pick_match(comp, items)
        report.append({"competitor_id": comp["competitor_id"], "name": comp["name"], "place_id": place_id,
                       "reason": reason, "candidates": items[:5]})
        print(f"- {comp['name']}: {place_id or '-'} ({reason})")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                   "blocked": blocked, "results": report}, f, ensure_ascii=False, indent=2)
    confirmed = {r["competitor_id"]: r["place_id"] for r in report if r["place_id"]}
    print(f"확정 {len(confirmed)}곳 / 대상 {len(targets)}곳. 보고서: {REPORT_PATH.name}")

    if not args.apply:
        print("dry-run입니다. 보고서를 확인한 뒤 --apply로 반영하세요.")
        return 0
    if not confirmed:
        print("반영할 확정 ID가 없습니다.")
        return 0

    backup = apply_ids(config, confirmed)
    print(f"{len(confirmed)}곳 반영 완료. 백업: {backup.name}")
    return 0


def parse_place_id(value):
    """사람이 붙여넣은 값(숫자 또는 플레이스 URL)에서 플레이스 ID를 뽑는다.
    예약 URL(booking.naver.com)·단축 URL(naver.me)은 플레이스 ID가 아니므로 거부(None)."""
    v = (value or "").strip()
    if not v or "booking.naver.com" in v or "naver.me" in v:
        return None
    if v.isdigit():
        return v
    m = re.search(r"(?:place\.naver\.com/[a-z]+|map\.naver\.com/p/(?:[a-z]+/)*place)/(\d+)", v)
    if not m:
        m = re.search(r"place\.naver\.com/(\d+)", v)
    return m.group(1) if m else None


def apply_ids(config, confirmed):
    """confirmed({competitor_id: place_id})를 config에 반영하고 백업 경로를 반환한다."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = CONFIG_PATH.with_name(f"competitors_config.backup_{stamp}.json")
    shutil.copy2(CONFIG_PATH, backup)
    for comp in config["competitors"]:
        if comp["competitor_id"] in confirmed:
            comp["channels"]["naver_place_url"] = (
                f"https://m.place.naver.com/hospital/{confirmed[comp['competitor_id']]}/review/visitor"
            )
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return backup


def make_manual_template(path):
    """수동 확인용 입력 파일을 만든다. naver_place_id 칸에 숫자나 플레이스 URL을 붙여넣는다."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    rows = [
        {
            "competitor_id": c["competitor_id"],
            "name": c["name"],
            "check_address": c["address"],
            "search_url": "https://map.naver.com/p/search/" + requests.utils.quote(f"원주 {c['name']}"),
            "naver_place_id": "",
        }
        for c in config["competitors"]
        if needs_lookup(c["channels"].get("naver_place_url", ""))
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    html_path = Path(path).with_suffix(".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_check_page(rows))
    return len(rows)


def render_check_page(rows):
    """사람이 브라우저에서 플레이스 ID를 확인·입력하는 페이지. 터미널은 인코딩된 링크를
    잘라먹어 검색어가 깨지므로(2026-09-28 실측) 브라우저로 여는 HTML로 제공한다.
    [결과 JSON 복사] 결과를 입력 JSON 파일에 그대로 덮어써 --manual로 반영한다."""
    esc = html.escape
    trs = "".join(
        f'<tr><td>{i}</td><td><a href="{esc(r["search_url"])}" target="_blank" rel="noopener">{esc(r["name"])}</a></td>'
        f'<td>{esc(re.sub(r"^강원특별자치도 ", "", r["check_address"]))}</td>'
        f'<td><input data-id="{esc(r["competitor_id"])}" value="{esc(r["naver_place_id"])}" placeholder="숫자 또는 URL"></td></tr>'
        for i, r in enumerate(rows, 1)
    )
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>네이버 플레이스 확인</title>
<style>body{{font-family:sans-serif;margin:24px;max-width:960px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px 8px}}input{{width:200px}}a{{font-weight:bold}}
textarea{{width:100%;height:200px;margin-top:12px}}button{{padding:8px 16px;margin-top:12px;font-size:15px}}</style></head><body>
<h2>경쟁 병원 네이버 플레이스 ID 확인 ({len(rows)}곳)</h2>
<ol><li>병원 이름 클릭 → 네이버 지도가 새 탭에서 열림</li>
<li>오른쪽 주소와 <b>같은 곳</b>을 클릭 → 주소창 <code>.../place/<b>숫자</b></code> 복사 → 칸에 붙여넣기 (다르거나 없으면 비워 둠)</li>
<li>[결과 JSON 복사] → 입력 JSON 파일 내용을 통째로 바꿔 저장 (또는 Claude 채팅창에 붙여넣기)</li>
<li><code>python find_naver_place_ids.py --manual &lt;입력 JSON 파일&gt;</code> 실행</li></ol>
<table><tr><th>#</th><th>병원</th><th>확인할 주소</th><th>플레이스 ID</th></tr>{trs}</table>
<button onclick="go()">결과 JSON 복사</button><textarea id="out" readonly></textarea>
<script>const ROWS={data};
function go(){{const v={{}};document.querySelectorAll('input').forEach(e=>v[e.dataset.id]=e.value.trim());
const t=JSON.stringify(ROWS.map(r=>Object.assign({{}},r,{{naver_place_id:v[r.competitor_id]||""}})),null,2);
const o=document.getElementById('out');o.value=t;o.select();try{{navigator.clipboard.writeText(t)}}catch(e){{}}}}</script>
</body></html>"""


def apply_manual(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    known = {c["competitor_id"] for c in config["competitors"]}
    confirmed, rejected = {}, []
    for r in rows:
        raw = (r.get("naver_place_id") or "").strip()
        if not raw:
            continue
        pid = parse_place_id(raw)
        if r.get("competitor_id") not in known or not pid:
            rejected.append(f"{r.get('name')}: {raw!r}")
            continue
        confirmed[r["competitor_id"]] = pid
    for msg in rejected:
        print(f"[거부] {msg} (플레이스 ID 형식 아님 또는 알 수 없는 병원)")
    if not confirmed:
        print("반영할 값이 없습니다.")
        return 0
    backup = apply_ids(config, confirmed)
    print(f"{len(confirmed)}곳 반영 완료. 백업: {backup.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
