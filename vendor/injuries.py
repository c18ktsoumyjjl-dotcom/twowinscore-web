#!/usr/bin/env python3
"""그룹 검색 카드용 결장 정보. 채널 카드에는 쓰지 않는다.

- MLB: statsapi.mlb.com 40인 로스터 상태(D7/D10/D15/D60) + 트랜잭션(날짜·사유)
- NBA: ESPN 리그 전체 부상 피드(최근 10일 안에 갱신된 항목만)
- KBO: 표시하지 않음(2026-10-09 사용자 결정, RegisterAll 조회 중단)
- KBL/WKBL/V리그: 없음

팀 id 는 검증한 표로만 연결한다. 표에 없거나 실패·오래된 자료면 None(줄을 그리지 않음).
"""
import json, re, time, urllib.request, urllib.parse, http.cookiejar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common import log, redact

SEOUL = ZoneInfo("Asia/Seoul")
TTL = 30 * 60
MAX_ROWS = 4
UA = {"User-Agent": "Mozilla/5.0 (twowinscore)"}

# API-Sports baseball league 1 team id -> statsapi team id (2026-10-09 이름 대조로 검증)
MLB_TEAM = {
    2: 109, 963: 133, 3: 144, 4: 110, 5: 111, 6: 112, 7: 145, 8: 113, 9: 114, 10: 115,
    12: 116, 15: 117, 16: 118, 17: 108, 18: 119, 19: 146, 20: 158, 22: 142, 24: 121,
    25: 147, 27: 143, 28: 134, 30: 135, 31: 137, 32: 136, 33: 138, 34: 139, 35: 140,
    36: 141, 37: 120,
}
# API-Sports basketball league 12 team id -> ESPN team id (Clippers 는 ESPN 'LA Clippers')
NBA_TEAM = {
    132: "1", 133: "2", 134: "17", 135: "30", 136: "4", 137: "5", 138: "6", 139: "7",
    140: "8", 141: "9", 142: "10", 143: "11", 144: "12", 145: "13", 146: "29", 147: "14",
    148: "15", 149: "16", 150: "3", 151: "18", 152: "25", 153: "19", 154: "20", 155: "21",
    156: "22", 157: "23", 158: "24", 159: "28", 160: "26", 161: "27",
}
# API-Sports baseball league 5 team id -> KBO 사이트 팀 표기
KBO_TEAM = {88: "두산", 89: "한화", 90: "KIA", 91: "KT", 92: "키움", 93: "LG", 94: "롯데",
            95: "NC", 97: "삼성", 647: "SSG"}

_cache = {}


def _cached(key, fn, ttl=TTL):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:
        log(f"injury {key} {redact(e)[:140]}")
        val = None
        # 실패는 5분만 기억
        _cache[key] = (time.time() - ttl + 300, None)
        return None
    _cache[key] = (time.time(), val)
    return val


