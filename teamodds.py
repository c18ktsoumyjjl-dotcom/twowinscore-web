"""배당(경기당 북메이커 1곳: Bet365 우선, 없으면 대체) + 팀 페이지 데이터. API-Sports, 서버 캐시."""
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
# 한 경기에 한 북메이커만 표시. Bet365 우선, 없으면 아래 순서로 같은 API 응답에서 대체.
BOOK_ORDER = ["bet365", "pinnacle", "1xbet", "williamhill", "marathon", "betfair", "betvictor",
              "unibet", "bwin", "betano", "10bet", "sbo", "dafabet", "188bet", "betway"]
BOOK_SHORT = {"bet365": "B365", "pinnacle": "PIN", "1xbet": "1XB", "williamhill": "WH", "marathon": "MAR",
              "betfair": "BF", "betvictor": "BV", "unibet": "UNI", "bwin": "BWIN", "betano": "BTN",
              "10bet": "10B", "sbo": "SBO", "dafabet": "DAFA", "188bet": "188", "betway": "BWY"}
BOOK_NAME = {"bet365": "Bet365", "pinnacle": "Pinnacle", "1xbet": "1xBet", "williamhill": "William Hill",
             "marathon": "Marathonbet", "betfair": "Betfair", "betvictor": "BetVictor", "sbo": "SBO"}


def _norm(n):
    n = (n or "").lower().replace(" ", "")
    return {"pncl": "pinnacle", "marathonbet": "marathon"}.get(n, n)


def _prices(kind, b):
    bets = {bt.get("name"): bt.get("values") or [] for bt in b.get("bets") or []}
    vals = bets.get("Match Winner") if kind == "football" else bets.get("Home/Away")
    three = False
    if not vals and kind == "hockey":
        vals, three = bets.get("3Way Result"), True
    o = {}
    for v in vals or []:
        k = {"Home": "H", "Draw": "D", "Away": "A"}.get(v.get("value"))
        try:
            if k:
                o[k] = float(v.get("odd"))
        except (TypeError, ValueError):
            pass
    if kind != "football" and not three:
        o.pop("D", None)
    return o if "H" in o and "A" in o else None


def _parse(kind, resp, prev_book=None):
    cands = {}
    for x in resp:
        for b in x.get("bookmakers") or []:
            n = _norm(b.get("name"))
            if n and n not in cands:
                o = _prices(kind, b)
                if o:
                    cands[n] = (o, b.get("name"), x.get("update"))
    if not cands:
        return None
    rank = lambda n: BOOK_ORDER.index(n) if n in BOOK_ORDER else 99
    pick = min(cands, key=rank)
    if pick != "bet365" and prev_book in cands:   # 대체 북은 바뀌지 않게 유지(변동 화살표 일관성)
        pick = prev_book
    o, raw, upd = cands[pick]
    return {"o": o, "bk": pick, "name": BOOK_NAME.get(pick, raw or pick), "upd": upd}


def odds(g, lite=False):
    """{"book","bs","H","A",("D"),"mv","at","final"} 또는 None. 시작/종료 경기는 마지막 경기 전 배당(1회 조회 후 고정)."""
    kind = g.get("kind")
    if kind not in HOSTS or not g.get("id"):
        return None
    started = g.get("state") != "scheduled"
    key = ("odds", kind, g.get("id"))
    if started:
        with _lk:
            e = _c.get(key)
        cur = e[1] if e else None
        if cur is None and not (e and time.time() < e[0]):
            # 시작 후 1회만 조회: 있으면 하루, 없으면 6시간 동안 다시 안 부름
            cur = _cached(key, 86400, lambda prev: _fetch_odds(kind, g, prev) or prev, 3600)
            if cur is None:
                with _lk:
                    _c[key] = (time.time() + 21600, None)
    else:
        cur = _cached(key, ODDS_TTL, lambda prev: _fetch_odds(kind, g, prev))
    if not cur:
        return None
    bk = cur.get("bk") or "bet365"
    out = dict(cur["o"]); out["book"] = cur.get("name") or BOOK
    out["bs"] = BOOK_SHORT.get(bk, (cur.get("name") or bk)[:4].upper())
    out["mv"] = cur.get("mv") or {}; out["at"] = cur.get("at"); out["final"] = started
    return out


def _fetch_odds(kind, g, prev):
    p = {"fixture" if kind == "football" else "game": g["id"]}
    r = _parse(kind, _get(kind, "/odds", p), (prev or {}).get("bk"))
    if not r:
        return prev
    mv = dict((prev or {}).get("mv") or {}) if prev and prev.get("bk", "bet365") == r["bk"] else {}
    if prev and prev.get("bk", "bet365") == r["bk"]:
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
