"""배당(단일 북메이커: Bet365) + 팀 페이지 데이터. API-Sports, 서버 캐시."""
import os, json, time, threading, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
HOSTS = {"football": "https://v3.football.api-sports.io", "hockey": "https://v1.hockey.api-sports.io",
         "baseball": "https://v1.baseball.api-sports.io", "basketball": "https://v1.basketball.api-sports.io",
         "volleyball": "https://v1.volleyball.api-sports.io"}
BOOK = "Bet365"
BOOK_ID = {"football": 8, "baseball": 2, "basketball": 4, "volleyball": 4, "hockey": 3}  # 종목별 API의 Bet365 id
ODDS_TTL = 900      # 경기 전: 15분마다 갱신
TEAM_TTL = 1800
_c, _lk = {}, threading.Lock()


def _get(kind, path, params):
    req = urllib.request.Request(HOSTS[kind] + path + "?" + urllib.parse.urlencode(params),
                                 headers={"x-apisports-key": os.environ.get("API_SPORTS_KEY", "")})
    with urllib.request.urlopen(req, timeout=20) as r:
        b = json.loads(r.read().decode())
    if b.get("errors"):
        raise RuntimeError(str(b["errors"])[:200])
    return b.get("response") or []


def _cached(key, ttl, fn, fail_ttl=300):
    now = time.time()
    with _lk:
        e = _c.get(key)
        if e and now < e[0]:
            return e[1]
        if len(_c) > 4000:
            for k in [k for k, v in _c.items() if v[0] < now]:
                _c.pop(k, None)
        _c[key] = (now + 60, e[1] if e else None)   # 중복 호출 방지
    try:
        val = fn(e[1] if e else None)
        exp = now + ttl
    except Exception:
        val, exp = (e[1] if e else None), now + fail_ttl
    with _lk:
        _c[key] = (exp, val)
    return val


# ---------- 배당 ----------
def _parse(kind, resp):
    for x in resp:
        for b in x.get("bookmakers") or []:
            if b.get("id") != BOOK_ID[kind]:
                continue
            bets = {bt.get("name"): bt.get("values") or [] for bt in b.get("bets") or []}
            vals = bets.get("Match Winner") if kind == "football" else (bets.get("Home/Away") or None)
            if not vals and kind == "hockey":
                vals = bets.get("3Way Result")
            if not vals:
                return None
            o = {}
            for v in vals:
                k = {"Home": "H", "Draw": "D", "Away": "A"}.get(v.get("value"))
                try:
                    if k:
                        o[k] = float(v.get("odd"))
                except (TypeError, ValueError):
                    pass
            if kind != "football" and not (kind == "hockey" and "Home/Away" not in bets):
                o.pop("D", None)
            if "H" in o and "A" in o:
                return {"o": o, "upd": x.get("update")}
    return None


def odds(g, lite=False):
    """{"book","H","A",("D"),"mv":{H:+1/-1},"at":"HH:MM","final":bool} 또는 None. 경기 시작 후엔 마지막 경기 전 배당 고정."""
    kind = g.get("kind")
    if kind not in BOOK_ID or g.get("other") and False:
        return None
    started = g.get("state") != "scheduled"
    key = ("odds", kind, g.get("id"))
    if started:
        with _lk:
            e = _c.get(key)
        cur = e[1] if e else None
        if cur is None and not lite:
            cur = _cached(key, 86400, lambda prev: _fetch_odds(kind, g, prev), 3600)
    else:
        cur = _cached(key, ODDS_TTL, lambda prev: _fetch_odds(kind, g, prev))
    if not cur:
        return None
    out = dict(cur["o"]); out["book"] = BOOK; out["mv"] = cur.get("mv") or {}; out["at"] = cur.get("at"); out["final"] = started
    return out


def _fetch_odds(kind, g, prev):
    p = {"bookmaker": BOOK_ID[kind]}
    p["fixture" if kind == "football" else "game"] = g["id"]
    r = _parse(kind, _get(kind, "/odds", p))
    if not r:
        return prev
    mv = dict((prev or {}).get("mv") or {})
    if prev:
        for k, v in r["o"].items():
            pv = prev["o"].get(k)
            if pv and abs(v - pv) >= 0.005:
                mv[k] = 1 if v > pv else -1
    r["mv"] = mv
    r["at"] = datetime.now(SEOUL).strftime("%H:%M")
    return r


# ---------- 팀 페이지 ----------
FB_FIN = {"FT", "AET", "PEN"}
FIN = {"FT", "AOT", "AP", "AET", "PEN", "AW", "AB"}
LIVE_SKIP = {"CANC", "ABD", "AWD", "WO", "PST", "POST", "SUSP"}


def _seasons(kind):
    y = datetime.now(SEOUL).year
    if kind == "basketball":
        return [f"{y}-{y+1}", f"{y-1}-{y}", y]
    if kind in ("hockey", "volleyball"):
        return [y, y - 1]
    return [y]


