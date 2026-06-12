# -*- coding: utf-8 -*-
"""
월드컵 토토 - 경기 결과 자동수집기 (공개 저장소 / GitHub Actions용)

football-data.org 무료 API에서 월드컵 경기 스코어를 가져와
Supabase의 matches 테이블에 자동 기록한다.
표준 라이브러리만 사용 (urllib, json) — 추가 의존성 없음.

로컬 테스트:  py fetch_scores.py        (.env 읽음)
점검만(쓰기 X):  DRY_RUN=1 로 실행
GitHub Actions: 환경변수(Secrets)로 키 주입 → 5분마다 실행
"""
import os
import json
import sys
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ──────────────────────────────────────────────────────────────
# 설정값 (환경변수 → .env → 기본값)
# ──────────────────────────────────────────────────────────────
def load_dotenv(path=".env"):
    """python-dotenv 없이 .env 한 줄씩 읽어 os.environ에 주입 (이미 있으면 유지)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv()

SUPABASE_URL  = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY   = os.environ.get("SUPABASE_SERVICE_KEY", "")
FD_TOKEN      = os.environ.get("FOOTBALL_DATA_TOKEN", "")
COMPETITION   = os.environ.get("FD_COMPETITION", "WC")   # football-data 대회코드 (월드컵=WC)
TOTO_COMP     = os.environ.get("TOTO_COMPETITION", "worldcup")  # 우리 matches.competition 값
DRY_RUN       = os.environ.get("DRY_RUN", "") not in ("", "0", "false", "False")

FINISHED_STATUS = {"FINISHED", "AWARDED"}   # 이 상태면 finished=true 로 확정

# ──────────────────────────────────────────────────────────────
# 한글 팀명 → football-data 영문명 별칭 (월드컵 본선 48개국)
# API가 돌려주는 영문명이 조금 달라도 매칭되게 별칭을 여러 개 둠.
# 새 대회로 바꾸면 이 표만 갱신하면 됨.
# ──────────────────────────────────────────────────────────────
TEAM_ALIASES = {
    "멕시코": ["Mexico"],
    "남아공": ["South Africa"],
    "한국": ["South Korea", "Korea Republic", "Republic of Korea", "Korea"],
    "체코": ["Czech Republic", "Czechia"],
    "캐나다": ["Canada"],
    "보스니아": ["Bosnia and Herzegovina", "Bosnia-Herzegovina", "Bosnia & Herzegovina"],
    "미국": ["United States", "USA", "United States of America"],
    "파라과이": ["Paraguay"],
    "카타르": ["Qatar"],
    "스위스": ["Switzerland"],
    "브라질": ["Brazil"],
    "모로코": ["Morocco"],
    "아이티": ["Haiti"],
    "스코틀랜드": ["Scotland"],
    "호주": ["Australia"],
    "튀르키예": ["Turkey", "Türkiye", "Turkiye"],
    "독일": ["Germany"],
    "쿠라소": ["Curacao", "Curaçao"],
    "네덜란드": ["Netherlands", "Holland"],
    "일본": ["Japan"],
    "코트디부아르": ["Ivory Coast", "Cote d'Ivoire", "Côte d'Ivoire"],
    "에콰도르": ["Ecuador"],
    "스웨덴": ["Sweden"],
    "튀니지": ["Tunisia"],
    "스페인": ["Spain"],
    "카보베르데": ["Cape Verde", "Cabo Verde", "Cape Verde Islands"],
    "벨기에": ["Belgium"],
    "이집트": ["Egypt"],
    "사우디": ["Saudi Arabia"],
    "우루과이": ["Uruguay"],
    "이란": ["Iran", "IR Iran"],
    "뉴질랜드": ["New Zealand"],
    "프랑스": ["France"],
    "세네갈": ["Senegal"],
    "이라크": ["Iraq"],
    "노르웨이": ["Norway"],
    "아르헨티나": ["Argentina"],
    "알제리": ["Algeria"],
    "오스트리아": ["Austria"],
    "요르단": ["Jordan"],
    "포르투갈": ["Portugal"],
    "콩고DR": ["DR Congo", "Congo DR", "Democratic Republic of Congo",
              "Congo Democratic Republic", "Congo DR (Kinshasa)"],
    "잉글랜드": ["England"],
    "크로아티아": ["Croatia"],
    "가나": ["Ghana"],
    "파나마": ["Panama"],
    "우즈베키스탄": ["Uzbekistan"],
    "콜롬비아": ["Colombia"],
}


def norm(s):
    """비교용 정규화: 소문자 + 발음기호 제거 + 영숫자만."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


# 정규화된 영문별칭 → 한글팀명 역인덱스
ALIAS_TO_KR = {}
for kr, aliases in TEAM_ALIASES.items():
    for a in aliases:
        ALIAS_TO_KR[norm(a)] = kr
    ALIAS_TO_KR[norm(kr)] = kr  # 혹시 API가 한글로 줄 일은 없지만 안전망


def api_team_to_kr(name):
    """API가 준 팀명을 우리 한글팀명으로. 못 찾으면 None."""
    return ALIAS_TO_KR.get(norm(name))