def _json(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _md(dt):
    return f"{dt.month}/{dt.day}"


# ---------- 부위 번역 ----------
PART_KO = [
    ("tommy john", "토미 존 수술"), ("thoracic outlet", "흉곽출구 증후군"),
    ("pectoral", "흉근"), ("lumbar", "허리"), ("spine", "척추"), ("shin", "정강이"), ("tibia", "정강이뼈"),
    ("plantar", "족저근막"), ("labrum", "어깨 관절와순"), ("rotator", "회전근개"), ("trapezius", "승모근"), ("ucl", "팔꿈치 인대"), ("flexor", "굴곡근"),
    ("concussion", "뇌진탕"), ("hamstring", "햄스트링"), ("shoulder", "어깨"), ("elbow", "팔꿈치"),
    ("forearm", "전완"), ("wrist", "손목"), ("thumb", "엄지"), ("finger", "손가락"), ("hand", "손"),
    ("oblique", "옆구리"), ("lat ", "광배근"), ("back", "허리"), ("hip", "고관절"), ("groin", "사타구니"),
    ("quadriceps", "대퇴사두근"), ("quad", "대퇴사두근"), ("knee", "무릎"), ("calf", "종아리"),
    ("achilles", "아킬레스건"), ("ankle", "발목"), ("foot", "발"), ("toe", "발가락"), ("heel", "발뒤꿈치"),
    ("rib", "갈비뼈"), ("neck", "목"), ("abdominal", "복부"), ("chest", "가슴"), ("biceps", "이두근"),
    ("triceps", "삼두근"), ("illness", "질병"), ("lower body", "하체"), ("upper body", "상체"),
    ("leg", "다리"), ("face", "얼굴"), ("eye", "눈"), ("head", "머리"), ("rest", "휴식"),
]


def part_ko(text):
    """'Right shoulder impingement' -> '오른쪽 어깨'. 못 고르면 짧은 영어, 없으면 ''."""
    t = " " + (text or "").lower().replace("-", " ") + " "
    side = "오른쪽 " if " right " in t else ("왼쪽 " if " left " in t else "")
    for en, ko in PART_KO:
        if en in t:
            return (side + ko).strip()
    return ""  # 번역 못 한 부위는 영어로 남기지 않고 생략


# ---------- MLB ----------
IL_CODES = {"D7": "결장 · IL7", "D10": "결장 · IL10", "D15": "결장 · IL15", "D60": "결장 · IL60"}


def _mlb_team(team_id):
    now = datetime.now(SEOUL)
    roster = _json(f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster?rosterType=40Man")
    hurt = []
    for p in roster.get("roster") or []:
        code = (p.get("status") or {}).get("code")
        if code in IL_CODES:
            hurt.append((p["person"]["id"], p["person"]["fullName"], IL_CODES[code]))
    if not hurt:
        return {"rows": [], "asof": time.time()}
    start = (now - timedelta(days=240)).date().isoformat()
    tx = _json(f"https://statsapi.mlb.com/api/v1/transactions?teamId={team_id}"
               f"&startDate={start}&endDate={now.date().isoformat()}")
    last = {}
    for t in tx.get("transactions") or []:
        desc = t.get("description") or ""
        pid = ((t.get("person") or {}).get("id"))
        if pid is None or "injured list" not in desc.lower():
            continue
        if not re.search(r"\b(placed|transferred)\b", desc):
            continue
        d = t.get("date") or t.get("effectiveDate") or ""
        if d >= (last.get(pid) or ("", ""))[0]:
            last[pid] = (d, desc)
    rows = []
    for pid, name, il in hurt:
        d, desc = last.get(pid, ("", ""))
        bits = [il]
        if d:
            dt = datetime.strptime(d[:10], "%Y-%m-%d")
            bits.append(_md(dt))
        tail = re.split(r"injured list\.?", desc)[-1].strip() if "injured list" in desc else ""
        reason = part_ko(tail) if tail else ""
        if reason:
            bits.append(reason)
        rows.append({"name": name, "detail": " · ".join(bits), "sort": d or "0"})
    rows.sort(key=lambda r: r["sort"], reverse=True)
    return {"rows": rows, "asof": time.time()}


# ---------- NBA ----------
NBA_STATUS = {
    "out": "결장", "day-to-day": "출전 미정(DTD)", "questionable": "출전 미정(DTD)",
    "doubtful": "결장 유력", "probable": "출전 유력", "suspension": "출장 정지",
    "out for season": "시즌 아웃",
}


STATUS_RANK = {"시즌 아웃": 0, "결장": 1, "출장 정지": 1, "결장 유력": 2, "출전 미정(DTD)": 3, "출전 유력": 4}


def _nba_feed():
    feed = _json("https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/injuries")
    by_team = {}
    cutoff = datetime.now(SEOUL) - timedelta(days=10)
    for t in feed.get("injuries") or []:
        rows = []
        for i in t.get("injuries") or []:
            try:
                dt = datetime.strptime(i.get("date") or "", "%Y-%m-%dT%H:%MZ").replace(
                    tzinfo=ZoneInfo("UTC")).astimezone(SEOUL)
            except ValueError:
                continue
            if dt < cutoff:
                continue
            st = NBA_STATUS.get((i.get("status") or "").strip().lower())
            name = (i.get("athlete") or {}).get("displayName")
            if not st or not name:
                continue
            det = i.get("details") or {}
            part = part_ko(" ".join(x for x in (det.get("side"), det.get("type")) if x and x != "Not Specified"))
            if part in ("Undisclosed", "Other"):
                part = ""
            bits = [st, _md(dt)] + ([part] if part else [])
            rows.append({"name": name, "detail": " · ".join(bits), "sort": dt.isoformat(),
                         "rank": STATUS_RANK.get(st, 5)})
        rows.sort(key=lambda r: r["sort"], reverse=True)
        rows.sort(key=lambda r: r["rank"])
        by_team[str(t.get("id"))] = rows
    return {"teams": by_team, "asof": time.time()}


# ---------- 공개 ----------
def team_unavailable(kind, league, team_id, team_name=""):
    """{'label', 'team', 'rows':[(name, detail)], 'more'} 또는 None. 자료 없으면 None."""
    try:
        if kind == "baseball" and league == 1:
            mid = MLB_TEAM.get(team_id)
            if not mid:
                return None
            got = _cached(f"mlb:{mid}", lambda: _mlb_team(mid))
            rows, label = (got or {}).get("rows"), "부상자 명단"
            if got is None:
                return None
        elif kind == "basketball" and league == 12:
            eid = NBA_TEAM.get(team_id)
            if not eid:
                return None
            feed = _cached("nba:feed", _nba_feed)
            if feed is None:
                return None
            rows, label = feed["teams"].get(eid, []), "결장·부상"
        else:
            return None
    except Exception as e:
        log(f"injury {kind}:{league}:{team_id} {redact(e)[:140]}")
        return None
    if not rows:
        # 공식 자료를 정상으로 받았는데 명단이 비어 있으면 '없음'으로 확실히 표시
        return {"label": label, "team": team_name, "rows": [], "more": 0, "none": True}
    return {"label": label, "team": team_name,
            "rows": [(r["name"], r["detail"]) for r in rows[:MAX_ROWS]],
            "more": max(0, len(rows) - MAX_ROWS)}


def game_unavailable(g):
    """두 팀 결과 목록(있는 팀만). 야구는 원정 먼저(카드 왼쪽=원정), 그 외 홈 먼저."""
    from concurrent.futures import ThreadPoolExecutor
    sides = ("away", "home") if g.get("kind") == "baseball" else ("home", "away")
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(team_unavailable, g.get("kind"), g.get("league"), g.get(side + "_id"), g.get(side) or "")
                for side in sides]
        res = [f.result() for f in futs]
    out = [r for r in res if r]
    if out and all(b.get("none") for b in out):
        return []  # 두 팀 모두 없으면 섹션을 그리지 않음
    return out