def team(kind, tid):
    if kind not in HOSTS:
        return None
    return _cached(("team", kind, tid), TEAM_TTL, lambda prev: _team_fetch(kind, tid) or prev, 600)


def ko(kind, tid, en):
    if kind in ("baseball", "basketball", "volleyball"):
        import data  # noqa: F401  (vendor 경로 준비)
        import score_bot as sb
        n = (sb.TEAM_KO.get(kind) or {}).get(tid)
        return (n, en) if n else (en, None)
    from teams_ko import ko as k
    return k(kind, tid, en)


def _row(kind, x, tid):
    if kind == "football":
        fx, t, gl, lg = x.get("fixture") or {}, x.get("teams") or {}, x.get("goals") or {}, x.get("league") or {}
        st, ts, hs, as_, gid = (fx.get("status") or {}).get("short"), fx.get("timestamp") or 0, gl.get("home"), gl.get("away"), fx.get("id")
    else:
        t, sc, lg = x.get("teams") or {}, x.get("scores") or {}, x.get("league") or {}
        st, ts, gid = (x.get("status") or {}).get("short"), x.get("timestamp") or 0, x.get("id")
        hs, as_ = sc.get("home"), sc.get("away")
        if isinstance(hs, dict):
            hs, as_ = hs.get("total"), (as_ or {}).get("total")
    h, a = t.get("home") or {}, t.get("away") or {}
    home = h.get("id") == tid
    op = a if home else h
    me, ot = (hs, as_) if home else (as_, hs)
    d = datetime.fromtimestamp(ts, SEOUL)
    r = None
    if me is not None and ot is not None:
        r = "W" if me > ot else ("L" if me < ot else "D")
    return {"ts": ts, "st": st, "date": d.strftime("%Y.%m.%d"), "md": d.strftime("%m/%d"), "time": d.strftime("%H:%M"),
            "ha": "홈" if home else "원정", "opp": ko(kind, op.get("id"), op.get("name") or "?")[0], "opp_id": op.get("id"),
            "opp_logo": op.get("logo"), "league": lg.get("name") or "", "me": me, "ot": ot, "r": r, "gid": gid}


def _team_fetch(kind, tid):
    info = _get(kind, "/teams", {"id": tid})
    if not info:
        return None
    t0 = info[0].get("team") if kind == "football" else info[0]
    venue = (info[0].get("venue") or {}).get("name") if kind == "football" else None
    name, en = ko(kind, tid, t0.get("name") or "?")
    ctry = t0.get("country")
    if isinstance(ctry, dict):
        ctry = ctry.get("name")
    out = {"kind": kind, "id": tid, "name": name, "en": en, "logo": t0.get("logo"), "country": ctry,
           "founded": t0.get("founded"), "venue": venue, "roster": [], "past": [], "next": []}
    now = time.time()
    if kind == "football":
        past = _get(kind, "/fixtures", {"team": tid, "last": 10, "timezone": "Asia/Seoul"})
        nxt = _get(kind, "/fixtures", {"team": tid, "next": 10, "timezone": "Asia/Seoul"})
        rows = [_row(kind, x, tid) for x in past + nxt]
        try:
            sq = _get(kind, "/players/squads", {"team": tid})
            POS = {"Goalkeeper": "골키퍼", "Defender": "수비수", "Midfielder": "미드필더", "Attacker": "공격수"}
            for p in (sq[0].get("players") if sq else []) or []:
                out["roster"].append({"name": p.get("name"), "no": p.get("number"), "pos": POS.get(p.get("position"), p.get("position") or ""),
                                      "age": p.get("age"), "photo": p.get("photo")})
        except Exception:
            pass
    else:
        rows, used = [], None
        for s in _seasons(kind):
            try:
                rs = _get(kind, "/games", {"team": tid, "season": s, "timezone": "Asia/Seoul"})
            except Exception:
                continue
            if rs:
                rows += [_row(kind, x, tid) for x in rs]
                used = used or s
                if any((x.get("timestamp") or 0) > now for x in rs) or len(rows) > 40:
                    break
        if kind == "basketball" and used:
            try:
                for p in _get(kind, "/players", {"team": tid, "season": used}):
                    out["roster"].append({"name": p.get("name"), "no": p.get("number"), "pos": {"Guard": "가드", "Forward": "포워드", "Center": "센터"}.get(p.get("position"), p.get("position") or ""), "age": p.get("age"), "photo": None})
            except Exception:
                pass
    seen = set()
    rows = [r for r in rows if not (r["gid"] in seen or seen.add(r["gid"]))]
    out["past"] = sorted([r for r in rows if r["r"] and (r["st"] in FIN or r["st"] in FB_FIN)], key=lambda r: -r["ts"])[:10]
    out["next"] = sorted([r for r in rows if r["ts"] > now - 3 * 3600 and not r["r"] and r["st"] not in LIVE_SKIP], key=lambda r: r["ts"])[:10]
    return out