# ──────────────────────────────────────────────────────────────
# HTTP 유틸 (표준 라이브러리)
# ──────────────────────────────────────────────────────────────
def http(url, method="GET", headers=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, raw


# ──────────────────────────────────────────────────────────────
# football-data.org: 월드컵 경기 전체
# ──────────────────────────────────────────────────────────────
def fetch_api_matches():
    url = "https://api.football-data.org/v4/competitions/%s/matches" % COMPETITION
    status, data = http(url, headers={"X-Auth-Token": FD_TOKEN})
    if status != 200:
        print("[ERROR] football-data %s: %s" % (status, data))
        sys.exit(1)
    return data.get("matches", [])


def parse_dt(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ──────────────────────────────────────────────────────────────
# Supabase REST
# ──────────────────────────────────────────────────────────────
def sb_headers(extra=None):
    h = {"apikey": SERVICE_KEY, "Authorization": "Bearer " + SERVICE_KEY}
    if extra:
        h.update(extra)
    return h


def fetch_toto_matches():
    """아직 확정 안 된 우리 경기들."""
    url = ("%s/rest/v1/matches?competition=eq.%s&finished=eq.false"
           "&select=id,home_team,away_team,kickoff_at,home_score,away_score,finished"
           % (SUPABASE_URL, TOTO_COMP))
    status, data = http(url, headers=sb_headers())
    if status != 200:
        print("[ERROR] supabase select %s: %s" % (status, data))
        sys.exit(1)
    return data or []


def patch_match(mid, home_score, away_score, finished):
    url = "%s/rest/v1/matches?id=eq.%s" % (SUPABASE_URL, mid)
    body = {"home_score": home_score, "away_score": away_score, "finished": finished}
    status, data = http(url, method="PATCH",
                        headers=sb_headers({"Content-Type": "application/json",
                                            "Prefer": "return=minimal"}),
                        body=body)
    if status not in (200, 204):
        print("[ERROR] supabase patch id=%s %s: %s" % (mid, status, data))
        return False
    return True


# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────
def main():
    missing = [k for k, v in [("SUPABASE_URL", SUPABASE_URL),
                              ("SUPABASE_SERVICE_KEY", SERVICE_KEY),
                              ("FOOTBALL_DATA_TOKEN", FD_TOKEN)] if not v]
    if missing:
        print("[ERROR] 환경변수 누락: " + ", ".join(missing))
        sys.exit(1)

    print("=== 월드컵 결과 수집 시작 %s%s ==="
          % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "  [DRY RUN]" if DRY_RUN else ""))

    api_matches = fetch_api_matches()
    toto_matches = fetch_toto_matches()
    print("API 경기 %d건 / 미확정 토토경기 %d건" % (len(api_matches), len(toto_matches)))

    # API 경기를 (한글팀쌍 frozenset, utc일자) 로 색인
    index = {}      # frozenset({krHome, krAway}) -> list of api match dict
    unknown = set()
    for am in api_matches:
        hn = (am.get("homeTeam") or {}).get("name")
        an = (am.get("awayTeam") or {}).get("name")
        kh, ka = api_team_to_kr(hn), api_team_to_kr(an)
        if not kh:
            unknown.add(hn)
        if not ka:
            unknown.add(an)
        if kh and ka:
            index.setdefault(frozenset((kh, ka)), []).append(am)

    if unknown:
        print("[주의] 매핑 안 된 API 팀명(별칭 추가 필요): " + ", ".join(sorted(filter(None, unknown))))

    updated = matched = 0
    for tm in toto_matches:
        kh, ka = tm["home_team"], tm["away_team"]
        cands = index.get(frozenset((kh, ka)))
        if not cands:
            continue
        # 같은 팀쌍이 여러 번이면 킥오프 시각이 가장 가까운 API 경기 선택
        t_kick = parse_dt(tm.get("kickoff_at"))
        def gap(am):
            a = parse_dt(am.get("utcDate"))
            if not (a and t_kick):
                return timedelta(days=999)
            return abs(a - t_kick)
        am = min(cands, key=gap)
        if t_kick and gap(am) > timedelta(days=2):
            continue  # 날짜가 너무 멀면 다른 경기로 보고 패스

        matched += 1
        ft = (am.get("score") or {}).get("fullTime") or {}
        sh, sa = ft.get("home"), ft.get("away")
        if sh is None or sa is None:
            continue  # 아직 스코어 없음(시작 전)

        # API의 home/away 가 우리와 반대면 스코어도 뒤집어 맞춤
        api_home_kr = api_team_to_kr((am.get("homeTeam") or {}).get("name"))
        if api_home_kr != kh:
            sh, sa = sa, sh

        finished = am.get("status") in FINISHED_STATUS
        # 바뀐 게 없으면 건너뜀
        if (tm.get("home_score") == sh and tm.get("away_score") == sa
                and bool(tm.get("finished")) == finished):
            continue

        tag = "확정" if finished else "진행중"
        print("  %s %d:%d %s  (id=%s, %s)"
              % (kh, sh, sa, ka, tm["id"], tag))
        if DRY_RUN:
            updated += 1
        elif patch_match(tm["id"], sh, sa, finished):
            updated += 1

    print("매칭 %d건 / %s %d건" % (matched, "기록예정" if DRY_RUN else "기록", updated))
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
