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


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rates(st):
    """시즌/상대 기록 → 막대용 지표."""
    if not st:
        return None
    g = _int(st.get("gameCount")) or 0
    inn = _f(st.get("inn")) or 0.0
    if g <= 0 and inn <= 0:
        return None
    per = inn / g if g else None
    def pg(key):
        n = _f(st.get(key))
        if n is None or not g:
            return None
        return round(n / g, 2)
    return {
        "era": _era(st.get("era")),
        "era_n": _f(st.get("era")),
        "ip_g": round(per, 2) if per is not None else None,
        "k_g": pg("kk"),
        "bb_g": pg("bb"),
        "h_g": pg("hit") if st.get("hit") is not None else None,
        "w": _int(st.get("w")),
        "l": _int(st.get("l")),
        "g": g,
        "inn": inn,
    }


def _pack_starter(name, season_st, opp_st):
    if not name:
        return None
    out = {"name": name}
    if season_st:
        out["era"] = _era(season_st.get("era"))
        out["w"] = _int(season_st.get("w"))
        out["l"] = _int(season_st.get("l"))
        sea = _rates(season_st)
        if sea:
            out["season"] = sea
    if opp_st:
        vs = _rates(opp_st)
        if vs:
            out["vs"] = vs
    return out


# ---------- KBO ----------
def _naver_day(day):
    d = _json("https://api-gw.sports.naver.com/schedule/games?fields=basic,schedule,baseball"
              f"&upperCategoryId=kbaseball&categoryId=kbo&fromDate={day}&toDate={day}&size=50", NAVER_H)
    if not d.get("success", True) and "result" not in d:
        raise RuntimeError("naver schedule fail")
    return d["result"]["games"]


def _naver_preview(game_id):
    d = _json(f"https://api-gw.sports.naver.com/schedule/games/{game_id}/preview", NAVER_H)
    return (d.get("result") or {}).get("previewData") or {}


def _naver_era(game_id):
    p = _naver_preview(game_id)
    out = {}
    for side in ("home", "away"):
        st = p.get(side + "Starter") or {}
        info = (st.get("playerInfo") or {}).get("name")
        out[side] = (info, st.get("currentSeasonStats") or {}, st.get("currentSeasonStatsOnOpponents") or {})
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
            row = pv.get(nside) or (None, None, None)
            nm, season_st, opp_st = (row + (None, None, None))[:3]
            side = ({"home": "away", "away": "home"}[nside]) if swap else nside
            if nm and nm == names[side]:
                eras[side] = (season_st or {}, opp_st or {})
    out = {}
    for s in ("home", "away"):
        if not names[s]:
            out[s] = None
            continue
        season_st, opp_st = eras.get(s, ({}, {}))
        out[s] = _pack_starter(names[s], season_st, opp_st)
    out["_gid"] = match["gameId"]
    out["_swap"] = swap
    return out


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
            g = _int(stt.get("gamesStarted") or stt.get("gamesPlayed") or stt.get("games"))
            inn = _f(stt.get("inningsPitched"))
            def pg(key, alt=None):
                n = _f(stt.get(key) if stt.get(key) is not None else stt.get(alt))
                if n is None or not g:
                    return None
                return round(n / g, 2)
            sea = {
                "era": _era(stt.get("era")), "era_n": _f(stt.get("era")),
                "w": _int(stt.get("wins")), "l": _int(stt.get("losses")), "g": g, "inn": inn,
                "ip_g": round(inn / g, 2) if inn is not None and g else None,
                "k_g": pg("strikeOuts"), "bb_g": pg("baseOnBalls"), "h_g": pg("hits"),
            }
            return {"era": sea["era"], "w": sea["w"], "l": sea["l"], "season": sea}
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
    if not any(match["teams"][s_].get("probablePitcher") for s_ in ("home", "away")):
        return {"home": None, "away": None, "_pk": match.get("gamePk")}
    for side in ("home", "away"):
        pp = match["teams"][side].get("probablePitcher") or {}
        if not pp.get("fullName"):
            out[side] = None
            continue
        stat = _cached(f"mlb:st:{pp['id']}:{season}", lambda i=pp.get("id"): _mlb_era(i, season)) if pp.get("id") else None
        if not stat:
            out[side] = {"name": pp["fullName"]}
        else:
            out[side] = {"name": pp["fullName"], "era": stat.get("era"), "w": stat.get("w"), "l": stat.get("l")}
            if stat.get("season"):
                out[side]["season"] = stat["season"]
    out["_pk"] = match.get("gamePk")
    return out


def game_starters(g):
    try:
        if g.get("kind") != "baseball":
            return None
        out = None
        if g.get("league") == 5:
            out = _kbo(g)
        elif g.get("league") == 1:
            out = _mlb(g)
        if out:
            out = {k: v for k, v in out.items() if not str(k).startswith("_")}
        return out
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


# ---------- KBO 타자 시즌 기록 (Daum hermes, 규정타석 이상만) ----------
_DAUM = {"User-Agent": "Mozilla/5.0 (twowinscore)", "Referer": "https://sports.daum.net/"}
# API-Sports KBO team id → Daum cpTeamId
_KBO_DAUM = {88: "OB", 89: "HH", 90: "HT", 91: "KT", 92: "WO", 93: "LG", 94: "LT",
             95: "NC", 97: "SS", 647: "SK"}


def _daum_hitters(season):
    d = _json(f"https://sports.daum.net/prx/hermes/api/person/rank.json?leagueCode=kbo&seasonKey={season}"
              "&pageSize=200&page=1&sortKey=battingAverage", _DAUM)
    by = {}
    for x in d.get("list") or []:
        st = x.get("stat") or {}
        if st.get("batAvg") is None:
            continue
        code = (x.get("team") or {}).get("cpTeamId")
        if not code:
            continue
        by.setdefault(code, []).append({
            "name": x.get("name") or x.get("nameMain"),
            "avg": f"{st['batAvg']:.3f}".lstrip("0") if st["batAvg"] < 1 else f"{st['batAvg']:.3f}",
            "avg_n": st["batAvg"],
            "h": _int(st.get("batH")),
            "rbi": _int(st.get("batRbi")),
            "r": _int(st.get("batR")),
            "hr": _int(st.get("batHr")),
            "slg": f"{st['batSlg']:.3f}".lstrip("0") if st.get("batSlg") is not None and st["batSlg"] < 1 else (f"{st['batSlg']:.3f}" if st.get("batSlg") is not None else None),
        })
    for code in by:
        by[code].sort(key=lambda p: -(p["avg_n"] or 0))
    return by


def game_batters(g):
    """야구 양 팀 시즌 타자 표. 데이터 없으면 None."""
    try:
        if g.get("kind") != "baseball" or g.get("league") != 5:
            return None
        hc, ac = _KBO_DAUM.get(g.get("home_id")), _KBO_DAUM.get(g.get("away_id"))
        if not hc or not ac:
            return None
        season = str(g["start"].astimezone(SEOUL).year)
        allh = _cached(f"daum:hit:{season}", lambda: _daum_hitters(season))
        if not allh:
            return None
        home, away = allh.get(hc) or [], allh.get(ac) or []
        if not home and not away:
            return None
        return {"home": home[:12], "away": away[:12]}
    except Exception as e:
        log(f"batters {g.get('key')} {redact(e)[:140]}")
    return None
