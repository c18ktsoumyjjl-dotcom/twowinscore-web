#!/usr/bin/env python3
"""MLB 공식 일정(statsapi.mlb.com) 보조. 그룹 검색 전용(채널 게시에는 쓰지 않음).

API-Sports 에 아직 안 올라온 MLB 예정 경기(포스트시즌 등)를 검색 프리뷰로만 보여준다.
- 두 팀이 모두 확정되고(검증된 MLB_TEAM 표로 연결되는 팀) 시작 시각이 정해진 경기만
- 상태가 Scheduled / Pre-Game / Warmup 인 경기만 (취소·연기·진행·종료 제외)
- 'If Necessary' 경기는 if_necessary=True ('필요 시 개최' 표시)
- 시리즈 이름은 아래 표에 있는 것만 한국어로 붙인다
같은 경기가 API-Sports 에 있으면 언제나 API-Sports 경기가 우선이다(score_search 에서 처리).
"""
import json, time, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import score_bot as sb
from common import log, redact
from injuries import MLB_TEAM

SEOUL = ZoneInfo("Asia/Seoul")
TTL = 15 * 60
UA = {"User-Agent": "Mozilla/5.0 (twowinscore)"}
OK_STATES = {"Scheduled", "Pre-Game", "Warmup"}
STATS_TO_API = {s: a for a, s in MLB_TEAM.items()}
SERIES_KO = {
    "AL Wild Card Series": "AL 와일드카드시리즈", "NL Wild Card Series": "NL 와일드카드시리즈",
    "AL Division Series": "AL 디비전시리즈", "NL Division Series": "NL 디비전시리즈",
    "AL Championship Series": "AL 챔피언십시리즈", "NL Championship Series": "NL 챔피언십시리즈",
    "World Series": "월드시리즈",
}
POST_TYPES = {"F", "D", "L", "W"}
_cache = {}


def _schedule(d0, d1):
    key = (d0, d1)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={d0}&endDate={d1}"
           "&hydrate=team,seriesStatus,probablePitcher")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            d = json.loads(r.read().decode())
        games = [x for day in d.get("dates") or [] for x in day.get("games") or []]
    except Exception as e:
        log(f"mlb official schedule {d0}~{d1} {redact(e)[:140]}")
        _cache[key] = (time.time() - TTL + 120, None)   # 실패는 2분만
        return None
    _cache[key] = (time.time(), games)
    return games


def _start(x):
    try:
        return datetime.strptime(x["gameDate"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        return None


def series_label(x):
    """'NL 챔피언십시리즈 1차전'. 포스트시즌이고 표에 있는 시리즈일 때만, 아니면 ''."""
    if x.get("gameType") not in POST_TYPES:
        return ""
    name = SERIES_KO.get((x.get("seriesDescription") or "").strip())
    try:
        n = int(x.get("seriesGameNumber"))
    except (TypeError, ValueError):
        return ""
    return f"{name} {n}차전" if name and n > 0 else ""


def is_if_necessary(x):
    return x.get("ifNecessary") == "Y" or "if necessary" in (x.get("ifNecessaryDescription") or "").lower()


def _api_ids(x):
    t = x.get("teams") or {}
    out = []
    for side in ("home", "away"):
        team = (t.get(side) or {}).get("team") or {}
        name = team.get("name") or ""
        aid = STATS_TO_API.get(team.get("id"))
        if not aid or "/" in name:
            return None   # 상대 미정(CLE/CWS 같은 승자 자리) 또는 표에 없는 팀
        out.append((aid, name))
    return out


def _window(now, horizon):
    d0 = (now.astimezone(timezone.utc) - timedelta(days=1)).date().isoformat()
    d1 = (horizon.astimezone(timezone.utc) + timedelta(days=1)).date().isoformat()
    return d0, d1


def upcoming_games(now, horizon):
    """확실한 예정 경기만 game dict 로. 실패하면 빈 목록."""
    games = _schedule(*_window(now, horizon))
    if not games:
        return []
    meta = sb.LEAGUE_BY_KEY[("baseball", 1)]
    out = []
    for x in games:
        st = x.get("status") or {}
        if st.get("detailedState") not in OK_STATES or st.get("startTimeTBD"):
            continue
        start = _start(x)
        if not start:
            continue
        start = start.astimezone(SEOUL)
        if not (now - timedelta(hours=3) <= start <= horizon):
            continue
        ids = _api_ids(x)
        if not ids:
            continue
        (hid, hen), (aid, aen) = ids
        pk = x.get("gamePk")
        series = series_label(x)
        out.append({
            "key": f"baseball:1:mlb{pk}", "id": f"mlb{pk}", "emoji": meta["emoji"],
            "label": meta["label"] + (f" · {series}" if series else ""),
            "kind": "baseball", "league": 1,
            "order": sb.LEAGUE_ORDER.get(("baseball", 1), 99),
            "start": start, "status": "NS",
            "home": sb.ko_name("baseball", hid, hen), "away": sb.ko_name("baseball", aid, aen),
            "home_id": hid, "away_id": aid, "home_logo": None, "away_logo": None,
            "home_score": None, "away_score": None, "period": "", "lines": [],
            "home_en": hen, "away_en": aen,
            "source": "mlb_official", "mlb_pk": pk, "series_ko": series,
            "if_necessary": is_if_necessary(x),
        })
    out.sort(key=lambda g: (g["start"], g["key"]))
    return out


def same_game(a, b):
    """같은 MLB 경기인지(두 팀이 같고 시작 ±6시간, 홈·원정 순서 무관)."""
    if {a.get("home_id"), a.get("away_id")} != {b.get("home_id"), b.get("away_id")}:
        return False
    return abs((a["start"] - b["start"]).total_seconds()) <= 6 * 3600


def enrich(g, now, horizon):
    """API-Sports MLB 예정 경기에 공식 일정의 시리즈 이름·'필요 시 개최'를 붙인 사본. 못 맞추면 원본."""
    if g.get("kind") != "baseball" or g.get("league") != 1 or g.get("source") == "mlb_official":
        return g
    try:
        for o in upcoming_games(now, horizon):
            if same_game(g, o):
                if not o["series_ko"] and not o["if_necessary"]:
                    return g
                c = dict(g)
                if o["series_ko"] and "·" not in (c.get("label") or ""):
                    c["label"] = (c.get("label") or "MLB") + f" · {o['series_ko']}"
                c["series_ko"] = o["series_ko"]
                c["if_necessary"] = o["if_necessary"]
                c["mlb_pk"] = o["mlb_pk"]
                return c
    except Exception as e:
        log(f"mlb official enrich {g.get('key')} {redact(e)[:140]}")
    return g
