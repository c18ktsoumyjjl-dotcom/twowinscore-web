#!/usr/bin/env python3
"""야구 검색 카드용 선발 투수. 그룹 검색 카드 전용.

- KBO: 네이버 스포츠 일정(homeStarterName/awayStarterName) + 프리뷰(시즌 ERA)
- MLB: statsapi.mlb.com schedule hydrate=probablePitcher + people 시즌 기록(ERA)
  API-Sports 일정과 statsapi 경기가 (팀, 시작 ±6시간)으로 맞을 때만 쓴다.

반환: {'home': {'name','era'}|None, 'away': ...} / 맞는 경기 없음·실패 → None(줄 숨김).
"""
import json, time, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from common import log, redact
from injuries import MLB_TEAM, KBO_TEAM

SEOUL = ZoneInfo("Asia/Seoul")
TTL = 30 * 60
UA = {"User-Agent": "Mozilla/5.0 (twowinscore)"}
NAVER_H = {**UA, "Referer": "https://m.sports.naver.com/"}
_cache = {}


def _cached(key, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    try:
        val = fn()
    except Exception as e:
        log(f"starter {key} {redact(e)[:140]}")
        _cache[key] = (time.time() - TTL + 300, None)   # 실패는 5분만
        return None
    _cache[key] = (time.time(), val)
    return val


def _json(url, headers=UA):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
        return json.loads(r.read().decode())


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _era(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return f"{x:.2f}"


# ---------- KBO ----------
def _naver_day(day):
    d = _json("https://api-gw.sports.naver.com/schedule/games?fields=basic,schedule,baseball"
              f"&upperCategoryId=kbaseball&categoryId=kbo&fromDate={day}&toDate={day}&size=50", NAVER_H)
    if not d.get("success", True) and "result" not in d:
        raise RuntimeError("naver schedule fail")
    return d["result"]["games"]


def _naver_era(game_id):
    d = _json(f"https://api-gw.sports.naver.com/schedule/games/{game_id}/preview", NAVER_H)
    p = (d.get("result") or {}).get("previewData") or {}
    out = {}
    for side in ("home", "away"):
        st = p.get(side + "Starter") or {}
        cs = st.get("currentSeasonStats") or {}
        out[side] = ((st.get("playerInfo") or {}).get("name"),
                     {"era": _era(cs.get("era")), "w": _int(cs.get("w")), "l": _int(cs.get("l"))})
    return out


def _kbo(g):
    hk, ak = KBO_TEAM.get(g.get("home_id")), KBO_TEAM.get(g.get("away_id"))
    if not hk or not ak:
        return None
    st = g["start"].astimezone(SEOUL)
    day = st.strftime("%Y-%m-%d")
    games = _cached(f"kbo:{day}", lambda: _naver_day(day))
    if games is None:
        return None
    match, swap = None, False
    for x in games:
        if x.get("cancel"):
            continue
        pair = (x.get("homeTeamName"), x.get("awayTeamName"))
        try:
            t = datetime.fromisoformat(x["gameDateTime"]).replace(tzinfo=SEOUL)
        except (KeyError, ValueError):
            continue
        if abs((t - st).total_seconds()) > 6 * 3600:
            continue
        if pair == (hk, ak):
            match, swap = x, False
            break
        if pair == (ak, hk):
            match, swap = x, True
    if not match:
        return None
    names = {"home": (match.get("homeStarterName") or "").strip(),
             "away": (match.get("awayStarterName") or "").strip()}
    if swap:
        names = {"home": names["away"], "away": names["home"]}
    eras = {}
    if names["home"] or names["away"]:
        pv = _cached(f"kbo:pv:{match['gameId']}", lambda: _naver_era(match["gameId"])) or {}
        for nside in ("home", "away"):
            nm, stat = pv.get(nside, (None, None))
            side = ({"home": "away", "away": "home"}[nside]) if swap else nside
            if nm and nm == names[side] and stat:   # 이름이 같을 때만 기록
                eras[side] = stat
    return {s: ({"name": names[s], **(eras.get(s) or {})} if names[s] else None) for s in ("home", "away")}


# ---------- MLB ----------
def _mlb_sched(d0, d1):
    d = _json(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={d0}&endDate={d1}"
              "&hydrate=probablePitcher")
    return [x for day in d.get("dates") or [] for x in day.get("games") or []]


def _mlb_era(pid, season):
    d = _json(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=season&group=pitching&season={season}")
    for s in d.get("stats") or []:
        for sp in s.get("splits") or []:
            stt = sp.get("stat") or {}
            return {"era": _era(stt.get("era")), "w": _int(stt.get("wins")), "l": _int(stt.get("losses"))}
    return None


def _mlb(g):
    hid, aid = MLB_TEAM.get(g.get("home_id")), MLB_TEAM.get(g.get("away_id"))
    if not hid or not aid:
        return None
    st = g["start"].astimezone(timezone.utc)
    d0 = (st - timedelta(days=1)).strftime("%Y-%m-%d")
    d1 = (st + timedelta(days=1)).strftime("%Y-%m-%d")
    games = _cached(f"mlb:{d0}:{d1}", lambda: _mlb_sched(d0, d1))
    if games is None:
        return None
    match = None
    pk = g.get("mlb_pk")
    if pk:
        match = next((x for x in games if x.get("gamePk") == pk), None)
    for x in ([] if match else games):
        t = x.get("teams") or {}
        if (t.get("home", {}).get("team", {}).get("id"), t.get("away", {}).get("team", {}).get("id")) != (hid, aid):
            continue
        try:
            gt = datetime.strptime(x["gameDate"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if abs((gt - st).total_seconds()) <= 6 * 3600:
            match = x
            break
    if not match:
        return None
    season = match.get("season") or str(st.year)
    out = {}
    for side in ("home", "away"):
        pp = match["teams"][side].get("probablePitcher") or {}
        if not pp.get("fullName"):
            out[side] = None
            continue
        stat = _cached(f"mlb:st:{pp['id']}:{season}", lambda: _mlb_era(pp["id"], season)) if pp.get("id") else None
        out[side] = {"name": pp["fullName"], **(stat or {})}
    return out


def game_starters(g):
    try:
        if g.get("kind") != "baseball":
            return None
        if g.get("league") == 5:
            return _kbo(g)
        if g.get("league") == 1:
            return _mlb(g)
    except Exception as e:
        log(f"starter {g.get('key')} {redact(e)[:140]}")
    return None


def starter_line(s):
    """'선발 · 원정투수 … vs 홈투수 …' (카드 왼쪽=원정, 오른쪽=홈) / '선발 미발표' / None."""
    if s is None:
        return None
    if not s.get("home") and not s.get("away"):
        return "선발 미발표"

    def one(p):
        if not p:
            return "미발표"
        bits = [p["name"]]
        if p.get("w") is not None and p.get("l") is not None:
            bits.append(f"{p['w']}승 {p['l']}패")
        if p.get("era"):
            bits.append(f"ERA {p['era']}")
        return " ".join(bits)
    return f"선발 · {one(s.get('away'))} vs {one(s.get('home'))}"
